package app.reva.brain

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.delay
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostedPlannerTest {
    private class Store(var saved: ModeConfig) : ModeSettings {
        override fun load() = saved
        override fun save(config: ModeConfig) { saved = config }
    }
    private class Capture : HostedTransport {
        var calls = 0
        var key = ""
        var body = ""
        var response = HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"text","text":"Jupiter is a planet."}]}""")
        override suspend fun send(key: String, body: String): HostedHttpResponse {
            calls++
            this.key = key
            this.body = body
            return response
        }
    }

    private fun ready(config: ModeConfig, capture: Capture): Pair<ModeController, HostedPlanner> {
        val modes = ModeController(Store(config))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        return modes to HostedPlanner(modes, key = { "test-api-key" }, transport = capture)
    }

    @Test fun hosted_processing_is_disabled_by_default_and_sends_nothing() = runBlocking {
        val capture = Capture()
        val (_, planner) = ready(ModeConfig(preferred = RunMode.Standalone), capture)

        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        assertEquals(0, capture.calls)
    }

    @Test fun finance_and_memory_text_cannot_leave_without_their_domain_consent() = runBlocking {
        val capture = Capture()
        val (_, planner) = ready(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true), capture)

        assertTrue(planner.answer("I spent $50 at the bank. Why?") is BrainResult.Unknown)
        assertTrue(planner.answer("My saved memory says my sister's name is Alex. Explain it.") is BrainResult.Unknown)
        assertTrue(planner.answer("What is my checking balance?") is BrainResult.Unknown)
        assertTrue(planner.answer("Explain my private note about Alex") is BrainResult.Unknown)
        assertTrue(planner.answer("What does alice@example.com mean?") is BrainResult.Unknown)
        assertEquals(0, capture.calls)
    }

    @Test fun a_generic_question_sends_only_the_question_and_a_fixed_instruction() = runBlocking {
        val capture = Capture()
        val (_, planner) = ready(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true), capture)

        val answer = planner.answer("What is Jupiter?")

        assertEquals(BrainResult.Answer("Jupiter is a planet.", "Anthropic"), answer)
        assertEquals(1, capture.calls)
        assertEquals("test-api-key", capture.key)
        val body = JSONObject(capture.body)
        assertEquals("What is Jupiter?", body.getJSONArray("messages").getJSONObject(0).getString("content"))
        assertFalse(body.has("tools"))
        assertFalse(capture.body.contains("Finance"))
        assertFalse(capture.body.contains("Memory"))
    }

    @Test fun disable_cloud_revokes_the_next_request_even_with_a_saved_key() = runBlocking {
        val capture = Capture()
        val (modes, planner) = ready(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true), capture)
        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Answer)
        modes.disableCloud()

        assertTrue(planner.answer("What is Saturn?") is BrainResult.Unknown)
        assertEquals(1, capture.calls)
    }

    @Test fun revocation_during_key_read_stops_before_network_send() = runBlocking {
        val capture = Capture()
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        val planner = HostedPlanner(modes, key = { modes.disableCloud(); "test-api-key" }, transport = capture)

        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        assertEquals(0, capture.calls)
    }

    @Test fun revoking_one_domain_during_key_read_stops_all_network_egress() = runBlocking {
        val capture = Capture()
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true,
            financeConsent = true, memoryConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        val planner = HostedPlanner(modes, key = {
            modes.configure(modes.config().copy(memoryConsent = false))
            "test-api-key"
        }, transport = capture)

        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        assertEquals(0, capture.calls)
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
    }

    @Test fun revoking_one_domain_while_waiting_discards_provider_text() = runBlocking {
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true,
            financeConsent = true, memoryConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        val planner = HostedPlanner(modes, key = { "test-api-key" }, transport = HostedTransport { _, _ ->
            modes.configure(modes.config().copy(financeConsent = false))
            HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"text","text":"Jupiter is a planet."}]}""")
        })

        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
    }

    @Test fun truncated_or_non_text_response_is_never_reported_as_an_answer() = runBlocking {
        val capture = Capture()
        val (_, planner) = ready(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true), capture)
        capture.response = HostedHttpResponse(200, """{"stop_reason":"max_tokens","content":[{"type":"text","text":"I opened the app"}]}""")
        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        capture.response = HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"tool_use"}]}""")
        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
    }

    @Test fun a_provider_claim_of_action_completion_is_not_accepted_as_verified_evidence() = runBlocking {
        val capture = Capture()
        val (_, planner) = ready(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true), capture)
        capture.response = HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"text","text":"I opened Calculator for you."}]}""")

        assertTrue(planner.answer("Tell me a fun fact") is BrainResult.Unknown)
        capture.response = HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"text","text":"Done, Calculator is open."}]}""")
        assertTrue(planner.answer("Tell me a fun fact") is BrainResult.Unknown)
    }

    @Test fun hosted_timeout_moves_to_offline_lite_without_sending_an_answer() = runBlocking {
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        val planner = HostedPlanner(modes, key = { "test-api-key" }, transport = HostedTransport { _, _ ->
            delay(100)
            HostedHttpResponse(200, """{"stop_reason":"end_turn","content":[{"type":"text","text":"late"}]}""")
        }, timeoutMillis = 10)

        assertTrue(planner.answer("What is Jupiter?") is BrainResult.Unknown)
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        assertTrue(modes.state.value.retryRequired)
    }
}
