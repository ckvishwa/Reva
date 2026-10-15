package app.reva.language

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
) : ReplySource {
    override suspend fun reply(text: String): ReplySource.Reply {
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

    companion object {
        const val NOT_ON_PHONE_YET = "I understood that, but the phone can't do it yet. Nothing was changed."
    }
}
