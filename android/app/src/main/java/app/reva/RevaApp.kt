package app.reva

import android.app.Application
import android.content.Context
import app.reva.data.FinanceRepository
import app.reva.data.KernelFinanceRepository
import app.reva.data.KeystoreKeyProvider
import java.io.File
import uniffi.reva_kernel.openDomain

/**
 * Wires the real pieces together. Domain files and their wrapped keys live in noBackupFilesDir, which Android
 * never backs up; the XML backup rule files exclude it explicitly as well.
 */
class AppContainer(private val context: Context) {
    val domainRoot: File get() = File(context.noBackupFilesDir, "domains")
    val keyRoot: File get() = File(context.noBackupFilesDir, "keys")

    val financeRepository: FinanceRepository by lazy {
        KernelFinanceRepository(
            openHandle = {
                val dir = File(domainRoot, "finance").also { it.mkdirs() }
                // The Kernel opens SQLCipher here and may generate the key: always called off the main thread.
                openDomain("finance", KeystoreKeyProvider(keyRoot), dir.absolutePath)
            },
        )
    }
}

class RevaApp : Application() {
    val container: AppContainer by lazy { AppContainer(this) }
}
