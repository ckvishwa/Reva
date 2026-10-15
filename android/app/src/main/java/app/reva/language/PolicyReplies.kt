package app.reva.language

import app.reva.pcrequests.PcIntent
import app.reva.pcrequests.PcPhrases
import app.reva.pcrequests.PcRequestTracker
import app.reva.pcrequests.PcStart
import app.reva.phone.PhoneActions
import app.reva.policy.AuthState
import app.reva.policy.Proposal
import app.reva.policy.Registry
import app.reva.policy.authorize
import app.reva.voice.ReplySource
import app.reva.voice.UnavailableReplies
import java.time.Instant
import java.util.UUID

/**
 * Answers a sentence the way the PC does before it reaches any model: the rule fast path turns it into a typed
 * proposal and the same `authorize()` decides. The phone has no executor and no data engine behind this yet, so an
 * allowed proposal is answered "not on the phone yet" and nothing is claimed done. A refused one gets its refusal
 * template. A sentence no rule matches is an open question, which the phone cannot answer yet.
 *
 * The assistant controls (stop, repeat) are handled by the voice controller itself; undo has nothing to undo here.
 */
class PolicyReplies(
    private val registry: Registry,
    private val clock: () -> Instant = { Instant.now() },
    private val fallback: ReplySource = UnavailableReplies(),
    /** Where a request for the PC goes. Null: this build cannot ask the PC. */
    private val pc: PcRequestTracker? = null,
    /** The phone's own actions (open an approved app, alarm, reminder, calendar, share). */
    private val phone: PhoneActions? = null,
) : ReplySource {
    override suspend fun reply(text: String): ReplySource.Reply {
        PcPhrases.parse(text)?.let { return forPc(it) }
        phone?.handle(text)?.let { return it }
        val hit = Rules.parse(text) ?: return fallback.reply(text)
        if (hit.capability == "assistant.undo") return ReplySource.Reply(Outcomes.NOTHING_TO_UNDO, "template")
        val decision = authorize(
            Proposal(
                proposalId = UUID.randomUUID().toString(),
                capability = hit.capability,
                args = hit.args,
                source = "rule",
                originDevice = "phone",
                targetDevice = "phone",
            ),
            AuthState(clock()),
            registry,
        )
        if (!decision.allowed && decision.reason != "APPROVAL_REQUIRED") {
            return ReplySource.Reply(Outcomes.refusalText(decision.reason, hit.capability), "template")
        }
        return ReplySource.Reply(NOT_ON_PHONE_YET, "template")
    }

    /**
     * "Open Calculator on my PC": the same `authorize()` runs first (a sensitive request is allowed to go to the
     * PC to wait for a click THERE; the phone never approves it), then the request is handed to the tracker. What
     * this says is only that it was asked; the outcome arrives later from the PC's own report.
     */
    private fun forPc(intent: PcIntent): ReplySource.Reply {
        val tracker = pc ?: return ReplySource.Reply(NO_PC_REQUESTS, "template")
        val key = intent.appKey ?: return ReplySource.Reply(
            "I don't know an app called ${intent.phrase.take(40)} on your PC.", "template",
        )
        val decision = authorize(
            Proposal(
                proposalId = UUID.randomUUID().toString(),
                capability = intent.capability,
                args = mapOf("app_key" to key),
                source = "rule",
                originDevice = "phone",
                targetDevice = "pc",
            ),
            AuthState(clock(), deviceScopes = setOf("windows")),
            registry,
        )
        if (!decision.allowed && decision.reason != "APPROVAL_REQUIRED") {
            return ReplySource.Reply(Outcomes.refusalText(decision.reason, intent.capability), "template")
        }
        val name = Outcomes.APP_NAMES[key] ?: key
        val opening = intent.capability == "windows.app.open"
        return when (val started = tracker.start(intent.capability, mapOf("app_key" to key), (if (opening) "Open " else "Close ") + name)) {
            PcStart.Started -> ReplySource.Reply(
                if (opening) "Asking your PC to open $name." else "Asking your PC to close $name. Approve it on the PC.",
                "template",
            )
            is PcStart.Refused -> ReplySource.Reply(started.text, "template")
        }
    }

    companion object {
        const val NO_PC_REQUESTS = "This phone can't ask your PC to do things yet."
        const val NOT_ON_PHONE_YET = "I understood that, but the phone can't do it yet. Nothing was changed."
    }
}
