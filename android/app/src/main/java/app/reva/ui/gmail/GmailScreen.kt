package app.reva.ui.gmail

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.ActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import app.reva.ui.theme.RevaColors
import kotlinx.coroutines.flow.StateFlow

/** What the Gmail screen shows. Built by the composition root from the connector; carries no token or mail. */
sealed interface GmailUiState {
    data class Disconnected(val note: String? = null) : GmailUiState
    data object Working : GmailUiState
    /** Google's account picker or consent screen must be shown. */
    class NeedsUser(val request: IntentSenderRequest) : GmailUiState
    data class Connected(val detail: String) : GmailUiState
    data class Problem(val message: String, val action: GmailAction) : GmailUiState
}

enum class GmailAction { Connect, Retry, None }

/** The Gmail screen's port. `ui` never sees the connector; MainActivity adapts one to the other. */
class GmailConnectUi(
    val state: StateFlow<GmailUiState>,
    val connect: () -> Unit,
    val retry: () -> Unit,
    val onConsentResult: (ActivityResult) -> Unit,
    val disconnect: () -> Unit,
    /** Called when the screen opens: re-checks an earlier connection without showing Google's screens. */
    val onShown: () -> Unit,
)

const val GMAIL_SCOPE_EXPLANATION =
    "REVA asks Google for read-only Gmail access (gmail.readonly). That permission lets REVA read every message " +
        "in your mailbox. It cannot send, change or delete mail. This version only checks that the connection " +
        "works: it reads no message content, and nothing from Gmail leaves this phone."

@Composable
fun GmailScreen(gmail: GmailConnectUi, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val state by gmail.state.collectAsState()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) {
        gmail.onConsentResult(it)
    }
    LaunchedEffect(Unit) { gmail.onShown() }
    LaunchedEffect(state) {
        (state as? GmailUiState.NeedsUser)?.let { launcher.launch(it.request) }
    }
    LazyColumn(modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Gmail", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() }) }
        item {
            RevaCard(modifier = Modifier.testTag("gmail_scope")) {
                SectionTitle("What connecting allows")
                MutedText(GMAIL_SCOPE_EXPLANATION)
            }
        }
        item {
            RevaCard(modifier = Modifier.testTag("gmail_status")) {
                SectionTitle("Status")
                when (val s = state) {
                    is GmailUiState.Disconnected -> {
                        MutedText("Not connected.", Modifier.testTag("gmail_state_disconnected"))
                        s.note?.let { CaptionText(it, Modifier.testTag("gmail_note")) }
                        PrimaryButton("Connect Gmail", gmail.connect, Modifier.testTag("gmail_connect"))
                    }
                    GmailUiState.Working, is GmailUiState.NeedsUser ->
                        MutedText("Waiting for Google…", Modifier.testTag("gmail_state_working"))
                    is GmailUiState.Connected -> {
                        Text("Connected", style = MaterialTheme.typography.titleMedium, color = RevaColors.Accent, modifier = Modifier.testTag("gmail_state_connected"))
                        CaptionText(s.detail)
                        SecondaryButton("Check again", gmail.retry, Modifier.testTag("gmail_check"))
                        SecondaryButton("Disconnect", gmail.disconnect, Modifier.testTag("gmail_disconnect"))
                    }
                    is GmailUiState.Problem -> {
                        ErrorText(s.message, Modifier.testTag("gmail_state_problem"))
                        when (s.action) {
                            GmailAction.Connect -> PrimaryButton("Connect Gmail", gmail.connect, Modifier.testTag("gmail_connect"))
                            GmailAction.Retry -> PrimaryButton("Try again", gmail.retry, Modifier.testTag("gmail_retry"))
                            GmailAction.None -> Unit
                        }
                        SecondaryButton("Disconnect", gmail.disconnect, Modifier.testTag("gmail_disconnect"))
                    }
                }
            }
        }
        item { SecondaryButton("Back", onBack, Modifier.testTag("gmail_back")) }
    }
}
