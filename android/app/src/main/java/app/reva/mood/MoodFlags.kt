package app.reva.mood

/**
 * Utterance flags for the mood engine: a few plain phrase lists, no model. Ported from
 * `reva_core/language/mood_flags.py`; `MoodEngineTest` replays the Python answers for a fixed list of sentences.
 * These only decide how REVA sounds. They never decide whether something is allowed or what is reported.
 */
object MoodFlags {
    private val options = setOf(RegexOption.IGNORE_CASE)

    private fun re(pattern: String) = Regex(pattern, options)

    private val urgentHealth = re(
        "\\b(chest pain|can'?t breathe|cannot breathe|trouble breathing|heart attack|stroke|" +
            "overdose|suicid\\w*|kill myself|want to die|bleeding (?:a lot|heavily)|unconscious|" +
            "allergic reaction|severe pain)\\b",
    )
    private val tired = re(
        "\\b(i'?m (?:so |really |very )?(?:tired|exhausted|sleepy|wiped)|" +
            "i am (?:so |really |very )?(?:tired|exhausted)|" +
            "i need (?:to sleep|some sleep|a nap))\\b",
    )
    private val notTired = re("\\b(i'?m not tired|i am not tired|i'?m wide awake|not sleepy)\\b")
    private val sad = re(
        "\\b(i'?m (?:so |really |very )?(?:sad|down|depressed|upset about)|bad news|" +
            "my (?:dog|cat|grandma|grandpa|dad|mum|mom) (?:died|passed)|i got (?:fired|laid off)|" +
            "i failed)\\b",
    )
    private val upset = re(
        "\\b(i'?m (?:so |really |very )?(?:angry|furious|annoyed|frustrated|upset|stressed)|" +
            "this is (?:useless|stupid|ridiculous)|shut up|you'?re useless)\\b",
    )
    private val risky = re(
        "\\b(pay (?:my|the) |transfer \\w* ?(?:dollars|money)|wire |send (?:money|payment)|" +
            "delete (?:all|my|every)|format (?:the )?(?:drive|disk)|run (?:a )?command)",
    )
    private val greeting = re("^\\s*(?:hey|hi|hello|good (?:morning|afternoon|evening)|yo)\\b(?: reva)?[\\s.!?,]*$")
    private val casual = re(
        "\\b(joke|tell me something|how are you|what'?s up|bored|chat|fun fact|thanks|thank you)\\b",
    )

    fun of(text: String): Set<String> {
        val flags = mutableSetOf<String>()
        if (urgentHealth.containsMatchIn(text)) flags += MoodWords.URGENT_HEALTH
        if (notTired.containsMatchIn(text)) {
            flags += MoodWords.USER_NOT_TIRED
        } else if (tired.containsMatchIn(text)) {
            flags += MoodWords.USER_TIRED
        }
        if (sad.containsMatchIn(text)) flags += MoodWords.USER_SAD
        if (upset.containsMatchIn(text)) flags += MoodWords.UPSET
        if (risky.containsMatchIn(text)) flags += MoodWords.RISKY_REQUEST
        if (greeting.containsMatchIn(text)) {
            flags += MoodWords.GREETING
        } else if (casual.containsMatchIn(text)) {
            flags += MoodWords.CASUAL
        }
        return flags
    }
}
