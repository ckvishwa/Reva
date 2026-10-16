package app.reva.language

/**
 * What REVA says, as templates bound to what happened, never to model text. Ported from
 * `reva_core/language/outcomes.py`; the refusal sentences are checked against the Python ones in `RulesTest`
 * (`refusals` in `tests/fixtures/rules-cases.json`).
 *
 * A success sentence exists for exactly one case: a verified outcome with evidence from an executor. Nothing on
 * the phone produces one yet, so none is ported; every sentence here claims nothing happened.
 */
object Outcomes {
    const val REFUSED_MONEY = "I can't move money. I can record it or show your spending."
    const val REFUSED_GENERIC = "I can't do that."
    const val REFUSED_MEDICAL = "I can't give medical advice or doses. A doctor or pharmacist can."
    const val NOT_UNDERSTOOD = "I didn't catch all of that. Say it again, or use the screen."
    const val NOT_APPROVED = "I need your approval on screen before I do that."
    const val NOTHING_TO_UNDO = "There's nothing I can undo."
    const val NOTHING_TO_REPEAT = "I haven't said anything yet."

    /** The sentence for a proposal that was not authorized. */
    fun refusalText(reason: String, capability: String): String {
        if (reason == "FORBIDDEN_CAPABILITY") {
            return when {
                capability.startsWith("finance.") -> REFUSED_MONEY
                capability.startsWith("health.") -> REFUSED_MEDICAL
                else -> REFUSED_GENERIC
            }
        }
        if (reason in setOf("UNRESOLVED_TERMS", "LOW_EVIDENCE", "AMBIGUOUS_ENTITY")) return NOT_UNDERSTOOD
        if (reason == "APPROVAL_REQUIRED") return NOT_APPROVED
        return REFUSED_GENERIC
    }
}
