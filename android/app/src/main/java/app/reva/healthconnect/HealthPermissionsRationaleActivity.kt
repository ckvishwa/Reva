package app.reva.healthconnect

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import app.reva.ui.MutedText
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaTheme

/**
 * Why REVA asks to read Health Connect data. Health Connect opens this screen from its permission sheet and its
 * settings (required for the permission request to be shown at all). It only displays text: it reads nothing,
 * receives no data from the intent, and returns nothing.
 */
class HealthPermissionsRationaleActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            RevaTheme {
                LazyColumn(
                    Modifier.fillMaxSize().testTag("health_connect_rationale"),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    item { Text("How REVA uses Health Connect", style = MaterialTheme.typography.headlineSmall, color = RevaColors.Text) }
                    item {
                        RevaCard {
                            SectionTitle("Read only")
                            MutedText("REVA reads only the types you allow, one at a time. It never writes, edits or deletes anything in Health Connect.")
                        }
                    }
                    HealthConnectType.entries.forEach { type ->
                        item {
                            RevaCard {
                                SectionTitle(type.label)
                                MutedText(type.reason)
                            }
                        }
                    }
                    item {
                        RevaCard {
                            SectionTitle("Where it goes")
                            MutedText(RATIONALE_STORAGE)
                            MutedText(RATIONALE_LIMITS)
                        }
                    }
                    item { SecondaryButton("Close", { finish() }) }
                }
            }
        }
    }

    companion object {
        const val RATIONALE_STORAGE =
            "Daily totals are copied into REVA's encrypted Health store on this phone. They are not sent to any server, " +
                "are not shared with a hosted AI model, and are not part of Android backups."
        const val RATIONALE_LIMITS =
            "REVA shows the numbers as recorded. It does not diagnose, rate your health or suggest medication. " +
                "You can delete everything REVA copied from Health Connect on the Health screen, and turn access off in Health Connect at any time."
    }
}
