package app.reva.voice

import java.io.ByteArrayOutputStream
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlaybackTest {
    private fun wav(samples: ShortArray, rate: Int = 22_050, channels: Int = 1, declaredSize: Int? = null, format: Int = 1, bits: Int = 16): ByteArray {
        val data = ByteArray(samples.size * 2)
        samples.forEachIndexed { i, s -> data[i * 2] = (s.toInt() and 0xFF).toByte(); data[i * 2 + 1] = (s.toInt() shr 8).toByte() }
        val out = ByteArrayOutputStream()
        fun le32(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte(), (v shr 16).toByte(), (v shr 24).toByte()))
        fun le16(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte()))
        out.write("RIFF".toByteArray()); le32(36 + data.size); out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); le32(16); le16(format); le16(channels); le32(rate); le32(rate * channels * 2); le16(channels * 2); le16(bits)
        out.write("data".toByteArray()); le32(declaredSize ?: data.size); out.write(data)
        return out.toByteArray()
    }

    private fun tone(frames: Int, amplitude: Double, rate: Int = 22_050) =
        ShortArray(frames) { (sin(2 * PI * 440 * it / rate) * amplitude * 32767).toInt().toShort() }

    @Test fun a_pcm16_wav_is_decoded() {
        val clip = Wav.parse(wav(tone(2205, 0.5)))!!
        assertEquals(22_050, clip.sampleRate)
        assertEquals(1, clip.channels)
        assertEquals(2205, clip.frames)
        assertEquals(100L, clip.durationMs)
    }

    @Test fun a_data_size_left_at_zero_by_a_streaming_writer_uses_the_file_length() {
        val clip = Wav.parse(wav(tone(1000, 0.5), declaredSize = 0))!!
        assertEquals(1000, clip.frames)
    }

    @Test fun anything_that_is_not_pcm16_is_refused() {
        assertNull(Wav.parse(ByteArray(10)))
        assertNull(Wav.parse("not a wav file at all, but long enough to pass the header length check....".toByteArray()))
        assertNull(Wav.parse(wav(tone(100, 0.5), format = 3)))
        assertNull(Wav.parse(wav(tone(100, 0.5), bits = 8)))
        assertNull(Wav.parse(wav(tone(100, 0.5), rate = 1000)))
        assertNotNull(Wav.parse(wav(tone(100, 0.5), channels = 2)))
    }

    @Test fun silence_has_no_level_and_a_sine_has_its_rms() {
        val silent = PcmClip(22_050, 1, ShortArray(22_050))
        assertTrue(LevelMeter.windows(silent, 0, silent.frames).all { it.rms == 0.0 })

        val loud = Wav.parse(wav(tone(22_050, 0.5)))!!
        val windows = LevelMeter.windows(loud, 0, loud.frames)
        assertEquals(22_050 / LevelMeter.windowFrames(22_050), windows.size)
        for (w in windows) assertTrue("rms ${w.rms}", abs(w.rms - 0.5 / Math.sqrt(2.0)) < 0.02)
    }

    @Test fun windows_are_about_sixty_a_second_and_carry_the_play_position() {
        val clip = PcmClip(24_000, 1, ShortArray(24_000))
        val windows = LevelMeter.windows(clip, 0, clip.frames)
        assertEquals(60, windows.size)
        assertEquals(1000, windows.last().positionMs)
        assertTrue(windows.zipWithNext().all { (a, b) -> b.positionMs > a.positionMs })
    }

    @Test fun only_what_was_played_is_measured() {
        val clip = Wav.parse(wav(tone(22_050, 0.5)))!!
        val first = LevelMeter.windows(clip, 0, 5_000)
        val rest = LevelMeter.windows(clip, 5_000, clip.frames)
        assertTrue(first.isNotEmpty() && rest.isNotEmpty())
        assertTrue("nothing past the played frame", first.last().positionMs <= 5_000 * 1000L / 22_050 + 1)
    }

    @Test fun stereo_is_averaged_to_one_level() {
        val samples = ShortArray(22_050 * 2) { if (it % 2 == 0) 16_384 else (-16_384).toShort() } // opposite channels cancel
        val clip = PcmClip(22_050, 2, samples)
        assertTrue(LevelMeter.windows(clip, 0, clip.frames).all { it.rms < 0.001 })
    }
}
