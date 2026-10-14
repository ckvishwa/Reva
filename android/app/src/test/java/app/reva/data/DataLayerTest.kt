package app.reva.data

import app.reva.ui.ExportShare
import java.io.File
import java.nio.file.Files
import java.security.GeneralSecurityException
import java.time.LocalDate
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.KeyProviderException

/** AES-GCM with an in-memory key: the same blob layout as the Android Keystore wrapper, testable on a JVM. */
private class MemoryWrapper(var key: ByteArray = ByteArray(32) { it.toByte() }, var present: Boolean = true) : KeyWrapper {
    override fun wrap(domain: String, secret: ByteArray): ByteArray {
        val iv = ByteArray(12) { (it + 1).toByte() }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        return iv + cipher.doFinal(secret)
    }

    override fun unwrap(domain: String, blob: ByteArray): ByteArray {
        if (!present) throw GeneralSecurityException("Keystore key is missing")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, blob, 0, 12))
        return cipher.doFinal(blob, 12, blob.size - 12)
    }
}

class KeystoreKeyProviderTest {
    private lateinit var dir: File

    @Before fun setUp() {
        dir = Files.createTempDirectory("reva-keys-").toFile()
    }

    @After fun tearDown() {
        dir.deleteRecursively()
    }

    private val secret = ByteArray(32) { (it * 3).toByte() }

    @Test fun a_fresh_install_has_no_key() {
        assertNull(KeystoreKeyProvider(dir, MemoryWrapper()).loadKey("finance"))
    }

    @Test fun a_stored_key_comes_back_after_a_restart() {
        KeystoreKeyProvider(dir, MemoryWrapper()).storeKey("finance", secret)
        assertArrayEquals(secret, KeystoreKeyProvider(dir, MemoryWrapper()).loadKey("finance"))
    }

    @Test fun only_the_wrapped_key_is_on_disk_never_the_key_itself() {
        KeystoreKeyProvider(dir, MemoryWrapper()).storeKey("finance", secret)
        val bytes = File(dir, "finance.key").readBytes()
        assertEquals(12 + 32 + 16, bytes.size) // IV + key + GCM tag
        assertFalse(bytes.toList().windowed(secret.size).any { it == secret.toList() })
        assertFalse(File(dir, "finance.key.tmp").exists())
    }

    @Test fun an_existing_key_is_never_overwritten() {
        val provider = KeystoreKeyProvider(dir, MemoryWrapper())
        provider.storeKey("finance", secret)
        try {
            provider.storeKey("finance", ByteArray(32) { 9 })
            fail("storing over an existing key must be refused")
        } catch (_: KeyProviderException) {
        }
        assertArrayEquals(secret, provider.loadKey("finance"))
    }

    @Test fun a_lost_keystore_key_fails_closed_instead_of_reporting_no_key() {
        val wrapper = MemoryWrapper()
        KeystoreKeyProvider(dir, wrapper).storeKey("finance", secret)
        wrapper.present = false
        try {
            KeystoreKeyProvider(dir, wrapper).loadKey("finance")
            fail("expected KeyProviderException")
        } catch (_: KeyProviderException) {
        }
    }

    @Test fun a_tampered_blob_fails_closed() {
        KeystoreKeyProvider(dir, MemoryWrapper()).storeKey("finance", secret)
        val file = File(dir, "finance.key")
        val bytes = file.readBytes()
        bytes[20] = (bytes[20].toInt() xor 1).toByte()
        file.writeBytes(bytes)
        try {
            KeystoreKeyProvider(dir, MemoryWrapper()).loadKey("finance")
            fail("expected KeyProviderException")
        } catch (_: KeyProviderException) {
        }
    }

    @Test fun domain_names_cannot_escape_the_key_directory() {
        for (bad in listOf("../x", "a/b", "", "Finance", "a.b")) {
            try {
                KeystoreKeyProvider(dir, MemoryWrapper()).loadKey(bad)
                fail("accepted $bad")
            } catch (_: IllegalArgumentException) {
            }
        }
    }
}

class ErrorTranslationTest {
    @Test fun kernel_errors_become_safe_messages() {
        assertEquals(ErrorKind.Locked, KernelFinanceRepository.translate(DomainException.Locked()).kind)
        assertEquals(ErrorText.LOCKED, KernelFinanceRepository.translate(DomainException.Locked()).message)
        assertEquals(ErrorKind.KeyLost, KernelFinanceRepository.translate(DomainException.WrongKey()).kind)
        assertEquals(ErrorKind.Corrupt, KernelFinanceRepository.translate(DomainException.Corrupt()).kind)
        val validation = KernelFinanceRepository.translate(DomainException.Validation("category", "no such category"))
        assertEquals(ErrorKind.Validation, validation.kind)
        assertEquals("category", validation.field)
        assertEquals("no such category", validation.detail)
        assertEquals("category: no such category", validation.message)
    }

    @Test fun internal_details_never_reach_the_message() {
        val error = KernelFinanceRepository.translate(DomainException.MigrationFailed("C:\\secret\\path token=abc"))
        assertEquals(ErrorKind.Internal, error.kind)
        assertFalse(error.message.contains("secret"))
        assertTrue(error.message.startsWith("REVA hit an internal error"))
    }
}

class ExportShareTest {
    @Test fun file_names_and_types() {
        val day = LocalDate.of(2026, 10, 12)
        assertEquals("reva-finance-2026-10-12.csv", ExportShare.fileName("csv", day))
        assertEquals("reva-finance-2026-10-12.json", ExportShare.fileName("json", day))
        assertEquals("text/csv", ExportShare.mimeType("csv"))
        assertEquals("application/json", ExportShare.mimeType("json"))
    }
}

class ExportCleanupTest {
    @Test fun clear_removes_every_shared_export_and_only_those() {
        val cache = Files.createTempDirectory("reva-cache-").toFile()
        try {
            File(cache, "exports").mkdirs()
            File(cache, "exports/reva-finance-2026-10-12.csv").writeText("secret")
            File(cache, "exports/reva-finance-2026-10-11.json").writeText("secret")
            File(cache, "other.tmp").writeText("keep")
            ExportShare.clear(cache)
            assertEquals(0, File(cache, "exports").listFiles()!!.size)
            assertTrue(File(cache, "other.tmp").exists())
            ExportShare.clear(File(cache, "missing")) // no directory yet: harmless
        } finally {
            cache.deleteRecursively()
        }
    }
}

class ReadUpToTest {
    @Test fun reads_everything_under_the_limit_and_stops_one_past_it() {
        val data = ByteArray(200_000) { (it % 251).toByte() }
        assertArrayEquals(data, app.reva.ui.readUpTo(data.inputStream(), 1_000_000))
        val capped = app.reva.ui.readUpTo(data.inputStream(), 100_001)
        assertEquals(100_001, capped.size)
        assertArrayEquals(data.copyOf(100_001), capped)
        assertEquals(0, app.reva.ui.readUpTo(ByteArray(0).inputStream(), 10).size)
    }
}
