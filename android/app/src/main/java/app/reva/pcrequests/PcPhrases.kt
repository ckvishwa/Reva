package app.reva.pcrequests

/**
 * "Open Calculator on my PC", "close Spotify on my laptop": a sentence that names the PC becomes a request for
 * the PC to act. Only the two exact rungs of the app ladder are used (a canonical name or an approved alias, the
 * same words `reva_core/language/entities.py` uses); a guess is never sent. A sentence that does not name the PC
 * is not handled here (the phone's own actions come later and must never be confused with these).
 *
 * `tests/fixtures/policy-cases.json` ("app_resolution") is written by the Python resolver and replayed in
 * `PcPhrasesTest`, so the two lists of words cannot drift apart.
 */
data class PcIntent(
    /** `windows.app.open` or `windows.app.close`. */
    val capability: String,
    /** What the owner said the app was called. */
    val phrase: String,
    /** The PC's canonical app key, or null when the phrase is not one the phone can name. */
    val appKey: String?,
)

object PcPhrases {
    /** Words that carry no meaning for picking an app (same list as the PC). */
    val FILLER = setOf(
        "a", "an", "the", "my", "up", "app", "apps", "application", "program", "window", "please",
        "for", "me", "now", "can", "you", "could", "would", "will", "to", "just", "again", "pls",
        "hey", "reva", "ok", "okay", "go", "and", "then",
    )

    /** The built-in apps and the aliases the owner approved by default (same table as the PC). */
    val ALIASES: Map<String, List<String>> = mapOf(
        "notepad" to listOf("notepad", "notes app"),
        "calculator" to listOf("calculator", "calc"),
        "chrome" to listOf("chrome", "google chrome", "browser", "the browser"),
        "vscode" to listOf("vscode", "vs code", "visual studio code", "code", "vs-code"),
        "spotify" to listOf("spotify", "music", "music app"),
    )

    private val request = Regex(
        "(?iU)^(?:please\\s+)?(open|launch|start|close|quit|exit|shut down|shut)\\s+(.+?)\\s+(?:on|from|in)\\s+" +
            "(?:my|the)\\s+(?:pc|computer|laptop|desktop|windows pc|windows)$",
    )
    private val opening = setOf("open", "launch", "start")

    fun tokens(text: String): List<String> =
        Regex("[a-z0-9]+").findAll(text.lowercase().replace("-", " ")).map { it.value }.toList()

    fun contentTokens(text: String): List<String> = tokens(text).filter { it !in FILLER }

    /**
     * The PC's app key for [phrase], or null unless its meaningful words are exactly a canonical name or an approved
     * alias (compared as written, like the PC does: "notes app" is not "notes").
     */
    fun resolveApp(phrase: String): String? {
        val joined = contentTokens(phrase).joinToString(" ")
        if (joined.isEmpty()) return null
        for ((key, names) in ALIASES) {
            if (joined == key || names.any { it == joined }) return key
        }
        return null
    }

    fun parse(text: String): PcIntent? {
        val cleaned = text.trim().trim { it in ".!?," }.replace(Regex("(?U)\\s+"), " ").trim()
        val match = request.matchEntire(cleaned) ?: return null
        val verb = match.groupValues[1].lowercase()
        val phrase = match.groupValues[2].trim()
        val capability = if (verb in opening) "windows.app.open" else "windows.app.close"
        return PcIntent(capability, phrase, resolveApp(phrase))
    }
}
