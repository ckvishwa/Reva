package app.reva.voice

import app.reva.mood.ExpressionEvent

/** Where the microphone permission stands. Text never depends on it. */
enum class MicPermission {
    /** Never asked. The system dialog is allowed. */
    NotAsked,

    /** Granted. */
    Granted,

    /** Asked and refused, but Android will still show the dialog next time. */
    Denied,

    /** Refused with "don't ask again" (or twice): only the system settings can change it. */
    DeniedForever,
}

/** Reads the permission and the system's "can we still ask" answer. The Android version lives in the UI layer. */
interface PermissionGate {
    fun current(): MicPermission
}

/** Raised by [Recognizer] callbacks; every one carries the epoch of the turn that started the recognizer. */
interface RecognizerListener {
    fun onPartial(text: String)
    fun onFinal(text: String)
    fun onError(error: RecognizerError)
}

enum class RecognizerError {
    /** Nothing was said, or nothing could be understood. */
    NoSpeech,

    /** Android revoked or never gave the microphone permission. */
    PermissionRevoked,

    /** The recognizer is busy or was lost; a fresh one may work. */
    Unavailable,

    /** Anything else. */
    Failed,
}

/** One on-device recognizer. [release] must free everything, and is called at the end of every session. */
interface Recognizer {
    fun start(listener: RecognizerListener)
    fun stop()
    fun release()
}

/**
 * Whether speech recognition can run on the phone itself. A recognizer that sends audio to a server is
 * never used (ARD-200 AR-AND-003): if on-device recognition is missing, voice input is off, REVA says why,
 * and typing still works.
 */
sealed interface RecognizerAvailability {
    data object OnDevice : RecognizerAvailability

    /** Android 12 and 12L cannot tell us, so voice input stays off there rather than guess. */
    data object UnknownBeforeAndroid13 : RecognizerAvailability

    data object NotInstalled : RecognizerAvailability
}

object RecognizerPolicy {
    /** The one sentence shown (and spoken nowhere) when voice input cannot be used on the device. */
    fun disclosure(availability: RecognizerAvailability): String? = when (availability) {
        RecognizerAvailability.OnDevice -> null
        RecognizerAvailability.UnknownBeforeAndroid13 ->
            "Voice input needs Android 13 or newer, so it is off. Typing works. Nothing is sent to a server."
        RecognizerAvailability.NotInstalled ->
            "This phone has no on-device speech recognition installed, so voice input is off. Typing works. " +
                "Nothing is sent to a server."
    }

    fun usable(availability: RecognizerAvailability): Boolean = availability == RecognizerAvailability.OnDevice
}

/** Where the answer to a typed or spoken sentence comes from. Only ever words, never evidence of an action. */
interface ReplySource {
    /** The reply text, or null when nothing can answer right now (the caller shows [unavailable]). */
    suspend fun reply(text: String): Reply

    class Reply(val text: String, val source: String)
}

/** How a reply should sound. Comes from the mood engine; it can change speed and pitch, never the words. */
data class Prosody(val rate: Float = 1f, val pitchSt: Int = 0)

/** Told, about 60 times a second while a sentence plays, how loud the audio that reached the speaker is. */
fun interface LevelSink {
    fun onLevel(epoch: Int, rms: Double, tMs: Int)
}

/**
 * Speaks one reply. [speak] returns when the sentence finished or was stopped, and reports the loudness of the
 * audio it actually plays through [levels] (the avatar's mouth follows that and nothing else). After [release]
 * the next [speak] sets everything up again.
 */
interface Speaker {
    suspend fun speak(text: String, epoch: Int, prosody: Prosody, levels: LevelSink)
    fun stop()
    fun release()
}

object SilentSpeaker : Speaker {
    override suspend fun speak(text: String, epoch: Int, prosody: Prosody, levels: LevelSink) = Unit
    override fun stop() = Unit
    override fun release() = Unit
}

/** What the mood engine decided for one turn: how to sound and which face (if any) may be shown. */
class MoodDecision(val prosody: Prosody, val expression: ExpressionEvent?)

/** Chooses mood for a heard sentence. The engine implementation is in `app.reva.mood`; tests can fake it. */
fun interface VoiceMood {
    fun decide(userText: String): MoodDecision
}

object NeutralMood : VoiceMood {
    override fun decide(userText: String) = MoodDecision(Prosody(), null)
}

/** Starts and stops the foreground service that keeps the microphone legal while the app is in use. */
interface ServiceLauncher {
    /** Called only from a tap, with the app in front. Returns false when Android refused. */
    fun start(): Boolean
    fun stop()
}
