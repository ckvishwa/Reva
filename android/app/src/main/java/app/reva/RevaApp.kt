package app.reva

import android.app.Application
import android.content.Context
import app.reva.data.FinanceRepository
import app.reva.data.KernelFinanceRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.sync.KeystoreDeviceSigner
import app.reva.sync.PairedPcStore
import app.reva.sync.PinnedHttpsTransport
import app.reva.sync.SyncEngine
import app.reva.sync.SyncService
import app.reva.ui.ExportShare
import java.io.File
import uniffi.reva_kernel.openDomain

/**
 * Wires the real pieces together. Domain files and their wrapped keys live in noBackupFilesDir, which Android
 * never backs up; the XML backup rule files exclude it explicitly as well.
 */
class AppContainer(private val context: Context) {
    val domainRoot: File get() = File(context.noBackupFilesDir, "domains")
    val keyRoot: File get() = File(context.noBackupFilesDir, "keys")

    /** Pairing record (public data only). Under noBackupFilesDir, so it is excluded from backups like the keys. */
    val syncRoot: File get() = File(context.noBackupFilesDir, "sync")

    private val kernelRepository: KernelFinanceRepository by lazy {
        KernelFinanceRepository(
            openHandle = {
                val dir = File(domainRoot, "finance").also { it.mkdirs() }
                // The Kernel opens SQLCipher here and may generate the key: always called off the main thread.
                openDomain("finance", KeystoreKeyProvider(keyRoot), dir.absolutePath)
            },
        )
    }

    val financeRepository: FinanceRepository get() = kernelRepository

    /** Pairing and LAN sync with the user's own PC. Signs with a Keystore key; pins the PC's TLS key from the QR code. */
    val syncService: SyncService by lazy {
        SyncEngine(
            kernel = { kernelRepository.kernelHandle() },
            signer = KeystoreDeviceSigner(),
            store = PairedPcStore(File(syncRoot, "paired_pc.json")),
            transport = PinnedHttpsTransport(),
            deviceName = android.os.Build.MODEL ?: "Android phone",
        )
    }
}

class RevaApp : Application() {
    val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        // A Finance export is a plain file in the cache for the share sheet; never keep it past the session.
        ExportShare.clear(cacheDir)
    }
}
