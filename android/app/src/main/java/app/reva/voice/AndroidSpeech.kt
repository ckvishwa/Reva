package app.reva.voice

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.core.content.ContextCompat

/**
 * The microphone permission as Android reports it. "Asked before" is remembered here because Android answers
 * "no rationale" both before the first request and after "don't ask again".
 */
class AndroidPermissionGate(
    private val context: Context,
    private val prefs: SharedPreferences,
    private val activity: () -> Activity?,
) : PermissionGate {
    override fun current(): MicPermission {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) return MicPermission.Granted
        if (!prefs.getBoolean(ASKED, false)) return MicPermission.NotAsked
        val canAsk = activity()?.shouldShowRequestPermissionRationale(Manifest.permission.RECORD_AUDIO) ?: false
        return if (canAsk) MicPermission.Denied else MicPermission.DeniedForever
    }

    /** Call when the system dialog is about to be shown. */
    fun markAsked() {
        prefs.edit().putBoolean(ASKED, true).apply()
    }

    private companion object {
        const val ASKED = "mic_permission_asked"
    }
}

/** Whether the phone can recognise speech without sending audio anywhere. */
object AndroidRecognizerAvailability {
    fun check(context: Context): RecognizerAvailability = when {
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU -> RecognizerAvailability.UnknownBeforeAndroid13
        SpeechRecognizer.isOnDeviceRecognitionAvailable(context) -> RecognizerAvailability.OnDevice
        else -> RecognizerAvailability.NotInstalled
    }
}

/**
 * Android's on-device recognizer. Must be created, started and released on the main thread. Only
 * `createOnDeviceSpeechRecognizer` is used, never the default service that may stream audio to a server.
 */
class AndroidSpeechRecognizer(private val context: Context) : Recognizer {
    private var recognizer: SpeechRecognizer? = null

    override fun start(listener: RecognizerListener) {
        val created = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
        recognizer = created
        created.setRecognitionListener(
            object : RecognitionListener {
                override fun onPartialResults(partialResults: Bundle?) {
                    firstResult(partialResults)?.let(listener::onPartial)
                }

                override fun onResults(results: Bundle?) {
                    listener.onFinal(firstResult(results).orEmpty())
                }

                override fun onError(error: Int) {
                    listener.onError(map(error))
                }

                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            },
        )
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        created.startListening(intent)
    }

    override fun stop() {
        recognizer?.stopListening()
    }

    override fun release() {
        val current = recognizer ?: return
        recognizer = null
        current.setRecognitionListener(null)
        current.cancel()
        current.destroy()
    }

    private fun firstResult(bundle: Bundle?): String? =
        bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()

    private fun map(error: Int): RecognizerError = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> RecognizerError.NoSpeech
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> RecognizerError.PermissionRevoked
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY, SpeechRecognizer.ERROR_CLIENT -> RecognizerError.Unavailable
        else -> RecognizerError.Failed
    }
}
