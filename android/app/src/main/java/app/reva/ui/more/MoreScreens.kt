package app.reva.ui.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.MutedText
import app.reva.ui.RevaCard
import app.reva.ui.SectionTitle
import app.reva.ui.theme.RevaColors

/** Talk is a placeholder in this slice: no avatar, voice or chat exists on the phone yet, and it says so. */
@Composable
fun TalkScreen(modifier: Modifier = Modifier) {
    LazyColumn(modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Talk", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() }) }
        item {
            RevaCard(modifier = Modifier.testTag("talk_placeholder")) {
                Text("Coming soon", style = MaterialTheme.typography.titleMedium, color = RevaColors.Accent)
                MutedText("Talking to REVA on the phone arrives in a later slice. Nothing here listens, records or sends anything.")
            }
        }
    }
}

private val comingSoon = listOf("Health", "Coach", "Career", "Learn", "Cyber", "Personal", "Memory")

@Composable
fun MoreScreen(versionName: String, modifier: Modifier = Modifier) {
    LazyColumn(modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("More", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() }) }
        item {
            RevaCard(modifier = Modifier.testTag("more_sections")) {
                SectionTitle("Sections")
                comingSoon.forEach { name ->
                    Row(
                        Modifier.fillMaxWidth().heightIn(min = 48.dp).semantics(mergeDescendants = true) { contentDescription = "$name, coming soon" },
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(name, style = MaterialTheme.typography.bodyLarge, color = RevaColors.Secondary)
                        CaptionText("coming soon")
                    }
                }
            }
        }
        item {
            RevaCard(modifier = Modifier.testTag("more_about")) {
                SectionTitle("About this build")
                MutedText("REVA $versionName")
                MutedText("Finance data is encrypted on this phone with a key held by the Android Keystore. It is excluded from Android backups.")
                MutedText("This build has no internet permission, so it cannot send data anywhere.")
            }
        }
    }
}
