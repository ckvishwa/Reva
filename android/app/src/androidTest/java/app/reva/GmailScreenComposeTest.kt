package app.reva

import androidx.activity.result.ActivityResult
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.connectors.gmail.GmailFailure
import app.reva.connectors.gmail.GmailState
import app.reva.ui.gmail.GMAIL_SCOPE_EXPLANATION
import app.reva.ui.gmail.GmailConnectUi
import app.reva.ui.gmail.GmailScreen
import app.reva.ui.gmail.GmailUiState
import app.reva.ui.theme.RevaTheme
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** CON-1: the Gmail screen in each state, with a fake port (no Google, no network). */
@RunWith(AndroidJUnit4::class)
class GmailScreenComposeTest {
    @get:Rule val compose = createComposeRule()

    private val calls = mutableListOf<String>()
    private val state = MutableStateFlow<GmailUiState>(GmailUiState.Disconnected())
    private val port = GmailConnectUi(
        state = state,
        connect = { calls += "connect" },
        retry = { calls += "retry" },
        onConsentResult = { _: ActivityResult -> calls += "consent" },
        disconnect = { calls += "disconnect" },
        onShown = { calls += "shown" },
    )

    private fun show() = compose.setContent { RevaTheme { GmailScreen(port, onBack = { calls += "back" }) } }

    @Test fun before_connecting_it_explains_that_the_scope_reads_the_whole_mailbox_and_waits_for_a_tap() {
        show()
        compose.onNodeWithText(GMAIL_SCOPE_EXPLANATION).assertIsDisplayed()
        compose.onNodeWithTag("gmail_state_disconnected").assertIsDisplayed()
        assertEquals(listOf("shown"), calls) // opening the screen starts nothing interactive
        compose.onNodeWithTag("gmail_connect").performScrollTo().performClick()
        assertEquals(listOf("shown", "connect"), calls)
    }

    @Test fun connected_shows_the_check_and_offers_disconnect() {
        state.value = gmailUiState(GmailState.Connected(200))
        show()
        compose.onNodeWithTag("gmail_state_connected").assertIsDisplayed()
        compose.onNodeWithText("Gmail answered a read-only check (HTTP 200). No messages were read.").assertIsDisplayed()
        compose.onNodeWithTag("gmail_disconnect").performScrollTo().performClick()
        assertEquals("disconnect", calls.last())
    }

    @Test fun a_denial_offers_connect_again() {
        state.value = gmailUiState(GmailState.Failed(GmailFailure.Denied))
        show()
        compose.onNodeWithText(GmailFailure.Denied.message).assertIsDisplayed()
        compose.onNodeWithTag("gmail_connect").performScrollTo().performClick()
        assertEquals("connect", calls.last())
    }

    @Test fun expiry_or_revocation_offers_connect_again() {
        state.value = gmailUiState(GmailState.Failed(GmailFailure.ReconsentNeeded))
        show()
        compose.onNodeWithText(GmailFailure.ReconsentNeeded.message).assertIsDisplayed()
        compose.onNodeWithTag("gmail_connect").assertIsDisplayed()
    }

    @Test fun a_network_failure_offers_retry() {
        state.value = gmailUiState(GmailState.Failed(GmailFailure.Network))
        show()
        compose.onNodeWithTag("gmail_retry").performScrollTo().performClick()
        assertEquals("retry", calls.last())
    }

    @Test fun an_unconfirmed_revoke_says_so() {
        state.value = gmailUiState(GmailState.Disconnected(revokeConfirmed = false))
        show()
        compose.onNodeWithTag("gmail_note").assertIsDisplayed()
    }
}
