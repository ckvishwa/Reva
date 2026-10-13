package app.reva

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.sync.GatewayProtocol
import app.reva.sync.KeystoreDeviceSigner
import java.io.File
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import org.json.JSONArray
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.DeviceSigner
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.KeyProvider
import uniffi.reva_kernel.SyncBatch
import uniffi.reva_kernel.openDomain

/** Test-only key vault: keeps the Kernel key in memory. Never used for real data. */
class MemoryKeyProvider : KeyProvider {
    private val keys = mutableMapOf<String, ByteArray>()

    override fun loadKey(domain: String): ByteArray? = keys[domain]

    override fun storeKey(domain: String, key: ByteArray) {
        keys[domain] = key.copyOf()
    }
}

/** A software P-256 device key, the other side of the pairing in these tests. */
class SoftwareDeviceSigner : DeviceSigner {
    private val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()

    override fun publicKey(): ByteArray = pair.public.encoded

    override fun sign(message: ByteArray): ByteArray =
        Signature.getInstance("SHA256withECDSA").run {
            initSign(pair.private)
            update(message)
            sign()
        }
}

/**
 * The Android Keystore device key against the Kernel's verifier, on the real Keystore of the emulator or phone
 * (API 31 and 36 are both run). Everything lives under throw-away directories and a throw-away alias.
 */
@RunWith(AndroidJUnit4::class)
class KeystoreSignerInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val alias = "reva.test.signing.${System.nanoTime()}"
    private val signer = KeystoreDeviceSigner(alias)
    private val dirs = mutableListOf<File>()
    private val handles = mutableListOf<DomainHandle>()

    @Before fun setUp() = signer.delete()

    @After fun tearDown() {
        handles.forEach { it.close() }
        dirs.forEach { it.deleteRecursively() }
        signer.delete()
    }

    private fun open(): DomainHandle {
        val dir = File(context.noBackupFilesDir, "sync-test-${System.nanoTime()}").also { it.mkdirs(); dirs += it }
        return openDomain("finance", MemoryKeyProvider(), dir.absolutePath).also { handles += it }
    }

    @Test fun the_public_key_is_a_p256_spki_and_stable() {
        val key = signer.publicKey()
        assertEquals("X.509 SubjectPublicKeyInfo for P-256 is 91 bytes", 91, key.size)
        assertTrue(key.contentEquals(signer.publicKey()))
        assertEquals(64, GatewayProtocol.spkiSha256(key).length)
    }

    @Test fun keystore_signatures_verify_and_tampering_breaks_them() {
        val message = "REVA-GW1\nrequest\nPOST\n/sync/pull".toByteArray()
        val signature = signer.sign(message)
        assertTrue("DER encoded", signature[0].toInt() == 0x30)
        assertTrue(GatewayProtocol.verify(signer.publicKey(), message, signature))
        assertFalse(GatewayProtocol.verify(signer.publicKey(), message + 1, signature))
    }

    @Test fun events_signed_by_the_keystore_are_accepted_by_the_kernel_and_forged_ones_are_not() {
        val phone = open()
        val other = open()
        phone.setSigner(signer)
        val otherSigner = SoftwareDeviceSigner()
        other.setSigner(otherSigner)
        phone.registerPeer(other.deviceId(), otherSigner.publicKey(), "PC", listOf("finance"))
        other.registerPeer(phone.deviceId(), signer.publicKey(), "Phone", listOf("finance"))

        phone.command("account.create", """{"id":"acct-main-1","name":"Main","currency":"USD"}""")
        phone.command(
            "transaction.create",
            """{"id":"tx-keystore-1","account_id":"acct-main-1","date":"2026-10-01","amount_minor":-1250,"description":"Signed by the Keystore"}""",
        )
        val batch = phone.syncExport(other.deviceId(), 100u)
        assertEquals(2uL, batch.count)
        val events = JSONArray(batch.eventsJson)
        for (i in 0 until events.length()) assertTrue(events.getJSONObject(i).getString("signature").startsWith("es256:"))

        val report = other.syncApply(phone.deviceId(), batch)
        assertEquals(2uL, report.applied)
        assertEquals(phone.projectionDigest(), other.projectionDigest())

        // The same events with one byte changed are refused whole.
        val forged = JSONArray(batch.eventsJson)
        forged.getJSONObject(1).getJSONObject("payload").put("amount_minor", -1)
        val third = open().also { it.registerPeer(phone.deviceId(), signer.publicKey(), "Phone", listOf("finance")) }
        try {
            third.syncApply(phone.deviceId(), SyncBatch(forged.toString(), batch.cursorFrom, batch.cursorTo, batch.count))
            throw AssertionError("a forged batch must be rejected")
        } catch (_: uniffi.reva_kernel.DomainException.Rejected) {
        }
        assertEquals(0L, third.eventCount())
    }
}
