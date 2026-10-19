package app.reva

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import app.reva.healthconnect.AndroidHealthConnectGateway
import app.reva.ui.ExportShare
import app.reva.ui.health.HealthConnectUi
import app.reva.ui.RevaRoot
import app.reva.ui.theme.RevaTheme
import java.lang.ref.WeakReference

/** The single activity. Everything else is Compose. */
class MainActivity : ComponentActivity() {
    private val container get() = (application as RevaApp).container

    override fun onStart() {
        super.onStart()
        container.currentActivity = WeakReference(this)
        container.voice.onForegrounded()
    }

    override fun onStop() {
        // The microphone is never left open behind the screen.
        container.voice.onBackgrounded()
        if (container.currentActivity?.get() === this) container.currentActivity = null
        super.onStop()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dark = android.graphics.Color.parseColor("#0E1013")
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(dark),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.parseColor("#121519")),
        )
        val container = (application as RevaApp).container
        val healthConnect = HealthConnectUi(
            gateway = AndroidHealthConnectGateway(applicationContext),
            permissionFor = AndroidHealthConnectGateway::permission,
            requestContract = AndroidHealthConnectGateway.requestContract(),
            openSettings = { runCatching { startActivity(AndroidHealthConnectGateway.settingsIntent()) } },
        )
        setContent {
            RevaTheme {
                RevaRoot(
                    repository = container.financeRepository,
                    healthRepository = container.healthRepository,
                    healthConnect = healthConnect,
                    versionName = BuildConfig.VERSION_NAME,
                    onShare = { format, bytes -> ExportShare.share(this, format, bytes) },
                    sync = container.syncService,
                    autoSync = container.autoSync,
                    voice = container.voice,
                    pcRequests = container.pcRequests,
                    phoneActions = container.phoneActions,
                    phoneApps = container.approvedApps to container.intentPort,
                    onBeforeMicRequest = { container.micPermission.markAsked() },
                    onOpenAppSettings = {
                        startActivity(
                            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)),
                        )
                    },
                )
            }
        }
    }
}
