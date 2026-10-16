package app.reva.ui.apps

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.phone.ApprovedApps
import app.reva.phone.InstalledApp
import app.reva.phone.LaunchableApps
import app.reva.ui.CaptionText
import app.reva.ui.MutedText
import app.reva.ui.SecondaryButton
import app.reva.ui.theme.RevaColors

/**
 * Apps on this phone REVA may open. Nothing is approved by default; the owner turns each one on. REVA sees only
 * apps with a launcher icon (no package list permission) and opens one only when it is switched on here and the
 * owner says one of its names.
 */
@Composable
fun PhoneAppsScreen(approved: ApprovedApps, installed: LaunchableApps, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val apps = remember { installed.list() }
    var on by remember { mutableStateOf(approved.all().map { it.packageName }.toSet()) }
    LazyColumn(modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            Text("Apps REVA may open", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() })
            MutedText("Say \"open <name>\". Nothing is on until you switch it on. REVA can only see apps that have a launcher icon.")
            SecondaryButton("Back", onBack, Modifier.testTag("apps_back"))
        }
        items(apps, key = { it.packageName }) { app -> AppRow(app, app.packageName in on) { enabled ->
            if (enabled) approved.approve(app) else approved.remove(app.packageName)
            on = approved.all().map { it.packageName }.toSet()
        } }
        if (apps.isEmpty()) item { CaptionText("No launchable apps were found.") }
    }
}

@Composable
private fun AppRow(app: InstalledApp, enabled: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(vertical = 2.dp).testTag("app_row"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(app.label, color = RevaColors.Text, style = MaterialTheme.typography.bodyLarge)
        Switch(checked = enabled, onCheckedChange = onChange, modifier = Modifier.semantics { contentDescription = "REVA may open ${app.label}" })
    }
}
