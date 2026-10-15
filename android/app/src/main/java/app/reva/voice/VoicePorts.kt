package app.reva.voice

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

/** Speaks one reply. A later slice plugs in Android TTS; until then replies are shown, not spoken. */
interface Speaker {
    /** Returns when the sentence finished or was stopped. [epoch] lets a late finish be ignored. */
    suspend fun speak(text: String, epoch: Int)
    fun stop()
    fun release()
}

object SilentSpeaker : Speaker {
    override suspend fun speak(text: String, epoch: Int) = Unit
    override fun stop() = Unit
    override fun release() = Unit
}

/** Starts and stops the foreground service that keeps the microphone legal while the app is in use. */
interface ServiceLauncher {
    /** Called only from a tap, with the app in front. Returns false when Android refused. */
    fun start(): Boolean
    fun stop()
}
