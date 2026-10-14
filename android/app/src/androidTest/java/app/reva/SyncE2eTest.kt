package app.reva

import android.content.Context
import android.os.Bundle
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.reva.data.KernelFinanceRepository
import app.reva.data.NewTransaction
import app.reva.data.Outcome
import app.reva.sync.KeystoreDeviceSigner
import app.reva.sync.PairPoll
import app.reva.sync.PairedPcStore
import app.reva.sync.PinnedHttpsTransport
import app.reva.sync.SyncEngine
import app.reva.sync.SyncException
import app.reva.sync.SyncFailure
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.KeyProvider
import uniffi.reva_kernel.openDomain

/** Keeps the throw-away Kernel key in a file so a later run of this test can reopen the same data. Test data only. */
private class FileKeyProvider(private val dir: File) : KeyProvider {
    override fun loadKey(domain: String): ByteArray? = File(dir, "$domain.key").takeIf { it.exists() }?.readBytes()

    override fun storeKey(domain: String, key: ByteArray) {
        dir.mkdirs()
        File(dir, "$domain.key").writeBytes(key)
    }
}

/**
 * Pair with a REAL gateway on the host and sync, driven step by step by tools/android/sync_e2e.py (it starts
 * the Core and gateway, reaches this device through `adb reverse`, approves on the PC, adds the PC-side
 * expense, revokes). The two sides talk through small files in [mailbox]; progress goes back to the host as
 * instrumentation status lines. Skipped unless the host passes `-e syncMailbox <dir>`.
 *
 * It uses the real SyncEngine, the real pinned HTTPS transport, the real Android Keystore device key (a
 * throw-away alias) and the real Kernel; only the Kernel's file key is a plain file, and the data is a
 * throw-away directory, never the app's own Finance data. Airplane mode is not needed here (this suite talks
 * to the host on purpose); the airplane-mode suite is KernelConformanceTest.
 */
@RunWith(AndroidJUnit4::class)
class SyncE2eTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val mailbox: File? = InstrumentationRegistry.getArguments().getString("syncMailbox")?.let(::File)

    private fun status(key: String, value: String) {
        val bundle = Bundle().apply { putString(key, value) }
        InstrumentationRegistry.getInstrumentation().sendStatus(0, bundle)
    }

    /** Waits for the host to write [name] in the mailbox and returns its text. */
    private fun await(name: String, seconds: Int = 120): String {
        val file = File(mailbox!!, name)
        val deadline = System.currentTimeMillis() + seconds * 1000L
        while (System.currentTimeMillis() < deadline) {
            if (file.exists()) {
                val text = file.readText().trim()
                file.delete()
                return text
            }
            Thread.sleep(200)
        }
        fail("the host never sent '$name'")
        return ""
    }

    @Test fun pair_sync_both_directions_then_revoke() = runBlocking {
        assumeTrue("host-driven: run tools/android/sync_e2e.py", mailbox != null)
        val root = File(context.noBackupFilesDir, "sync-e2e").also { it.deleteRecursively(); it.mkdirs() }
        val signer = KeystoreDeviceSigner("reva.e2e.signing").also { it.delete() }
        val handle = openDomain("finance", FileKeyProvider(File(root, "keys")), File(root, "data").also { it.mkdirs() }.absolutePath)
        val repository = KernelFinanceRepository(openHandle = { handle })
        val engine = SyncEngine(
            kernel = { handle },
            signer = signer,
            store = PairedPcStore(File(root, "paired_pc.json")),
            transport = PinnedHttpsTransport(),
            deviceName = "Emulator ${android.os.Build.VERSION.SDK_INT}",
        )
        try {
            status("e2e", "ready")
            val qr = await("qr")
            val start = engine.startPairing(qr)
            status("fingerprint", start.fingerprint)

            // The host compares the digits, approves on the PC, and we poll like the Devices screen does.
            var paired = false
            val deadline = System.currentTimeMillis() + 90_000
            while (System.currentTimeMillis() < deadline && !paired) {
                when (val poll = engine.pollPairing()) {
                    PairPoll.Pending -> Thread.sleep(500)
                    is PairPoll.Approved -> paired = true.also { status("paired", poll.pc.deviceId) }
                    else -> fail("pairing ended with $poll")
                }
            }
            assertTrue("paired", paired)

            await("go_sync1") // the PC has added an account
            val first = engine.syncNow()
            status("sync1", "received=${first.receivedEvents} applied=${first.applied}")
            val account = (repository.balances() as Outcome.Ok).value.single().accountId
            val added = repository.addTransaction(NewTransaction(account, "2026-10-02", -4300, "Phone taxi (e2e)", null, null))
            assertTrue(added is Outcome.Ok)
            status("phone_expense", "added")

            await("go_sync2") // the PC has added its own expense meanwhile
            val second = engine.syncNow()
            status("sync2", "sent=${second.sentEvents} received=${second.receivedEvents}")
            status("digest", handle.projectionDigest())
            status("transactions", (repository.transactions(null, 50) as Outcome.Ok).value.joinToString("|") { it.description })

            await("go_revoked") // the PC has revoked this phone
            try {
                engine.syncNow()
                fail("a revoked phone must not sync")
            } catch (e: SyncException) {
                assertEquals(SyncFailure.Unauthorized, e.failure)
                status("after_revoke", "unauthorized")
            }
        } finally {
            handle.close()
            signer.delete()
            root.deleteRecursively()
        }
    }
}
