package app.reva.voice

import kotlin.math.sqrt

/** A decoded mono-or-stereo 16-bit PCM clip. */
class PcmClip(val sampleRate: Int, val channels: Int, val samples: ShortArray) {
    val frames: Int get() = samples.size / channels
    val durationMs: Long get() = frames * 1000L / sampleRate
}

object Wav {
    /** Parses the PCM16 WAV file Android's `TextToSpeech.synthesizeToFile` writes. Returns null if it is anything else. */
    fun parse(bytes: ByteArray): PcmClip? {
        if (bytes.size < 44 || String(bytes, 0, 4, Charsets.US_ASCII) != "RIFF" || String(bytes, 8, 4, Charsets.US_ASCII) != "WAVE") return null
        var offset = 12
        var channels = 0
        var rate = 0
        var bits = 0
        var format = 0
        while (offset + 8 <= bytes.size) {
            val id = String(bytes, offset, 4, Charsets.US_ASCII)
            var size = le32(bytes, offset + 4)
            val body = offset + 8
            if (id == "fmt " && body + 16 <= bytes.size) {
                format = le16(bytes, body)
                channels = le16(bytes, body + 2)
                rate = le32(bytes, body + 4)
                bits = le16(bytes, body + 14)
            } else if (id == "data") {
                if (format != 1 || bits != 16 || channels !in 1..2 || rate !in 8_000..48_000) return null
                // Some writers leave the size at 0 or past the end while streaming: trust the file length.
                if (size <= 0 || body + size > bytes.size) size = bytes.size - body
                val count = size / 2
                val samples = ShortArray(count - count % channels) { i -> le16(bytes, body + i * 2).toShort() }
                return PcmClip(rate, channels, samples)
            }
            offset = body + size + (size and 1)
        }
        return null
    }

    private fun le16(b: ByteArray, o: Int) = (b[o].toInt() and 0xFF) or ((b[o + 1].toInt() and 0xFF) shl 8)
    private fun le32(b: ByteArray, o: Int) = le16(b, o) or (le16(b, o + 2) shl 16)
}

/**
 * The loudness of the audio that is actually being played, in about 60 windows a second, the same way the
 * Windows app measures it (`MeteringSampleProvider`). The mouth follows this and nothing else, so it moves
 * only with sound that reached the speaker and stops the moment playback stops.
 */
object LevelMeter {
    const val WINDOWS_PER_SECOND = 60

    class Window(val positionMs: Int, val rms: Double)

    fun windowFrames(sampleRate: Int) = maxOf(1, sampleRate / WINDOWS_PER_SECOND)

    /** Windows of [clip] from [fromFrame] up to [toFrame] (exclusive); only whole windows are returned. */
    fun windows(clip: PcmClip, fromFrame: Int, toFrame: Int): List<Window> {
        val size = windowFrames(clip.sampleRate)
        val out = ArrayList<Window>()
        var start = fromFrame
        while (start + size <= minOf(toFrame, clip.frames)) {
            var sum = 0.0
            for (i in 0 until size) {
                var mono = 0.0
                for (c in 0 until clip.channels) mono += clip.samples[(start + i) * clip.channels + c] / 32768.0
                mono /= clip.channels
                sum += mono * mono
            }
            val end = start + size
            out += Window((end * 1000L / clip.sampleRate).toInt(), sqrt(sum / size))
            start = end
        }
        return out
    }
}
