package app.reva.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import kotlin.coroutines.resume
import kotlin.math.pow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext

/**
 * Speaks with Android's text-to-speech, in two steps so the mouth can follow real audio: the engine writes the
 * sentence to a WAV file, then [AudioTrack] plays it while the loudness of what has actually reached the
 * speaker (the track's play position) is reported through [LevelSink]. Nothing is reported for audio that was
 * never played, and playback and reports stop the moment [stop] is called or the caller is cancelled.
 *
 * Only a voice that works without the network is used: the reply is never sent to a speech server. If the
 * phone has no such voice the reply stays on the screen and nothing is spoken.
 */
class AndroidTtsSpeaker(private val context: Context) : Speaker {
    private var engine: TextToSpeech? = null
    private var track: AudioTrack? = null
    private var focus: AudioFocusRequest? = null

    @Volatile
    private var stopped = false

    override suspend fun speak(text: String, epoch: Int, prosody: Prosody, levels: LevelSink) {
        stopped = false
        val tts = ready() ?: return
        tts.setSpeechRate(prosody.rate.coerceIn(0.5f, 2.0f))
        tts.setPitch(2.0.pow(prosody.pitchSt / 12.0).toFloat().coerceIn(0.5f, 2.0f))
        val file = File(context.cacheDir, "tts-${System.nanoTime()}.wav")
        try {
            if (!synthesize(tts, text, file) || stopped) return
            val clip = withContext(Dispatchers.IO) { Wav.parse(file.readBytes()) } ?: return
            if (!stopped) play(clip, epoch, levels)
        } finally {
            file.delete()
        }
    }

    override fun stop() {
        stopped = true
        engine?.stop()
        track?.let {
            runCatching { it.pause(); it.flush() }
        }
    }

    override fun release() {
        stop()
        track?.let { runCatching { it.release() } }
        track = null
        abandonFocus()
        engine?.let { runCatching { it.shutdown() } }
        engine = null
    }

    // ------------------------------------------------------------------ the engine

    private suspend fun ready(): TextToSpeech? {
        engine?.let { return it }
        val created = suspendCancellableCoroutine<TextToSpeech?> { cont ->
            var instance: TextToSpeech? = null
            instance = TextToSpeech(context) { status ->
                if (cont.isActive) cont.resume(if (status == TextToSpeech.SUCCESS) instance else null)
            }
            cont.invokeOnCancellation { instance?.shutdown() }
        } ?: return null
        val voice = chooseOfflineVoice(created)
        if (voice == null) {
            created.shutdown()
            return null
        }
        created.voice = voice
        engine = created
        return created
    }

    private fun chooseOfflineVoice(tts: TextToSpeech): android.speech.tts.Voice? {
        val wanted = Locale.getDefault()
        val offline = tts.voices.orEmpty().filter {
            !it.isNetworkConnectionRequired && !it.features.contains(TextToSpeech.Engine.KEY_FEATURE_NETWORK_SYNTHESIS)
        }
        return offline.firstOrNull { it.locale.language == wanted.language }
            ?: offline.firstOrNull { it.locale.language == Locale.ENGLISH.language }
    }

    private suspend fun synthesize(tts: TextToSpeech, text: String, file: File): Boolean =
        suspendCancellableCoroutine { cont ->
            val id = "reva-${System.nanoTime()}"
            tts.setOnUtteranceProgressListener(
                object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = Unit
                    override fun onDone(utteranceId: String?) { if (utteranceId == id && cont.isActive) cont.resume(true) }

                    @Deprecated("Required override")
                    override fun onError(utteranceId: String?) { if (utteranceId == id && cont.isActive) cont.resume(false) }

                    override fun onError(utteranceId: String?, errorCode: Int) { if (utteranceId == id && cont.isActive) cont.resume(false) }
                    override fun onStop(utteranceId: String?, interrupted: Boolean) { if (utteranceId == id && cont.isActive) cont.resume(false) }
                },
            )
            val queued = tts.synthesizeToFile(text, Bundle(), file, id)
            if (queued != TextToSpeech.SUCCESS && cont.isActive) cont.resume(false)
            cont.invokeOnCancellation { tts.stop() }
        }

    // ------------------------------------------------------------------ playback and the mouth

    private suspend fun play(clip: PcmClip, epoch: Int, levels: LevelSink) {
        requestFocus()
        val mask = if (clip.channels == 1) AudioFormat.CHANNEL_OUT_MONO else AudioFormat.CHANNEL_OUT_STEREO
        val minimum = AudioTrack.getMinBufferSize(clip.sampleRate, mask, AudioFormat.ENCODING_PCM_16BIT)
        val created = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setAudioFormat(
                AudioFormat.Builder().setSampleRate(clip.sampleRate).setChannelMask(mask)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build(),
            )
            .setBufferSizeInBytes(maxOf(minimum, clip.sampleRate * clip.channels * 2 / 4))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        track = created
        try {
            created.play()
            val chunk = LevelMeter.windowFrames(clip.sampleRate) * clip.channels * 4
            var written = 0
            var reported = 0 // frames already reported as played
            withContext(Dispatchers.IO) {
                while (isActive && !stopped && written < clip.samples.size) {
                    val count = minOf(chunk, clip.samples.size - written)
                    val n = created.write(clip.samples, written, count)
                    if (n <= 0) break
                    written += n
                    reported = report(clip, created, reported, epoch, levels)
                }
                // Let the rest drain, reporting only what the speaker has reached.
                while (isActive && !stopped && created.playbackHeadPosition < clip.frames) {
                    delay(8)
                    reported = report(clip, created, reported, epoch, levels)
                }
                if (!stopped) report(clip, created, reported, epoch, levels)
            }
        } finally {
            runCatching { created.stop() }
            runCatching { created.release() }
            if (track === created) track = null
            abandonFocus()
        }
    }

    /** Reports the windows the track has really played since [reported]; returns the new played frame count. */
    private suspend fun report(clip: PcmClip, track: AudioTrack, reported: Int, epoch: Int, levels: LevelSink): Int {
        val played = minOf(track.playbackHeadPosition, clip.frames)
        if (played <= reported) return reported
        val windows = LevelMeter.windows(clip, reported, played)
        if (windows.isEmpty()) return reported
        withContext(Dispatchers.Main.immediate) {
            if (!stopped) windows.forEach { levels.onLevel(epoch, it.rms, it.positionMs) }
        }
        return reported + windows.size * LevelMeter.windowFrames(clip.sampleRate)
    }

    private fun requestFocus() {
        val manager = context.getSystemService(AudioManager::class.java) ?: return
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
            )
            .build()
        manager.requestAudioFocus(request)
        focus = request
    }

    private fun abandonFocus() {
        val request = focus ?: return
        focus = null
        context.getSystemService(AudioManager::class.java)?.abandonAudioFocusRequest(request)
    }
}
