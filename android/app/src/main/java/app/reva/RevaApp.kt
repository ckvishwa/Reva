package app.reva

import android.app.Application
import android.content.Context
import app.reva.sync.AutoSyncController
import app.reva.sync.SharedPrefsAutoSyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import app.reva.data.FinanceRepository
import app.reva.data.KernelFinanceRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.sync.KeystoreDeviceSigner
import app.reva.sync.PairedPcStore
import app.reva.sync.PinnedHttpsTransport
import app.reva.sync.SyncEngine
import app.reva.sync.SyncService
import app.reva.ui.ExportShare
import app.reva.voice.AndroidPermissionGate
import app.reva.voice.AndroidRecognizerAvailability
import app.reva.voice.AndroidServiceLauncher
import app.reva.voice.AndroidSpeechRecognizer
import app.reva.mood.EngineMood
import app.reva.mood.MoodEngine
import app.reva.voice.AndroidTtsSpeaker
import app.reva.voice.NeutralMood
import app.reva.voice.UnavailableReplies
import app.reva.voice.VoiceController
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
            // A sync that applied events from the PC moves the change counter, so open screens reload.
            onApplied = { kernelRepository.markChanged() },
        )
    }

    /** The activity in front, if any; the permission gate needs it to tell "denied" from "blocked". */
    @Volatile
    var currentActivity: java.lang.ref.WeakReference<android.app.Activity>? = null

    val micPermission: AndroidPermissionGate by lazy {
        AndroidPermissionGate(
            context,
            context.getSharedPreferences("reva_voice", Context.MODE_PRIVATE),
        ) { currentActivity?.get() }
    }

    /** One voice session at a time. Recognizer and service are created per session and released at its end. */
    val voice: VoiceController by lazy {
        VoiceController(
            permissions = micPermission,
            availability = { AndroidRecognizerAvailability.check(context) },
            recognizerFactory = { AndroidSpeechRecognizer(context) },
            replies = UnavailableReplies(),
            speaker = AndroidTtsSpeaker(context),
            service = AndroidServiceLauncher(context),
            scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate),
            mood = moodSource(),
        )
    }

    /** The mood engine over the same rules file the PC reads (shipped in the APK from contracts/). */
    private fun moodSource() = try {
        val rules = context.assets.open("contracts/mood-rules.v1.json").bufferedReader().use { it.readText() }
        EngineMood(MoodEngine(org.json.JSONObject(rules)), hour = { java.time.LocalTime.now().hour })
    } catch (_: java.io.IOException) {
        NeutralMood // the rules file is missing from this build: no mood, never a guessed one
    }

    /** Syncs with the paired PC on its own while the app is in front (setting, default on). */
    val autoSync: AutoSyncController by lazy {
        AutoSyncController(
            service = syncService,
            settings = SharedPrefsAutoSyncSettings(context.getSharedPreferences("reva_sync", Context.MODE_PRIVATE)),
            scope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
        )
    }
}

class RevaApp : Application() {
    val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        if (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0) {
            // Debug builds log any disk or network work on the main thread (AR-AND-018).
            android.webkit.WebView.setWebContentsDebuggingEnabled(true) // debug builds only: DevTools over adb
            android.os.StrictMode.setThreadPolicy(
                android.os.StrictMode.ThreadPolicy.Builder().detectAll().penaltyLog().build(),
            )
        }
        // A Finance export is a plain file in the cache for the share sheet; never keep it past the session.
        ExportShare.clear(cacheDir)
    }
}
