package app.reva.brain

import app.reva.data.KeyWrapper
import java.security.GeneralSecurityException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostedSecretsTest {
    private class Blob : SecretBlobStore {
        var value: ByteArray? = null
        override fun read() = value
        override fun write(blob: ByteArray) { value = blob }
        override fun clear() { value = null }
    }
    private class Wrapper : KeyWrapper {
        override fun wrap(domain: String, secret: ByteArray): ByteArray = byteArrayOf(7) + secret.reversedArray()
        override fun unwrap(domain: String, blob: ByteArray): ByteArray {
            if (blob.firstOrNull() != 7.toByte()) throw GeneralSecurityException("tampered")
            return blob.drop(1).toByteArray().reversedArray()
        }
    }

    @Test fun key_is_stored_only_as_a_wrapped_blob_and_can_be_revoked() {
        val blob = Blob()
        val secrets = HostedSecrets(blob, Wrapper())
        assertFalse(secrets.configured())

        secrets.save("test-private-key")

        assertTrue(secrets.configured())
        assertEquals("test-private-key", secrets.read())
        assertFalse(blob.value!!.decodeToString().contains("test-private-key"))
        secrets.clear()
        assertFalse(secrets.configured())
        assertEquals(null, secrets.read())
    }

    @Test fun a_tampered_blob_fails_closed_without_returning_a_key() {
        val blob = Blob().apply { value = byteArrayOf(1, 2, 3) }
        val secrets = HostedSecrets(blob, Wrapper())

        assertFalse(secrets.configured())
        assertEquals(null, secrets.read())
    }
}
