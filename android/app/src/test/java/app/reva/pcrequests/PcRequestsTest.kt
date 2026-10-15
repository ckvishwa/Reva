package app.reva.pcrequests

import app.reva.language.Outcomes
import app.reva.language.PolicyReplies
import app.reva.policy.loadRegistry
import app.reva.sync.GatewayProtocol
import app.reva.sync.GatewayTarget
import app.reva.sync.GatewayTransport
import app.reva.sync.HttpReply
import app.reva.sync.PairedPc
import java.io.File
import java.io.IOException
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlin.coroutines.EmptyCoroutineContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import uniffi.reva_kernel.DeviceSigner

private val PC = PairedPc("192.168.1.20", 47821, "ab".repeat(32), "device-1", ByteArray(65), "pc-kernel")

private fun reply(status: String, id: String = "req", reason: String = "OK", speak: String? = null, prompt: String? = null, capability: String = "windows.app.open") =
    PcReply(id, capability, if (capability.endsWith("close")) "T2" else "T1", status, reason, speak, prompt, null)

private class FakeGateway : PcGateway {
    val proposals = mutableListOf<Triple<String, String, Long>>() // request id, capability, issued_at
    val args = mutableListOf<Map<String, Any?>>()
    var proposeStep: (Int) -> PcReply = { reply("granted") }
    var statusStep: (Int) -> PcReply = { reply("verified", speak = "Opened Calculator.") }
    var polls = 0

    override fun propose(pc: PairedPc, requestId: String, capability: String, args: Map<String, Any?>, issuedAt: Long): PcReply {
        proposals += Triple(requestId, capability, issuedAt)
        this.args += args
        return proposeStep(proposals.size).copy(requestId = requestId)
    }

    override fun status(pc: PairedPc, requestId: String): PcReply {
        polls += 1
        return statusStep(polls).copy(requestId = requestId)
    }
}

private fun unreachable(): Nothing = throw PcException(PcFailure.Unreachable, "Could not reach your PC.")

@OptIn(ExperimentalCoroutinesApi::class)
private class Rig(scope: TestScope, var paired: PairedPc? = PC) {
    val job = Job()
    val gateway = FakeGateway()
    val texts = mutableListOf<String>()
    val tracker = PcRequestTracker(
        pc = { paired },
        gateway = gateway,
        scope = CoroutineScope(job + StandardTestDispatcher(scope.testScheduler)),
        clockSeconds = { scope.testScheduler.currentTime / 1000 },
        io = EmptyCoroutineContext,
        pause = { kotlinx.coroutines.delay(it) },
        newId = { "request-id-${gateway.proposals.size + 1}-abcdefghij" },
        onText = { texts += it },
    )
    val phase get() = tracker.ui.value
    fun finished() = phase as PcPhase.Finished
}

class PcPhrasesTest {
    @Test fun the_app_words_equal_the_python_ladder() {
        val cases = JSONObject(File(System.getProperty("reva.fixtures"), "rules-cases.json").readText()).getJSONArray("app_resolution")
        assertTrue(cases.length() > 20)
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val want = if (case.isNull("key")) null else case.getString("key")
            assertEquals("'${case.getString("phrase")}'", want, PcPhrases.resolveApp(case.getString("phrase")))
        }
    }

    @Test fun a_sentence_that_names_the_pc_becomes_a_request() {
        assertEquals(PcIntent("windows.app.open", "Calculator", "calculator"), PcPhrases.parse("Open Calculator on my PC"))
        assertEquals(PcIntent("windows.app.close", "spotify", "spotify"), PcPhrases.parse("close spotify on my laptop."))
        assertEquals(PcIntent("windows.app.open", "vs code", "vscode"), PcPhrases.parse("please launch vs code on the computer"))
        assertEquals(PcIntent("windows.app.close", "the browser", "chrome"), PcPhrases.parse("quit the browser on my windows pc"))
    }

    @Test fun an_unknown_app_is_named_but_has_no_key_so_nothing_is_sent() {
        assertNull(PcPhrases.parse("open obsidian on my pc")!!.appKey)
        assertNull(PcPhrases.parse("open calculator and format the disk on my pc")!!.appKey)
        assertNull(PcPhrases.parse("open spotfy on my pc")!!.appKey)
    }

    @Test fun sentences_that_do_not_name_the_pc_are_not_requests_for_it() {
        for (text in listOf("open calculator", "close spotify", "what is on my pc", "open on my pc", "remember my pc password", "delete files on my pc", "")) {
            assertNull(text, PcPhrases.parse(text))
        }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class PcRequestTrackerTest {
    @Test fun open_goes_granted_then_running_and_only_the_pcs_verified_report_says_done() = runTest {
        val rig = Rig(this)
        rig.gateway.statusStep = { n -> if (n < 3) reply("observed") else reply("verified", speak = "Opened Calculator.") }

        assertEquals(PcStart.Started, rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator"))
        runCurrent()
        assertTrue("granted is working on it, not done", rig.phase is PcPhase.Running)
        advanceUntilIdle()

        val done = rig.finished()
        assertEquals(PcOutcome.Verified, done.outcome)
        assertEquals("Opened Calculator.", done.text)
        assertEquals(listOf("Opened Calculator."), rig.texts)
        assertEquals(listOf(mapOf<String, Any?>("app_key" to "calculator")), rig.gateway.args)
        rig.job.cancel()
    }

    @Test fun close_waits_for_the_click_on_the_pc_and_says_so_once() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("awaiting_approval", prompt = "Close Spotify? Approve it on screen.", capability = "windows.app.close") }
        rig.gateway.statusStep = { n -> if (n < 3) reply("awaiting_approval", prompt = "Close Spotify? Approve it on screen.", capability = "windows.app.close") else reply("verified", speak = "Closed Spotify.", capability = "windows.app.close") }

        rig.tracker.start("windows.app.close", mapOf("app_key" to "spotify"), "Close Spotify")
        runCurrent()
        assertEquals(PcPhase.WaitingForApproval("Close Spotify", "Close Spotify? Approve it on screen."), rig.phase)
        advanceTimeBy(PcRequestTracker.POLL_MILLIS * 2)
        runCurrent()
        assertEquals(1, rig.texts.count { it.startsWith("Waiting for you on your PC") })
        advanceUntilIdle()

        assertEquals("Closed Spotify.", rig.finished().text)
        rig.job.cancel()
    }

    @Test fun every_non_success_ending_says_so_and_none_says_done() = runTest {
        val endings = mapOf(
            "failed" to (PcOutcome.Failed to PcRequestTracker.FAILED),
            "unknown" to (PcOutcome.Unknown to PcRequestTracker.UNKNOWN),
            "denied" to (PcOutcome.Denied to PcRequestTracker.DENIED),
            "expired" to (PcOutcome.Expired to PcRequestTracker.EXPIRED),
            "something_new" to (PcOutcome.Unknown to PcRequestTracker.UNKNOWN),
        )
        for ((status, want) in endings) {
            val rig = Rig(this)
            rig.gateway.proposeStep = { reply(status, speak = "Opened Calculator.") }

            rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
            advanceUntilIdle()

            assertEquals(status, want.first, rig.finished().outcome)
            assertEquals(status, want.second, rig.finished().text)
            rig.job.cancel()
        }
    }

    @Test fun a_refusal_says_why_in_words_a_person_can_use() = runTest {
        for ((reason, text) in mapOf(
            "INVALID_ARGS" to "Your PC doesn't know that app.",
            "STATE_MISMATCH" to "That clashed with an earlier request. Try again.",
            "UNKNOWN_CAPABILITY" to "Your PC refused that.",
        )) {
            val rig = Rig(this)
            rig.gateway.proposeStep = { reply("refused", reason = reason) }

            rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
            advanceUntilIdle()

            assertEquals(PcOutcome.Refused, rig.finished().outcome)
            assertEquals(text, rig.finished().text)
            rig.job.cancel()
        }
    }

    @Test fun a_verified_report_with_no_words_is_not_trusted_as_success() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("verified", speak = null) }

        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        advanceUntilIdle()

        assertEquals(PcOutcome.Unknown, rig.finished().outcome)
        rig.job.cancel()
    }

    // ---------------------------------------------------------------- disconnected, retried, duplicated

    @Test fun a_dropped_connection_retries_the_same_request_with_the_same_id_and_time() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { n -> if (n < 3) unreachable() else reply("granted") }
        rig.gateway.statusStep = { reply("verified", speak = "Opened Calculator.") }

        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        runCurrent()
        assertTrue(rig.phase is PcPhase.Retrying)
        advanceUntilIdle()

        assertEquals(3, rig.gateway.proposals.size)
        assertEquals("one id for the whole life of the request", 1, rig.gateway.proposals.map { it.first }.toSet().size)
        assertEquals("a retry must not stretch the PC's window", 1, rig.gateway.proposals.map { it.third }.toSet().size)
        assertEquals(PcOutcome.Verified, rig.finished().outcome)
        rig.job.cancel()
    }

    @Test fun a_pc_that_never_answers_ends_unknown_after_the_window_never_as_success() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { unreachable() }

        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        advanceUntilIdle()

        assertEquals(PcOutcome.Unreachable, rig.finished().outcome)
        assertEquals(PcRequestTracker.UNREACHABLE_UNKNOWN, rig.finished().text)
        assertTrue("it keeps trying inside the window", rig.gateway.proposals.size > 5)
        assertTrue("and stops before the PC's 120 s", currentTime / 1000 <= 125)
        assertEquals(1, rig.gateway.proposals.map { it.first }.toSet().size)
        rig.job.cancel()
    }

    @Test fun losing_touch_while_waiting_ends_unknown() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("granted") }
        rig.gateway.statusStep = { unreachable() }

        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        advanceUntilIdle()

        assertEquals(PcOutcome.Unknown, rig.finished().outcome)
        assertEquals(PcRequestTracker.LOST_TOUCH, rig.finished().text)
        rig.job.cancel()
    }

    @Test fun a_request_nobody_approves_is_given_up_on_with_a_honest_sentence() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("awaiting_approval", prompt = "p", capability = "windows.app.close") }
        rig.gateway.statusStep = { reply("awaiting_approval", prompt = "p", capability = "windows.app.close") }

        rig.tracker.start("windows.app.close", mapOf("app_key" to "spotify"), "Close Spotify")
        advanceUntilIdle()

        assertEquals(PcOutcome.Unknown, rig.finished().outcome)
        assertEquals(PcRequestTracker.GAVE_UP, rig.finished().text)
        rig.job.cancel()
    }

    @Test fun only_one_request_at_a_time_so_one_tap_cannot_ask_twice() = runTest {
        val rig = Rig(this)
        rig.gateway.statusStep = { reply("granted") }

        val first = rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        runCurrent()
        val second = rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")

        assertEquals(PcStart.Started, first)
        assertEquals(PcStart.Refused(PcRequestTracker.STILL_WAITING), second)
        assertEquals(1, rig.gateway.proposals.size)
        rig.tracker.cancel()
        advanceUntilIdle()
        rig.gateway.statusStep = { reply("verified", speak = "Opened Calculator.") }
        assertEquals(PcStart.Started, rig.tracker.start("windows.app.open", mapOf("app_key" to "notepad"), "Open Notepad"))
        assertNotEquals("a new request gets a new id", rig.gateway.proposals[0].first, rig.gateway.proposals.getOrNull(1)?.first ?: "")
        advanceUntilIdle()
        rig.job.cancel()
    }

    @Test fun not_paired_means_nothing_is_sent() = runTest {
        val rig = Rig(this, paired = null)

        val start = rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        advanceUntilIdle()

        assertEquals(PcStart.Refused(PcRequestTracker.NOT_PAIRED), start)
        assertTrue(rig.gateway.proposals.isEmpty())
        assertEquals(PcPhase.Idle, rig.phase)
        rig.job.cancel()
    }

    @Test fun stop_waiting_is_honest_the_pc_may_still_act_and_late_answers_are_ignored() = runTest {
        val rig = Rig(this)
        rig.gateway.statusStep = { reply("granted") }
        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        runCurrent()

        rig.tracker.cancel()
        rig.gateway.statusStep = { reply("verified", speak = "Opened Calculator.") }
        advanceUntilIdle()

        assertEquals(PcOutcome.Cancelled, rig.finished().outcome)
        assertEquals(PcRequestTracker.CANCELLED, rig.finished().text)
        assertTrue(rig.texts.none { it.contains("Opened") })
        rig.job.cancel()
    }

    // ---------------------------------------------------------------- what the PC refuses

    @Test fun the_pcs_refusals_become_plain_sentences_and_none_of_them_retry() = runTest {
        val cases = mapOf(
            PcFailure.OutOfScope to PcOutcome.OutOfScope,
            PcFailure.NotAllowed to PcOutcome.NotAllowed,
            PcFailure.Unauthorized to PcOutcome.Revoked,
            PcFailure.Expired to PcOutcome.Expired,
            PcFailure.TooMany to PcOutcome.Refused,
            PcFailure.Unavailable to PcOutcome.Refused,
            PcFailure.BadAnswer to PcOutcome.Refused,
        )
        for ((failure, outcome) in cases) {
            val rig = Rig(this)
            rig.gateway.proposeStep = { throw PcException(failure, "words for $failure") }

            rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
            advanceUntilIdle()

            assertEquals(failure.name, outcome, rig.finished().outcome)
            assertEquals("words for $failure", rig.finished().text)
            assertEquals("a refusal is not retried", 1, rig.gateway.proposals.size)
            rig.job.cancel()
        }
    }

    @Test fun an_unknown_request_while_following_ends_unknown_not_success() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("granted") }
        rig.gateway.statusStep = { throw PcException(PcFailure.UnknownRequest, "Your PC does not know that request.") }

        rig.tracker.start("windows.app.open", mapOf("app_key" to "calculator"), "Open Calculator")
        advanceUntilIdle()

        assertEquals(PcOutcome.Unknown, rig.finished().outcome)
        rig.job.cancel()
    }

    // ---------------------------------------------------------------- through the reply path

    private fun replies(rig: Rig) = PolicyReplies(loadRegistry(), clock = { java.time.Instant.parse("2026-10-15T12:00:00Z") }, pc = rig.tracker)

    @Test fun a_sentence_naming_the_pc_asks_it_and_says_only_that_it_asked() = runTest {
        val rig = Rig(this)
        rig.gateway.statusStep = { reply("granted") }

        val open = replies(rig).reply("open calculator on my pc").text
        runCurrent()

        assertEquals("Asking your PC to open Calculator.", open)
        assertEquals(listOf("windows.app.open"), rig.gateway.proposals.map { it.second })
        assertEquals(mapOf<String, Any?>("app_key" to "calculator"), rig.gateway.args.single())
        rig.tracker.cancel()
        advanceUntilIdle()

        val close = replies(rig).reply("close Spotify on my laptop").text
        assertEquals("Asking your PC to close Spotify. Approve it on the PC.", close)
        rig.tracker.close()
        rig.job.cancel()
    }

    @Test fun the_phone_runs_authorize_first_and_a_close_is_allowed_to_go_only_to_wait_for_the_pc() = runTest {
        val rig = Rig(this)
        rig.gateway.proposeStep = { reply("awaiting_approval", prompt = "Close Spotify? Approve it on screen.", capability = "windows.app.close") }
        rig.gateway.statusStep = { reply("awaiting_approval", prompt = "x", capability = "windows.app.close") }

        replies(rig).reply("close spotify on my pc")
        runCurrent()

        assertTrue("the phone did not approve anything", rig.phase is PcPhase.WaitingForApproval)
        rig.tracker.close()
        rig.job.cancel()
    }

    @Test fun an_unknown_or_hostile_app_phrase_is_never_sent() = runTest {
        val rig = Rig(this)

        val unknown = replies(rig).reply("open obsidian on my pc").text
        val hostile = replies(rig).reply("open calculator; del /s on my pc").text
        runCurrent()

        assertEquals("I don't know an app called obsidian on your PC.", unknown)
        assertTrue(hostile.startsWith("I don't know an app called"))
        assertTrue(rig.gateway.proposals.isEmpty())
        rig.job.cancel()
    }

    @Test fun without_a_tracker_the_phone_says_it_cannot_ask() = runTest {
        val noPc = PolicyReplies(loadRegistry())

        assertEquals(PolicyReplies.NO_PC_REQUESTS, noPc.reply("open calculator on my pc").text)
    }

    @Test fun not_paired_is_said_in_words_and_nothing_goes_out() = runTest {
        val rig = Rig(this, paired = null)

        val text = replies(rig).reply("open calculator on my pc").text
        advanceUntilIdle()

        assertEquals(PcRequestTracker.NOT_PAIRED, text)
        assertTrue(rig.gateway.proposals.isEmpty())
        rig.job.cancel()
    }

    @Test fun no_sentence_the_phone_says_while_working_claims_it_is_done() {
        val said = listOf(
            "Asking your PC to open Calculator.",
            "Asking your PC to close Spotify. Approve it on the PC.",
            PcRequestTracker.STILL_WAITING, PcRequestTracker.UNREACHABLE_UNKNOWN, PcRequestTracker.LOST_TOUCH,
            PcRequestTracker.GAVE_UP, PcRequestTracker.CANCELLED, PcRequestTracker.UNKNOWN, PcRequestTracker.FAILED,
        )
        for (text in said) {
            for (word in Outcomes.SUCCESS_WORDS) {
                assertFalse("'$text' contains '$word'", Regex("\\b$word\\b").containsMatchIn(text.lowercase()))
            }
        }
    }
}

// ---------------------------------------------------------------------------- the signed gateway client

class SignedPcGatewayTest {
    private val phoneKey = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    private val pcKey = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    private val pc = PairedPc("192.168.1.20", 47821, "ab".repeat(32), "device-1", pcKey.public.encoded, "pc-kernel")

    private val signer = object : DeviceSigner {
        override fun publicKey(): ByteArray = phoneKey.public.encoded
        override fun sign(message: ByteArray): ByteArray =
            Signature.getInstance("SHA256withECDSA").run {
                initSign(phoneKey.private)
                update(message)
                sign()
            }
    }

    private fun pcSign(message: ByteArray): ByteArray = Signature.getInstance("SHA256withECDSA").run {
        initSign(pcKey.private)
        update(message)
        sign()
    }

    private class Capture : GatewayTransport {
        var path = ""
        var headers: Map<String, String> = emptyMap()
        var body = ByteArray(0)
        var respond: (String, ByteArray) -> HttpReply = { _, _ -> throw IOException("no route") }

        override fun post(target: GatewayTarget, path: String, headers: Map<String, String>, body: ByteArray): HttpReply {
            this.path = path
            this.headers = headers
            this.body = body
            return respond(headers.getValue(GatewayProtocol.HEADER_NONCE), body)
        }
    }

    private fun answer(nonce: String, status: Int, json: String, sign: Boolean = true, key: ((ByteArray) -> ByteArray) = ::pcSign): HttpReply {
        val bytes = json.toByteArray()
        val headers = if (sign) mapOf(GatewayProtocol.HEADER_RESPONSE_SIGNATURE.lowercase() to GatewayProtocol.b64u(key(GatewayProtocol.responseMessage(nonce, status, bytes)))) else emptyMap()
        return HttpReply(status, headers, bytes)
    }

    private val okJson = """{"request_id":"abcdefghijklmnop","capability":"windows.app.open","tier":"T1","status":"granted","reason":"OK","speak":null,"prompt":null,"deadline":null,"evidence_kind":"process_started"}"""

    @Test fun the_request_is_signed_the_way_the_gateway_checks_it() {
        val transport = Capture().apply { respond = { nonce, _ -> answer(nonce, 200, okJson) } }
        val client = SignedPcGateway(signer, transport, clockSeconds = { 1_800_000_000 })

        val result = client.propose(pc, "abcdefghijklmnop", "windows.app.open", mapOf("app_key" to "calculator"), 1_800_000_000)

        assertEquals("/actions/propose", transport.path)
        val body = JSONObject(String(transport.body))
        assertEquals(setOf("request_id", "capability", "args", "issued_at"), body.keys().asSequence().toSet())
        assertEquals("calculator", body.getJSONObject("args").getString("app_key"))
        val message = GatewayProtocol.requestMessage(
            "POST", "/actions/propose", 1_800_000_000, transport.headers.getValue(GatewayProtocol.HEADER_NONCE), transport.body, pc.tlsSha256,
        )
        val signature = GatewayProtocol.b64uDecode(transport.headers.getValue(GatewayProtocol.HEADER_SIGNATURE))
        assertTrue("the PC can verify this request", GatewayProtocol.verify(phoneKey.public.encoded, message, signature))
        assertEquals("device-1", transport.headers[GatewayProtocol.HEADER_DEVICE])
        assertEquals("granted", result.status)
    }

    @Test fun a_status_request_names_only_the_request_id() {
        val transport = Capture().apply { respond = { nonce, _ -> answer(nonce, 200, okJson) } }

        SignedPcGateway(signer, transport).status(pc, "abcdefghijklmnop")

        assertEquals("/actions/status", transport.path)
        assertEquals(setOf("request_id"), JSONObject(String(transport.body)).keys().asSequence().toSet())
    }

    @Test fun an_answer_not_signed_by_the_paired_pc_is_never_believed() {
        val other = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        for (reply in listOf<(String) -> HttpReply>(
            { nonce -> answer(nonce, 200, okJson, sign = false) },
            { nonce -> answer(nonce, 200, okJson, key = { m -> Signature.getInstance("SHA256withECDSA").run { initSign(other.private); update(m); sign() } }) },
            { nonce -> HttpReply(200, mapOf(GatewayProtocol.HEADER_RESPONSE_SIGNATURE.lowercase() to "not base64!!"), okJson.toByteArray()) },
        )) {
            val transport = Capture().apply { respond = { nonce, _ -> reply(nonce) } }
            try {
                SignedPcGateway(signer, transport).status(pc, "abcdefghijklmnop")
                throw AssertionError("a forged answer must be refused")
            } catch (e: PcException) {
                assertEquals(PcFailure.BadAnswer, e.failure)
            }
        }
    }

    @Test fun an_answer_for_a_different_request_cannot_be_replayed_to_this_one() {
        val transport = Capture().apply { respond = { _, _ -> answer("some-other-nonce-123456", 200, okJson) } }

        try {
            SignedPcGateway(signer, transport).status(pc, "abcdefghijklmnop")
            throw AssertionError("a signature for another nonce must not count")
        } catch (e: PcException) {
            assertEquals(PcFailure.BadAnswer, e.failure)
        }
    }

    @Test fun the_gateways_refusals_map_to_plain_failures() {
        val cases = mapOf(
            401 to ("""{"error":"unauthorized"}""" to PcFailure.Unauthorized),
            403 to ("""{"error":"out_of_scope"}""" to PcFailure.OutOfScope),
            4031 to ("""{"error":"capability_not_allowed"}""" to PcFailure.NotAllowed),
            410 to ("""{"error":"request_expired"}""" to PcFailure.Expired),
            404 to ("""{"error":"unknown_request"}""" to PcFailure.UnknownRequest),
            429 to ("""{"error":"too_many_actions"}""" to PcFailure.TooMany),
            503 to ("""{"error":"actions_unavailable"}""" to PcFailure.Unavailable),
            500 to ("""{"error":"internal_error"}""" to PcFailure.Other),
        )
        for ((code, want) in cases) {
            val status = if (code == 4031) 403 else code
            val transport = Capture().apply { respond = { _, _ -> HttpReply(status, emptyMap(), want.first.toByteArray()) } }
            try {
                SignedPcGateway(signer, transport).status(pc, "abcdefghijklmnop")
                throw AssertionError("$code must fail")
            } catch (e: PcException) {
                assertEquals("$code", want.second, e.failure)
            }
        }
    }

    @Test fun a_network_error_is_unreachable_and_a_missing_key_is_a_plain_failure() {
        val down = Capture()
        try {
            SignedPcGateway(signer, down).status(pc, "abcdefghijklmnop")
            throw AssertionError("must fail")
        } catch (e: PcException) {
            assertEquals(PcFailure.Unreachable, e.failure)
        }
        val broken = object : DeviceSigner {
            override fun publicKey(): ByteArray = ByteArray(0)
            override fun sign(message: ByteArray): ByteArray = throw uniffi.reva_kernel.SignerException.Unavailable("no key")
        }
        try {
            SignedPcGateway(broken, down).status(pc, "abcdefghijklmnop")
            throw AssertionError("must fail")
        } catch (e: PcException) {
            assertEquals(PcFailure.Other, e.failure)
        }
    }

    @Test fun an_answer_missing_its_status_is_not_understood_and_never_a_success() {
        val transport = Capture().apply { respond = { nonce, _ -> answer(nonce, 200, """{"request_id":"abcdefghijklmnop"}""") } }

        try {
            SignedPcGateway(signer, transport).status(pc, "abcdefghijklmnop")
            throw AssertionError("must fail")
        } catch (e: PcException) {
            assertEquals(PcFailure.BadAnswer, e.failure)
        }
    }
}
