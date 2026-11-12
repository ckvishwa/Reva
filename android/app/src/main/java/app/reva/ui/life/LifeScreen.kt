package app.reva.ui.life

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.MutedText
import app.reva.ui.RevaCard
import app.reva.ui.theme.RevaColors

/** The Life tab's first screen: one entry per built domain, pinned entries first. */
@Composable
fun LifeScreen(pins: LifePins, available: Set<LifeArea>, onOpen: (LifeArea) -> Unit) {
    var order by remember { mutableStateOf(pins.ordered()) }
    var pinned by remember { mutableStateOf(pins.pinned()) }
    var notice by remember { mutableStateOf<String?>(null) }

    LazyColumn(
        Modifier.fillMaxSize().testTag("life_hub"),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text(
                "Life",
                style = MaterialTheme.typography.headlineMedium,
                color = RevaColors.Text,
                modifier = Modifier.semantics { heading() },
            )
        }
        items(order.filter { it in available }, key = { it.key }) { area ->
            val isPinned = area in pinned
            RevaCard(modifier = Modifier.testTag(area.tag).clickable(role = Role.Button) { onOpen(area) }) {
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(Modifier.weight(1f).padding(end = 8.dp)) {
                        Text(area.label, style = MaterialTheme.typography.titleMedium, color = RevaColors.Text)
                        MutedText(area.summary)
                    }
                    TextButton(
                        onClick = {
                            notice = if (pins.toggle(area)) null else "Unpin one first. ${LifePins.MAX_PINS} can be pinned."
                            order = pins.ordered()
                            pinned = pins.pinned()
                        },
                        modifier = Modifier
                            .testTag("${area.tag}_pin")
                            .semantics { contentDescription = if (isPinned) "Unpin ${area.label}" else "Pin ${area.label}" },
                    ) { Text(if (isPinned) "Pinned" else "Pin", color = if (isPinned) RevaColors.Accent else RevaColors.Secondary) }
                }
            }
        }
        notice?.let { text -> item { CaptionText(text, modifier = Modifier.testTag("life_pin_notice")) } }
    }
}

/** Shown above a domain screen opened from the hub, so there is always a visible way back. */
@Composable
fun LifeAreaBar(area: LifeArea, onBack: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        TextButton(
            onClick = onBack,
            modifier = Modifier.testTag("life_back").semantics { contentDescription = "Back to Life" },
        ) { Text("‹ Life", color = RevaColors.Accent) }
        CaptionText(area.label)
    }
}
