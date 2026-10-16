package app.reva.phone

import app.reva.language.Outcomes
import app.reva.pcrequests.PcPhrases
import app.reva.policy.Approval
import app.reva.policy.AuthState
import app.reva.policy.Proposal
import app.reva.policy.Registry
import app.reva.policy.argsHash
import app.reva.policy.authorize
import app.reva.voice.ReplySource
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Hands an intent to Android. The real one resolves and starts activities; tests record what they were given. */
interface IntentPort {
    /** The label of the app that would handle [spec], or null when nothing on this phone can. Starts nothing. */
    fun resolve(spec: IntentSpec): String?

    /** Starts it. False if Android refused. */
    fun start(spec: IntentSpec): Boolean
}

/** A confirm card waiting for a tap. The sentence was written before anything ran. */
data class ActionCard(val id: String, val label: String, val prompt: String, val deadline: Instant)

/**
 * What the executor saw. `verified` needs evidence of the kind the registry expects for the capability and a
 * reference of the right shape ([PhoneActions.evidenceOk]); anything handed to another app's screen is only
 * `observed`, because whether the owner then tapped Save cannot be seen.
 */
data class PhoneReport(val status: String, val evidenceKind: String?, val evidenceRef: String?)

/**
 * The phone's own actions, with the same authorize() as the PC: open an approved app (T1), and hand an alarm,
 * reminder, calendar event or share to the Clock, Calendar and share sheet (T2). A T2 action waits for a tap on
 * the confirm card on THIS phone; a spoken "yes" is only text and never reaches [approve]. Nothing here says an
 * alarm "was set" or an event "was added": the other app's screen is where the owner finishes it.
 */
class PhoneActions(
    private val registry: Registry,
    private val apps: ApprovedApps,
    private val port: IntentPort,
    private val clock: () -> Instant = { Instant.now() },
    private val zone: () -> ZoneId = { ZoneId.systemDefault() },
    private val newId: () -> String = { UUID.randomUUID().toString() },
    private val onText: (String) -> Unit = {},
) {
    private class Pending(val card: ActionCard, val intent: PhoneIntent, val proposal: Proposal)

    private var pending: Pending? = null
    private val _card = MutableStateFlow<ActionCard?>(null)
    val card: StateFlow<ActionCard?> = _card.asStateFlow()

    /** A reply when [text] is one of the phone's own commands, or null (the sentence is for something else). */
    fun handle(text: String): ReplySource.Reply? {
        expire()
        val now = clock()
        val parsed = PhoneRules.parse(text, now, zone()) ?: return null
        val intent = when (parsed) {
            is PhoneParse.Ask -> return template(parsed.question)
            is PhoneParse.Action -> parsed.intent
        }
        if (intent.capability == "android.app.open") return openApp(intent)
        if (pending != null) return template(BUSY)
        return propose(intent, intent.args)
    }

    /** The Confirm button. A tap on this phone's screen: the only approval that exists here. */
    fun approve(cardId: String) {
        val waiting = pending?.takeIf { it.card.id == cardId } ?: return
        pending = null
        _card.value = null
        val approval = Approval(
            proposalId = waiting.proposal.proposalId,
            argsHash = argsHash(waiting.proposal.args),
            targetDevice = PHONE,
            user = "owner",
            via = "tap",
            expiresAt = waiting.card.deadline,
        )
        val decision = authorize(waiting.proposal, AuthState(clock(), approval = approval), registry)
        if (!decision.allowed) {
            onText(if (decision.reason == "APPROVAL_REQUIRED") PhoneOutcomes.TIMED_OUT else Outcomes.refusalText(decision.reason, waiting.proposal.capability))
            return
        }
        onText(execute(waiting.intent))
    }

    fun deny(cardId: String) {
        if (pending?.card?.id != cardId) return
        pending = null
        _card.value = null
        onText(PhoneOutcomes.DENIED)
    }

    /** A card nobody tapped goes away on its own. */
    fun expire() {
        val waiting = pending ?: return
        if (!clock().isBefore(waiting.card.deadline)) {
            pending = null
            _card.value = null
            onText(PhoneOutcomes.TIMED_OUT)
        }
    }

    fun close() {
        pending = null
        _card.value = null
    }

    // ------------------------------------------------------------------ steps

    private fun openApp(intent: PhoneIntent): ReplySource.Reply? {
        val alias = intent.args.getValue("package_alias").toString()
        val app = apps.resolve(alias)
        if (app == null) {
            // "open the pod bay doors" is a sentence for the assistant, not a failed app launch.
            return if (PcPhrases.tokens(alias).size > MAX_APP_WORDS) null else template(PhoneOutcomes.notApproved(alias))
        }
        val proposal = proposal(intent.capability, intent.args)
        val decision = authorize(proposal, AuthState(clock()), registry)
        if (!decision.allowed) return template(Outcomes.refusalText(decision.reason, intent.capability))
        val spec = PhoneIntents.open(app.packageName)
        val target = port.resolve(spec) ?: return template(PhoneOutcomes.NO_APP)
        if (!port.start(spec)) return template(PhoneOutcomes.FAILED)
        val report = PhoneReport("verified", "intent_resolved", "pkg:${app.packageName}")
        return template(PhoneOutcomes.text(intent, report, target, registry))
    }

    private fun propose(intent: PhoneIntent, args: Map<String, Any?>): ReplySource.Reply {
        val proposal = proposal(intent.capability, args)
        val decision = authorize(proposal, AuthState(clock()), registry)
        if (decision.allowed) return template(execute(intent))
        if (decision.reason != "APPROVAL_REQUIRED") return template(Outcomes.refusalText(decision.reason, intent.capability))
        val deadline = clock().plusSeconds(APPROVAL_SECONDS)
        val card = ActionCard(newId(), intent.label, "${intent.summary} Confirm on screen.", deadline)
        pending = Pending(card, intent, proposal)
        _card.value = card
        return template(card.prompt)
    }

    private fun proposal(capability: String, args: Map<String, Any?>) = Proposal(
        proposalId = newId(),
        capability = capability,
        args = args,
        source = "rule",
        originDevice = PHONE,
        targetDevice = PHONE,
    )

    /** Builds the intent, checks something can handle it, starts it, and words the result from what was seen. */
    private fun execute(intent: PhoneIntent): String {
        val spec = try {
            specFor(intent)
        } catch (e: IllegalArgumentException) {
            return PhoneOutcomes.FAILED
        }
        val target = port.resolve(spec) ?: return PhoneOutcomes.NO_APP
        if (!port.start(spec)) return PhoneOutcomes.FAILED
        // The other app's screen is where the owner finishes it: observed, never verified.
        return PhoneOutcomes.text(intent, PhoneReport("observed", null, null), target, registry)
    }

    private fun specFor(intent: PhoneIntent): IntentSpec {
        val a = intent.args
        return when (intent.capability) {
            "android.alarm.set" -> {
                val (h, m) = a.getValue("time").toString().split(":").map { it.toInt() }
                PhoneIntents.alarm(h, m, a["label"]?.toString())
            }
            "android.reminder.set" -> {
                val due = OffsetDateTime.parse(a.getValue("due").toString())
                PhoneIntents.calendarEvent(a.getValue("text").toString(), due, due.plusMinutes(15), null, withAlarm = true)
            }
            "android.calendar.insert" -> {
                val start = OffsetDateTime.parse(a.getValue("start").toString())
                val end = a["end"]?.let { OffsetDateTime.parse(it.toString()) } ?: start.plusHours(1)
                PhoneIntents.calendarEvent(a.getValue("title").toString(), start, end, a["location"]?.toString(), withAlarm = false)
            }
            "android.share" -> PhoneIntents.share(a.getValue("text").toString())
            else -> throw IllegalArgumentException("not a hand-off")
        }
    }

    private fun template(text: String) = ReplySource.Reply(text, "template")

    companion object {
        const val PHONE = "phone"
        const val APPROVAL_SECONDS = 120L
        const val MAX_APP_WORDS = 4
        const val BUSY = "Finish the one on screen first: Confirm or Not now."

        private val REF_SHAPES = mapOf("intent_resolved" to Regex("^pkg:[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+$"))

        /** Success needs evidence of the kind the registry expects for this capability, and a reference that fits. */
        fun evidenceOk(registry: Registry, capability: String, report: PhoneReport): Boolean {
            val expected = registry[capability]?.evidenceKind ?: return false
            val ref = report.evidenceRef ?: return false
            val shape = REF_SHAPES[expected] ?: return false // no shape known for this kind: not enough to claim success
            return report.evidenceKind == expected && ref.length <= 200 && shape.matches(ref)
        }
    }
}

object PhoneOutcomes {
    const val FAILED = "That didn't work. Nothing was changed."
    const val NO_APP = "There's no app on this phone that can do that."
    const val TIMED_OUT = "That timed out, so I didn't do it."
    const val DENIED = "Okay, I won't do that."

    fun notApproved(alias: String) = "I can't open ${alias.take(40)}. Approve it in Apps first."

    private val clockText = DateTimeFormatter.ofPattern("h:mm a")

    /**
     * The one sentence for what happened. "Opened X." exists only for a verified outcome with evidence; everything
     * handed to another app says it was handed over and what is left for the owner to do.
     */
    fun text(intent: PhoneIntent, report: PhoneReport, target: String, registry: Registry): String {
        if (report.status == "verified") {
            return if (PhoneActions.evidenceOk(registry, intent.capability, report)) "Opened $target." else UNCONFIRMED
        }
        return when (intent.capability) {
            "android.alarm.set" -> "Handed it to $target: the alarm for ${time(intent)} is ready. Tap Save there to finish."
            "android.reminder.set" -> "Handed it to $target: your reminder is ready. Tap Save there to finish."
            "android.calendar.insert" -> "Handed it to $target: the event is ready. Tap Save there to finish."
            "android.share" -> "Handed it to the share sheet. Pick where it goes there."
            else -> UNCONFIRMED
        }
    }

    const val UNCONFIRMED = "I couldn't confirm that it worked."

    private fun time(intent: PhoneIntent): String {
        val hhmm = intent.args["time"]?.toString() ?: return "that time"
        val (h, m) = hhmm.split(":").map { it.toInt() }
        return java.time.LocalTime.of(h, m).format(clockText)
    }
}
