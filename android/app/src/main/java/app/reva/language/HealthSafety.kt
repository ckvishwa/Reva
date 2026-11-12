package app.reva.language

/** Fixed local safety response. Matched before any planner, network provider, or action parser. */
object HealthSafety {
    const val URGENT_MESSAGE = "If this could be urgent, contact emergency services now. For medical questions, contact a qualified health professional."
    private val urgent = Regex(
        "\\b(?:chest pain|trouble breathing|can't breathe|cannot breathe|stroke signs?|overdos(?:e|ed|ing)|self[- ]harm|harm myself|kill myself|suicid(?:e|al))\\b",
        RegexOption.IGNORE_CASE,
    )

    fun isUrgent(text: String): Boolean = urgent.containsMatchIn(text.take(2_000))
}
