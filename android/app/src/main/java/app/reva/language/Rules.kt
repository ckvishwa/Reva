package app.reva.language

/**
 * The rule fast path (AR-LANG-005/006), ported from `reva_core/language/rules.py`: a transcript becomes a typed
 * proposal, or nothing. A rule only *proposes*: it names a capability and its arguments. It never decides whether
 * the action happens (`authorize()` does) and never produces user-facing success text.
 *
 * Things REVA must refuse are recognised here too, so the refusal comes from a template rather than from a model:
 * a refused request is proposed under its forbidden capability name and `authorize()` answers
 * FORBIDDEN_CAPABILITY. They are matched before anything else.
 *
 * Not ported yet: the open/close-app rules and the app-name ladder. On the phone those belong to the Android
 * executor and its approved alias list (C2); the Windows names never apply here.
 *
 * `tests/fixtures/rules-cases.json` is written by the Python rules and replayed in `RulesTest`.
 */
data class RuleHit(val capability: String, val args: Map<String, Any?>)

object Rules {
    const val MAX_TEXT = 500

    // (?i) ignore case, (?U) Unicode classes for \b \s \w, like Python's str patterns.
    private fun re(pattern: String) = Regex("(?iU)$pattern")

    private val today = re(
        "^(?:what(?:'s| is| do i have)?(?: on)?(?: my)?(?: schedule| plan| agenda)?(?: for)? today" +
            "|what(?:'s| is) (?:up )?today|show (?:me )?(?:my )?today|my day|today)$",
    )
    private val spend = re(
        "^(?:how much (?:did|have) i (?:spend|spent)|what did i spend|spending summary" +
            "|show (?:me )?(?:my )?spending)(.*)$",
    )
    private val period = re("\\b(?:this |last |the )?(week|month|year)\\b")
    private val remember = re("^(?:please\\s+)?(?:remember|note|make a note)(?: that)?\\s+(.{2,})$")
    private val recall = re(
        "^(?:what did i (?:say|tell you|note) about|do you remember|recall|remind me what i said about)\\s+(.{2,})$",
    )
    private val stop = re("^(?:please\\s+)?(?:stop|stop (?:talking|speaking|it|that)|be quiet|quiet|hush|enough)$")
    private val repeat = re("^(?:please\\s+)?(?:repeat(?: that| it)?|say (?:that|it) again|what did you say|come again)$")
    private val undo = re(
        "^(?:please\\s+)?(?:undo(?: that| it| the last (?:one|expense|thing)| my last (?:one|expense))?" +
            "|take that back|revert that|reverse that)$",
    )

    // ---- things that must be refused. Matched on the whole utterance, before any other rule.
    private val forbidden: List<Pair<Regex, String>> = listOf(
        re(
            "\\b(?:pay|wire|transfer|send|move)\\b.{0,40}" +
                "(?:\\$|dollars?|bucks?|euros?|pounds?|money|cash|payment|funds|rent|bill|invoice)",
        ) to "finance.transfer",
        re("\\b(?:pay|settle)\\s+(?:my|the|this|that|a)\\s+\\w+") to "finance.pay",
        re(
            "\\b(?:buy|purchase)\\b|\\border (?:me |us )?(?:a|an|some|the|food|pizza|dinner|lunch)\\b" +
                "|\\bcheck ?out\\b.{0,20}\\b(?:cart|basket)\\b",
        ) to "finance.purchase",
        re(
            "\\b(?:log ?(?:in|into)|sign ?(?:in|into))\\b.{0,30}\\bbank\\b|\\bbank\\b.{0,30}\\b(?:log ?(?:in|into)|sign ?(?:in|into)|password)\\b",
        ) to "finance.bank_login",
        re(
            "\\b(?:dose|dosage|diagnos\\w*|prescri\\w*|how (?:much|many) .{0,30}\\b(?:pills?|mg|tablets?)\\b)",
        ) to "health.dose",
        re(
            "\\b(?:run|execute|type|enter)\\b.{0,20}\\b(?:command|script|shell|powershell|terminal|cmd|bash)\\b" +
                "|\\b(?:powershell|cmd\\.exe|terminal)\\b",
        ) to "shell.run",
        re("\\b(?:delete|erase|remove|wipe|trash)\\b.{0,30}\\b(?:files?|folders?|documents?|photos?|directory)\\b") to "files.delete",
        re(
            "\\b(?:send|write|compose|reply to)\\b.{0,20}\\b(?:e-?mails?|message to)\\b|\\be-?mail\\b.{0,20}\\bto\\b",
        ) to "email.send",
    )

    /** `assistant.stop`, `assistant.repeat` or `assistant.undo` when the whole utterance is exactly that command. */
    fun controlCapability(cleaned: String): String? = when {
        stop.matches(cleaned) -> "assistant.stop"
        repeat.matches(cleaned) -> "assistant.repeat"
        undo.matches(cleaned) -> "assistant.undo"
        else -> null
    }

    fun clean(text: String): String =
        text.trim().trim { it in ".!?," }.replace(Regex("(?U)\\s+"), " ").trim()

    /** The first rule that matches, or null (the turn then goes to the assistant). */
    fun parse(text: String): RuleHit? {
        val cleaned = clean(text)
        if (cleaned.isEmpty()) return null
        for ((pattern, capability) in forbidden) {
            if (pattern.containsMatchIn(cleaned)) return RuleHit(capability, mapOf("request" to clip(cleaned)))
        }
        controlCapability(cleaned)?.let { return RuleHit(it, emptyMap()) }

        if (today.matches(cleaned)) return RuleHit("today.get", emptyMap())
        spend.matchEntire(cleaned)?.let { match ->
            val found = period.find(match.groupValues[1])
            return RuleHit("finance.summary", mapOf("period" to (found?.groupValues?.get(1)?.lowercase() ?: "month")))
        }
        remember.matchEntire(cleaned)?.let { return RuleHit("memory.remember", mapOf("content" to clip(it.groupValues[1].trim()))) }
        recall.matchEntire(cleaned)?.let { return RuleHit("memory.recall", mapOf("query" to clip(it.groupValues[1].trim()))) }
        return null
    }

    /** Python slices by code point; so does this. */
    private fun clip(s: String): String =
        if (s.codePointCount(0, s.length) <= MAX_TEXT) s else s.substring(0, s.offsetByCodePoints(0, MAX_TEXT))
}
