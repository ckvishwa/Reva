package app.reva.pcrequests

import app.reva.sync.PairedPc
import java.security.SecureRandom
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class PcOutcome { Verified, Failed, Unknown, Denied, Expired, Refused, Unreachable, Revoked, NotAllowed, OutOfScope, Cancelled }

sealed interface PcPhase {
    data object Idle : PcPhase
    data class Sending(val label: String) : PcPhase

    /** The PC could not be reached; the same request (same id) is being sent again. */
    data class Retrying(val label: String, val attempt: Int) : PcPhase
    data class WaitingForApproval(val label: String, val prompt: String) : PcPhase

    /** The PC has the request and is doing it. This is not success. */
    data class Running(val label: String) : PcPhase
    data class Finished(val label: String, val outcome: PcOutcome, val text: String) : PcPhase
}

sealed interface PcStart {
    data object Started : PcStart
    data class Refused(val text: String) : PcStart
}

/**
 * Carries one phone-to-PC request from "asked" to what really happened, and says nothing it cannot back up.
 *
 *  - The request has one id for its whole life. A dropped connection means "I do not know whether it landed", so
 *    the same request is sent again with the same id; the PC treats that as one action, never two.
 *  - The time the request was made (`issued_at`) is fixed too, so retries cannot stretch the PC's 120 second
 *    window: after that the PC refuses to act late, and so does the phone (it stops retrying and says it does
 *    not know).
 *  - "Done" is said only when the PC reports `verified`, in the PC's own words. Granted, observed or running is
 *    "working on it". A request the phone could not confirm is "unknown", never a success.
 *  - The phone never approves anything: a sensitive request waits for a click on the PC.
 *  - Only one request at a time, so the same tap cannot ask twice.
 */
class PcRequestTracker(
    private val pc: () -> PairedPc?,
    private val gateway: PcGateway,
    private val scope: CoroutineScope,
    private val clockSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
    private val io: CoroutineContext = Dispatchers.IO,
    private val pause: suspend (Long) -> Unit = { delay(it) },
    private val newId: () -> String = ::randomId,
    private val onText: (String) -> Unit = {},
) {
    private val _ui = MutableStateFlow<PcPhase>(PcPhase.Idle)
    val ui: StateFlow<PcPhase> = _ui.asStateFlow()
    private var job: Job? = null

    val busy: Boolean get() = job?.isActive == true

    fun start(capability: String, args: Map<String, Any?>, label: String): PcStart {
        if (busy) return PcStart.Refused(STILL_WAITING)
        val paired = pc() ?: return PcStart.Refused(NOT_PAIRED)
        val id = newId()
        val issuedAt = clockSeconds()
        _ui.value = PcPhase.Sending(label)
        job = scope.launch { run(paired, id, capability, args, label, issuedAt) }
        return PcStart.Started
    }

    /** Stops waiting. The PC may already have the request and may still act on it. */
    fun cancel() {
        val active = job ?: return
        if (!active.isActive) return
        val label = (_ui.value as? PcPhase.Sending)?.label ?: labelOf(_ui.value) ?: "that"
        active.cancel()
        finish(label, PcOutcome.Cancelled, CANCELLED)
    }

    fun close() {
        job?.cancel()
        job = null
        _ui.value = PcPhase.Idle
    }

    fun clearFinished() {
        if (_ui.value is PcPhase.Finished) _ui.value = PcPhase.Idle
    }

    // ------------------------------------------------------------------ the request's life

    private suspend fun run(paired: PairedPc, id: String, capability: String, args: Map<String, Any?>, label: String, issuedAt: Long) {
        val first = send(paired, id, capability, args, label, issuedAt) ?: return
        follow(paired, id, label, first)
    }

    /** Sends the request until the PC answers, a refusal comes back, or the PC's window for it has passed. */
    private suspend fun send(paired: PairedPc, id: String, capability: String, args: Map<String, Any?>, label: String, issuedAt: Long): PcReply? {
        var attempt = 0
        while (true) {
            try {
                return withContext(io) { gateway.propose(paired, id, capability, args, issuedAt) }
            } catch (e: PcException) {
                if (e.failure != PcFailure.Unreachable) {
                    finish(label, outcomeFor(e.failure), e.message)
                    return null
                }
            }
            attempt += 1
            if (clockSeconds() - issuedAt >= SEND_WINDOW_SECONDS) {
                finish(label, PcOutcome.Unreachable, UNREACHABLE_UNKNOWN)
                return null
            }
            _ui.value = PcPhase.Retrying(label, attempt)
            pause(minOf(RETRY_BASE_MILLIS * attempt, RETRY_MAX_MILLIS))
        }
    }

    /** Polls the PC's own record until it says something final. */
    private suspend fun follow(paired: PairedPc, id: String, label: String, firstReply: PcReply) {
        var reply = firstReply
        val startedAt = clockSeconds()
        var shownApproval = false
        while (true) {
            when (reply.status) {
                "awaiting_approval" -> {
                    val prompt = reply.prompt ?: "Approve it on your PC."
                    _ui.value = PcPhase.WaitingForApproval(label, prompt)
                    if (!shownApproval) {
                        shownApproval = true
                        onText("Waiting for you on your PC: $prompt")
                    }
                }
                "granted", "attempted", "observed" -> _ui.value = PcPhase.Running(label)
                else -> {
                    finishFrom(label, reply)
                    return
                }
            }
            if (clockSeconds() - startedAt >= FOLLOW_SECONDS) {
                finish(label, PcOutcome.Unknown, GAVE_UP)
                return
            }
            pause(POLL_MILLIS)
            reply = pollOnce(paired, id, label, startedAt) ?: return
        }
    }

    private suspend fun pollOnce(paired: PairedPc, id: String, label: String, startedAt: Long): PcReply? {
        while (true) {
            try {
                return withContext(io) { gateway.status(paired, id) }
            } catch (e: PcException) {
                when (e.failure) {
                    PcFailure.Unreachable -> {
                        if (clockSeconds() - startedAt >= FOLLOW_SECONDS) {
                            finish(label, PcOutcome.Unknown, LOST_TOUCH)
                            return null
                        }
                        pause(POLL_MILLIS)
                    }
                    else -> {
                        finish(label, if (e.failure == PcFailure.UnknownRequest) PcOutcome.Unknown else outcomeFor(e.failure), e.message)
                        return null
                    }
                }
            }
        }
    }

    private fun finishFrom(label: String, reply: PcReply) {
        when (reply.status) {
            "verified" -> {
                val said = reply.speak
                if (said.isNullOrBlank()) finish(label, PcOutcome.Unknown, "Your PC says it worked, but I could not read its confirmation.")
                else finish(label, PcOutcome.Verified, said)
            }
            "failed" -> finish(label, PcOutcome.Failed, FAILED)
            "unknown" -> finish(label, PcOutcome.Unknown, UNKNOWN)
            "denied" -> finish(label, PcOutcome.Denied, DENIED)
            "expired" -> finish(label, PcOutcome.Expired, EXPIRED)
            "refused" -> finish(label, PcOutcome.Refused, refusalText(reply.reason))
            else -> finish(label, PcOutcome.Unknown, UNKNOWN) // a status this phone does not know is never a success
        }
    }

    private fun finish(label: String, outcome: PcOutcome, text: String) {
        _ui.value = PcPhase.Finished(label, outcome, text)
        onText(text)
    }

    private fun labelOf(phase: PcPhase): String? = when (phase) {
        is PcPhase.Sending -> phase.label
        is PcPhase.Retrying -> phase.label
        is PcPhase.WaitingForApproval -> phase.label
        is PcPhase.Running -> phase.label
        is PcPhase.Finished -> phase.label
        PcPhase.Idle -> null
    }

    private fun outcomeFor(failure: PcFailure) = when (failure) {
        PcFailure.Unauthorized -> PcOutcome.Revoked
        PcFailure.OutOfScope -> PcOutcome.OutOfScope
        PcFailure.NotAllowed -> PcOutcome.NotAllowed
        PcFailure.Expired -> PcOutcome.Expired
        PcFailure.Unreachable -> PcOutcome.Unreachable
        else -> PcOutcome.Refused
    }

    companion object {
        const val SEND_WINDOW_SECONDS = 110L // inside the PC's 120 s: a retry after this would be refused as late
        const val FOLLOW_SECONDS = 150L
        const val POLL_MILLIS = 1_500L
        const val RETRY_BASE_MILLIS = 2_000L
        const val RETRY_MAX_MILLIS = 10_000L

        const val NOT_PAIRED = "Pair this phone with your PC first (More, then Devices)."
        const val STILL_WAITING = "I'm still waiting on your PC for the last request."
        const val UNREACHABLE_UNKNOWN =
            "I couldn't reach your PC, so I don't know whether it got the request. Check the PC before asking again."
        const val LOST_TOUCH = "I lost touch with your PC, so I don't know what happened. Check Activity on the PC."
        const val GAVE_UP = "Your PC hasn't answered in a while, so I've stopped waiting. It may still happen; check the PC."
        const val CANCELLED = "Stopped waiting. If your PC already has the request it may still do it."
        const val FAILED = "That didn't work on your PC. Nothing was changed."
        const val UNKNOWN = "I couldn't confirm it worked on your PC. Check Activity there."
        const val DENIED = "Okay, it wasn't approved on your PC, so it didn't happen."
        const val EXPIRED = "That timed out on your PC, so it didn't happen."

        fun refusalText(reason: String) = when (reason) {
            "INVALID_ARGS" -> "Your PC doesn't know that app."
            "STATE_MISMATCH" -> "That clashed with an earlier request. Try again."
            "APPROVAL_REQUIRED", "DEVICE_REVOKED" -> "Your PC didn't accept that."
            else -> "Your PC refused that."
        }

        /** 22 characters from 16 random bytes: the PC accepts 16 to 64 of [A-Za-z0-9_-]. */
        fun randomId(): String =
            java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(16).also(SecureRandom()::nextBytes))
    }
}
