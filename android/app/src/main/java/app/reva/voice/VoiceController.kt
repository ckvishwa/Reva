package app.reva.voice

import app.reva.language.Outcomes
import app.reva.language.Rules
import app.reva.mood.ExpressionEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class Who { You, Reva, Notice }

data class TalkLine(val id: Int, val who: Who, val text: String)

data class TalkUi(
    val state: VoiceState = VoiceState.Idle,
    val lines: List<TalkLine> = emptyList(),
    /** What the recognizer has heard so far in this utterance. Display only. */
    val partial: String = "",
    val permission: MicPermission = MicPermission.NotAsked,
    /** Null when voice input can be used; otherwise the sentence that says why not. */
    val voiceOffReason: String? = null,
    /** True exactly while the recognizer is open. The avatar's "listening" pose follows this and nothing else. */
    val micOpen: Boolean = false,
    /** A typed turn is waiting for its reply. */
    val thinking: Boolean = false,
    /** The current turn epoch; the avatar tags everything it is told with it. */
    val epoch: Int = 0,
    /** The last recognizer or service failure is still on screen; the avatar shows its error pose. */
    val failed: Boolean = false,
    /** The face the mood engine allows for the newest reply, and a counter so each one is shown once. */
    val expression: ExpressionEvent? = null,
    val expressionSeq: Int = 0,
)

/** One loudness reading of the audio being played, for the avatar's mouth. */
data class Level(val epoch: Int, val rms: Double, val tMs: Int)

sealed interface TalkEffect {
    /** Show the system microphone dialog. Only ever emitted in answer to a tap. */
    data object RequestMicPermission : TalkEffect
}

/**
 * Runs one voice session on the phone: tap, permission, on-device recognizer, reply, speech, release.
 * Everything runs on the main thread (Android's recognizer requires it) and nothing here blocks: replies
 * and speech are suspending calls in [scope].
 *
 * Rules that the tests pin down:
 *  - The microphone permission dialog is shown only after a tap on the mic button.
 *  - Text always works: nothing about typing depends on the permission or the recognizer.
 *  - A recognizer that is not on-device is never used; the reason is shown instead.
 *  - Results carry the epoch of the turn that asked for them; stale ones are dropped.
 *  - Recognizer, speaker and the foreground service are released at the end of every session, on every
 *    path (finished, no speech, error, revoked, backgrounded, stopped, closed).
 */
class VoiceController(
    private val permissions: PermissionGate,
    private val availability: () -> RecognizerAvailability,
    private val recognizerFactory: () -> Recognizer,
    private val replies: ReplySource,
    private val speaker: Speaker,
    private val service: ServiceLauncher,
    private val scope: CoroutineScope,
    private val mood: VoiceMood = NeutralMood,
) {
    private val session = VoiceSession()
    private val _ui = MutableStateFlow(TalkUi(permission = permissions.current(), voiceOffReason = reason()))
    val ui: StateFlow<TalkUi> = _ui.asStateFlow()
    private val _effects = MutableSharedFlow<TalkEffect>(extraBufferCapacity = 4)
    val effects: SharedFlow<TalkEffect> = _effects.asSharedFlow()

    private val _levels = MutableSharedFlow<Level>(extraBufferCapacity = 64)

    /** Loudness of what is playing, only while this session is speaking and only for the current epoch. */
    val levels: SharedFlow<Level> = _levels.asSharedFlow()

    private var lastAnswer: String? = null
    private var recognizer: Recognizer? = null
    private var turn: Job? = null
    private var nextLineId = 0

    private fun reason(): String? = RecognizerPolicy.disclosure(availability())

    // ------------------------------------------------------------------ taps and text

    /** The mic button. Starts a session, finishes the utterance, or interrupts a reply. */
    fun onMicTapped() {
        when (session.state) {
            VoiceState.Idle -> beginVoice()
            VoiceState.Listening -> recognizer?.stop() // "done talking": the final result follows
            VoiceState.Speaking, VoiceState.Reasoning, VoiceState.Transcribing,
            VoiceState.Endpointing, VoiceState.ApprovalPending, VoiceState.Executing,
            -> interruptAndListen()
            else -> endSession(null)
        }
    }

    /** Typed text. Needs no permission, no recognizer, no service. */
    fun onTextSubmitted(raw: String) {
        val text = raw.trim().take(MAX_TEXT)
        if (text.isEmpty()) return
        endSession(null) // a typed sentence replaces whatever voice turn was running
        val epoch = session.beginTurn()
        addLine(Who.You, text)
        if (isControl(text, "assistant.stop")) {
            _ui.update { it.copy(epoch = session.epoch) }
            return // stop: silence, nothing else
        }
        _ui.update { it.copy(thinking = true, failed = false, epoch = epoch) }
        turn = scope.launch {
            val answer = answerFor(text)
            if (!session.isCurrent(epoch)) return@launch
            addLine(Who.Reva, answer)
            _ui.update { it.copy(thinking = false) }
        }
    }

    /** The result of the system dialog (or of coming back from system settings). */
    fun onPermissionChanged() {
        val now = permissions.current()
        _ui.update { it.copy(permission = now) }
        if (session.state != VoiceState.AcquiringPermission) return
        when (now) {
            MicPermission.Granted -> openMic()
            MicPermission.Denied ->
                endSession("The microphone permission was refused. Typing still works; tap the mic to try again.")
            MicPermission.DeniedForever ->
                endSession("The microphone is blocked for REVA. Typing still works; turn it on in the app's settings.")
            MicPermission.NotAsked -> endSession(null)
        }
    }

    /** The stop button, the notification's Stop action, or anything else that ends the session. */
    fun onStopTapped() = endSession(null)

    // ------------------------------------------------------------------ lifecycle

    /** The app left the screen. The microphone is never left open behind it. */
    fun onBackgrounded() {
        if (session.state != VoiceState.Idle) endSession("Stopped listening because REVA left the screen.")
    }

    /** The app came back. The permission may have been changed in system settings meanwhile. */
    fun onForegrounded() {
        _ui.update { it.copy(permission = permissions.current(), voiceOffReason = reason()) }
    }

    /** Android took the microphone permission away while the app was running. */
    fun onPermissionRevoked() {
        val wasActive = session.state != VoiceState.Idle
        endSession(if (wasActive) "The microphone permission was turned off, so I stopped listening. Typing still works." else null)
        _ui.update { it.copy(permission = permissions.current()) }
    }

    /** The screen is gone for good. */
    fun close() {
        endSession(null)
    }

    // ------------------------------------------------------------------ the voice path

    private fun beginVoice() {
        val off = reason()
        _ui.update { it.copy(voiceOffReason = off) }
        if (off != null) {
            addLine(Who.Notice, off)
            return
        }
        session.beginTurn()
        session.go(VoiceState.AcquiringPermission)
        _ui.update { it.copy(failed = false) }
        publishState()
        val now = permissions.current()
        _ui.update { it.copy(permission = now) }
        when (now) {
            MicPermission.Granted -> openMic()
            MicPermission.NotAsked, MicPermission.Denied -> _effects.tryEmit(TalkEffect.RequestMicPermission)
            MicPermission.DeniedForever ->
                endSession("The microphone is blocked for REVA. Typing still works; turn it on in the app's settings.")
        }
    }

    private fun interruptAndListen() {
        turn?.cancel()
        speaker.stop()
        val epoch = session.interrupt()
        if (epoch == null) {
            endSession(null)
            return
        }
        // Back to Listening only if the microphone can really be opened; otherwise go quiet and idle.
        if (permissions.current() != MicPermission.Granted || !RecognizerPolicy.usable(availability())) {
            endSession(null)
            return
        }
        startRecognizer(epoch)
    }

    private fun openMic() {
        if (!service.start()) {
            endSession("Android would not start the microphone service, so I can't listen. Typing still works.")
            markFailed()
            return
        }
        val epoch = session.epoch
        if (!session.go(VoiceState.Listening)) {
            releaseMic()
            return
        }
        startRecognizer(epoch)
    }

    private fun startRecognizer(epoch: Int) {
        releaseMic(stopService = false)
        val fresh = try {
            recognizerFactory()
        } catch (_: RuntimeException) {
            endSession("The speech recognizer could not start. Typing still works.")
            return
        }
        recognizer = fresh
        publishState(micOpen = true, partial = "")
        fresh.start(
            object : RecognizerListener {
                override fun onPartial(text: String) {
                    if (!session.isCurrent(epoch) || session.state != VoiceState.Listening) return
                    _ui.update { it.copy(partial = text.take(MAX_TEXT)) }
                }

                override fun onFinal(text: String) = heard(epoch, text)

                override fun onError(error: RecognizerError) = recognizerFailed(epoch, error)
            },
        )
    }

    private fun heard(epoch: Int, raw: String) {
        if (!session.isCurrent(epoch) || session.state != VoiceState.Listening) return
        val text = raw.trim().take(MAX_TEXT)
        releaseMic() // the microphone closes the moment the utterance is over
        if (text.isEmpty()) {
            endSession("I didn't catch that.")
            return
        }
        session.go(VoiceState.Endpointing)
        session.go(VoiceState.Transcribing)
        session.go(VoiceState.Reasoning)
        publishState(micOpen = false, partial = "")
        addLine(Who.You, text)
        if (isControl(text, "assistant.stop")) {
            endSession(null) // stop: silence, nothing else
            return
        }
        val decision = mood.decide(text)
        turn = scope.launch {
            val answer = answerFor(text)
            if (!session.isCurrent(epoch)) return@launch
            addLine(Who.Reva, answer)
            if (!session.go(VoiceState.Speaking)) return@launch
            _ui.update { it.copy(expression = decision.expression, expressionSeq = it.expressionSeq + 1) }
            publishState()
            speaker.speak(answer, epoch, decision.prosody) { e, rms, tMs ->
                if (session.isCurrent(e) && session.state == VoiceState.Speaking) _levels.tryEmit(Level(e, rms, tMs))
            }
            if (!session.isCurrent(epoch)) return@launch
            endSession(null)
        }
    }

    private fun isControl(text: String, capability: String) = Rules.controlCapability(Rules.clean(text)) == capability

    /** The words for this sentence. "Repeat" replays only what was already said; nothing new is claimed. */
    private suspend fun answerFor(text: String): String {
        val answer = if (isControl(text, "assistant.repeat")) {
            lastAnswer ?: Outcomes.NOTHING_TO_REPEAT
        } else {
            replies.reply(text).text.take(MAX_REPLY)
        }
        lastAnswer = answer.takeIf { it != Outcomes.NOTHING_TO_REPEAT } ?: lastAnswer
        return answer
    }

    private fun recognizerFailed(epoch: Int, error: RecognizerError) {
        if (!session.isCurrent(epoch)) return
        when (error) {
            RecognizerError.NoSpeech -> endSession("I didn't catch that.")
            RecognizerError.PermissionRevoked -> {
                endSession("The microphone permission was turned off, so I stopped listening. Typing still works.")
                _ui.update { it.copy(permission = permissions.current()) }
            }
            RecognizerError.Unavailable -> {
                endSession("The speech recognizer is busy. Try the mic again in a moment.")
                markFailed()
            }
            RecognizerError.Failed -> {
                endSession("Speech recognition failed. Typing still works.")
                markFailed()
            }
        }
    }

    // ------------------------------------------------------------------ ending

    /** Ends the session on every path: new epoch, Idle, recognizer closed, service stopped, speaker released. */
    private fun endSession(notice: String?) {
        turn?.cancel()
        turn = null
        speaker.stop()
        releaseMic()
        session.cancel()
        speaker.release()
        _ui.update {
            it.copy(state = VoiceState.Idle, micOpen = false, partial = "", thinking = false, epoch = session.epoch)
        }
        if (notice != null) addLine(Who.Notice, notice)
    }

    private fun releaseMic(stopService: Boolean = true) {
        recognizer?.release()
        recognizer = null
        if (stopService) service.stop()
        _ui.update { it.copy(micOpen = false) }
    }

    private fun publishState(micOpen: Boolean = _ui.value.micOpen, partial: String = _ui.value.partial) {
        _ui.update { it.copy(state = session.state, micOpen = micOpen, partial = partial, epoch = session.epoch) }
    }

    private fun markFailed() {
        _ui.update { it.copy(failed = true) }
    }

    private fun addLine(who: Who, text: String) {
        _ui.update {
            val lines = (it.lines + TalkLine(nextLineId++, who, text)).takeLast(MAX_LINES)
            it.copy(lines = lines)
        }
    }

    companion object {
        const val MAX_TEXT = 500
        const val MAX_REPLY = 2000
        const val MAX_LINES = 50
    }
}
