package app.reva

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import app.reva.ui.ExportShare
import app.reva.ui.RevaRoot
import app.reva.ui.theme.RevaTheme

/** The single activity. Everything else is Compose. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dark = android.graphics.Color.parseColor("#0E1013")
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(dark),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.parseColor("#121519")),
        )
        val container = (application as RevaApp).container
        setContent {
            RevaTheme {
                RevaRoot(
                    repository = container.financeRepository,
                    versionName = BuildConfig.VERSION_NAME,
                    onShare = { format, bytes -> ExportShare.share(this, format, bytes) },
                    sync = container.syncService,
                    autoSync = container.autoSync,
                )
            }
        }
    }
}
