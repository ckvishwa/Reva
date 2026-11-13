package app.reva.connectors.gmail

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** CON-1: the Gmail connection state machine against scripted Google and Gmail answers. */
class GmailConnectorTest {
    private class FakeAuthorizer(vararg steps: AuthStep) : GmailAuthorizer {
        val queue = ArrayDeque(steps.toList())
        var consentStep: AuthStep = granted("consented")
        val cleared = mutableListOf<String>()
        var revokeResult = true
        var revokeCalls = 0
        var authorizeCalls = 0
        override suspend fun authorize(): AuthStep { authorizeCalls++; return queue.removeFirst() }
        override suspend fun fromConsentResult(data: Any?): AuthStep = consentStep
        override suspend fun clearToken(accessToken: String) { cleared += accessToken }
        override suspend fun revoke(): Boolean { revokeCalls++; return revokeResult }
    }

    private class FakeProbe(vararg results: ProbeResult) : GmailProbe {
        val queue = ArrayDeque(results.toList())
        val tokens = mutableListOf<String>()
        override suspend fun listOneMessage(accessToken: String): ProbeResult { tokens += accessToken; return queue.removeFirst() }
    }

    private class MemoryStore(override var connected: Boolean = false) : GmailConnectionStore

    companion object {
        fun granted(token: String, scopes: Set<String> = setOf(GMAIL_READONLY)) = AuthStep.Granted(token, scopes)
        val ok = ProbeResult.Http(200)
    }

    @Test fun granted_token_and_a_200_from_gmail_means_connected() = runTest {
        val probe = FakeProbe(ok)
        val store = MemoryStore()
        val c = GmailConnector(FakeAuthorizer(granted("t1")), probe, store)
        c.connect()
        assertEquals(GmailState.Connected(200), c.state.value)
        assertTrue(store.connected)
        assertEquals(listOf("t1"), probe.tokens)
    }

    @Test fun when_google_needs_the_user_the_screen_gets_the_resolution_and_nothing_is_read() = runTest {
        val resolution = Any()
        val probe = FakeProbe()
        val c = GmailConnector(FakeAuthorizer(AuthStep.NeedsUser(resolution)), probe, MemoryStore())
        c.connect()
        val state = c.state.value as GmailState.NeedsUser
        assertSame(resolution, state.resolution)
        assertTrue(probe.tokens.isEmpty())
    }

    @Test fun consent_granted_then_checked() = runTest {
        val auth = FakeAuthorizer(AuthStep.NeedsUser(Any())).apply { consentStep = granted("after-consent") }
        val probe = FakeProbe(ok)
        val c = GmailConnector(auth, probe, MemoryStore())
        c.connect()
        c.onConsentResult(ok = true, data = null)
        assertEquals(GmailState.Connected(200), c.state.value)
        assertEquals(listOf("after-consent"), probe.tokens)
    }

    @Test fun consent_denied_or_backed_out_reads_nothing_and_offers_connect_again() = runTest {
        val probe = FakeProbe()
        val store = MemoryStore(connected = true)
        val c = GmailConnector(FakeAuthorizer(AuthStep.NeedsUser(Any())), probe, store)
        c.connect()
        c.onConsentResult(ok = false, data = null)
        assertEquals(GmailState.Failed(GmailFailure.Denied), c.state.value)
        assertEquals(GmailRemedy.Connect, GmailFailure.Denied.remedy)
        assertFalse(store.connected)
        assertTrue(probe.tokens.isEmpty())
    }

    @Test fun consent_result_that_google_reports_as_cancelled_is_a_denial() = runTest {
        val auth = FakeAuthorizer().apply { consentStep = AuthStep.Failed(GmailFailure.Denied) }
        val c = GmailConnector(auth, FakeProbe(), MemoryStore())
        c.onConsentResult(ok = true, data = null)
        assertEquals(GmailState.Failed(GmailFailure.Denied), c.state.value)
    }

    @Test fun a_grant_without_gmail_readonly_is_refused_and_not_used() = runTest {
        val probe = FakeProbe()
        val c = GmailConnector(FakeAuthorizer(granted("t", scopes = setOf("openid"))), probe, MemoryStore())
        c.connect()
        assertEquals(GmailState.Failed(GmailFailure.ScopeNotGranted), c.state.value)
        assertTrue(probe.tokens.isEmpty())
    }

    @Test fun an_expired_token_is_cleared_and_replaced_once_silently() = runTest {
        val auth = FakeAuthorizer(granted("old"), granted("fresh"))
        val probe = FakeProbe(ProbeResult.Http(401), ok)
        val c = GmailConnector(auth, probe, MemoryStore())
        c.connect()
        assertEquals(GmailState.Connected(200), c.state.value)
        assertEquals(listOf("old"), auth.cleared)
        assertEquals(listOf("old", "fresh"), probe.tokens)
    }

    @Test fun a_second_401_stops_instead_of_looping() = runTest {
        val auth = FakeAuthorizer(granted("a"), granted("b"))
        val store = MemoryStore(connected = true)
        val c = GmailConnector(auth, FakeProbe(ProbeResult.Http(401), ProbeResult.Http(401)), store)
        c.connect()
        assertEquals(GmailState.Failed(GmailFailure.Unauthorized), c.state.value)
        assertEquals(listOf("a", "b"), auth.cleared)
        assertEquals(2, auth.authorizeCalls)
        assertFalse(store.connected)
    }

    @Test fun expiry_during_an_interactive_connect_can_ask_the_user_again() = runTest {
        val auth = FakeAuthorizer(granted("old"), AuthStep.NeedsUser(Any()))
        val c = GmailConnector(auth, FakeProbe(ProbeResult.Http(401)), MemoryStore())
        c.connect()
        assertTrue(c.state.value is GmailState.NeedsUser)
    }

    @Test fun access_revoked_outside_reva_is_found_by_a_silent_check_without_showing_googles_screens() = runTest {
        val store = MemoryStore(connected = true)
        val c = GmailConnector(FakeAuthorizer(AuthStep.NeedsUser(Any())), FakeProbe(), store)
        c.recheck()
        assertEquals(GmailState.Failed(GmailFailure.ReconsentNeeded), c.state.value)
        assertEquals(GmailRemedy.Connect, GmailFailure.ReconsentNeeded.remedy)
        assertFalse(store.connected)
    }

    @Test fun revoked_token_rejected_by_gmail_on_a_silent_check_needs_reconsent() = runTest {
        val auth = FakeAuthorizer(granted("stale"), AuthStep.NeedsUser(Any()))
        val c = GmailConnector(auth, FakeProbe(ProbeResult.Http(401)), MemoryStore(connected = true))
        c.recheck()
        assertEquals(GmailState.Failed(GmailFailure.ReconsentNeeded), c.state.value)
    }

    @Test fun transient_failures_keep_the_connection_and_offer_retry() = runTest {
        val cases = mapOf(
            ProbeResult.NetworkError to GmailFailure.Network,
            ProbeResult.Http(403) to GmailFailure.Forbidden,
            ProbeResult.Http(429) to GmailFailure.RateLimited,
            ProbeResult.Http(503) to GmailFailure.ServerError,
            ProbeResult.Http(418) to GmailFailure.Unexpected,
        )
        for ((result, failure) in cases) {
            val store = MemoryStore(connected = true)
            val c = GmailConnector(FakeAuthorizer(granted("t")), FakeProbe(result), store)
            c.connect()
            assertEquals(GmailState.Failed(failure), c.state.value)
            assertEquals(GmailRemedy.Retry, failure.remedy)
            assertTrue("$failure keeps the flag", store.connected)
        }
    }

    @Test fun retry_after_a_network_error_succeeds() = runTest {
        val c = GmailConnector(FakeAuthorizer(granted("t"), granted("t")), FakeProbe(ProbeResult.NetworkError, ok), MemoryStore())
        c.connect()
        assertEquals(GmailState.Failed(GmailFailure.Network), c.state.value)
        c.connect()
        assertEquals(GmailState.Connected(200), c.state.value)
    }

    @Test fun google_side_failures_are_passed_through() = runTest {
        val c = GmailConnector(FakeAuthorizer(AuthStep.Failed(GmailFailure.PlayServicesUnavailable)), FakeProbe(), MemoryStore())
        c.connect()
        assertEquals(GmailState.Failed(GmailFailure.PlayServicesUnavailable), c.state.value)
        assertEquals(GmailRemedy.None, GmailFailure.PlayServicesUnavailable.remedy)
    }

    @Test fun disconnect_revokes_at_google_and_forgets_the_connection() = runTest {
        val auth = FakeAuthorizer(granted("t"))
        val store = MemoryStore()
        val c = GmailConnector(auth, FakeProbe(ok), store)
        c.connect()
        c.disconnect()
        assertEquals(1, auth.revokeCalls)
        assertFalse(store.connected)
        assertEquals(GmailState.Disconnected(revokeConfirmed = true), c.state.value)
    }

    @Test fun disconnect_is_local_even_when_google_cannot_confirm_the_revoke() = runTest {
        val auth = FakeAuthorizer().apply { revokeResult = false }
        val store = MemoryStore(connected = true)
        val c = GmailConnector(auth, FakeProbe(), store)
        c.disconnect()
        assertFalse(store.connected)
        assertEquals(GmailState.Disconnected(revokeConfirmed = false), c.state.value)
    }

    @Test fun the_token_never_appears_in_a_state_or_a_step_description() = runTest {
        val secret = "ya29.SECRET-TOKEN"
        assertFalse(granted(secret).toString().contains(secret))
        val c = GmailConnector(FakeAuthorizer(granted(secret)), FakeProbe(ok), MemoryStore())
        c.connect()
        assertFalse(c.state.value.toString().contains(secret))
    }

    @Test fun the_starting_state_is_disconnected_and_remembers_an_earlier_connection() {
        val c = GmailConnector(FakeAuthorizer(), FakeProbe(), MemoryStore(connected = true))
        assertEquals(GmailState.Disconnected(), c.state.value)
        assertTrue(c.wasConnected)
    }
}
