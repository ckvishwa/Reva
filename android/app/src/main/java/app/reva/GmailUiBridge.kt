package app.reva

import android.app.Activity
import android.app.PendingIntent
import androidx.activity.result.IntentSenderRequest
import app.reva.connectors.gmail.GmailConnector
import app.reva.connectors.gmail.GmailRemedy
import app.reva.connectors.gmail.GmailState
import app.reva.ui.gmail.GmailAction
import app.reva.ui.gmail.GmailConnectUi
import app.reva.ui.gmail.GmailUiState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** Composition root glue: `ui` owns the Gmail screen's port, `connectors` owns the connection; neither imports the other. */
internal fun gmailUi(connector: GmailConnector, scope: CoroutineScope): GmailConnectUi = GmailConnectUi(
    state = connector.state.map(::gmailUiState).stateIn(scope, SharingStarted.Eagerly, gmailUiState(connector.state.value)),
    connect = { scope.launch { connector.connect() } },
    // Asking again is safe: when access is still granted Google answers without showing anything.
    retry = { scope.launch { connector.connect() } },
    onConsentResult = { result -> scope.launch { connector.onConsentResult(result.resultCode == Activity.RESULT_OK, result.data) } },
    disconnect = { scope.launch { connector.disconnect() } },
    onShown = {
        val current = connector.state.value
        if (connector.wasConnected && current !is GmailState.Connected && current !is GmailState.Working) {
            scope.launch { connector.recheck() }
        }
    },
)

internal fun gmailUiState(state: GmailState): GmailUiState = when (state) {
    is GmailState.Disconnected -> GmailUiState.Disconnected(
        if (state.revokeConfirmed) null
        else "Disconnected on this phone, but Google could not confirm it. You can also remove REVA under Google Account > Security > Third-party connections.",
    )
    GmailState.Working -> GmailUiState.Working
    is GmailState.NeedsUser -> GmailUiState.NeedsUser(IntentSenderRequest.Builder((state.resolution as PendingIntent).intentSender).build())
    is GmailState.Connected -> GmailUiState.Connected("Gmail answered a read-only check (HTTP ${state.httpStatus}). No messages were read.")
    is GmailState.Failed -> GmailUiState.Problem(
        state.failure.message,
        when (state.failure.remedy) {
            GmailRemedy.Connect -> GmailAction.Connect
            GmailRemedy.Retry -> GmailAction.Retry
            GmailRemedy.None -> GmailAction.None
        },
    )
}
