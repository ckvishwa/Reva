package app.reva.mood

import org.json.JSONArray
import org.json.JSONObject

/**
 * The mood engine, ported from `reva_core/language/mood.py` (docs/persona/REVA_Persona.md sections 2 and 3).
 *
 * A pure function: no model, no clock read, no I/O, no randomness. The rules are the same
 * `contracts/mood-rules.v1.json` the PC reads; `tests/fixtures/mood-cases.json` is written by the Python engine
 * and replayed in `MoodEngineTest`, so any difference between the two fails a test.
 *
 * What a mood can never do (CLAUDE.md safety invariants): change a risk tier, an approval or what REVA reports
 * happened; put a positive expression on an action result without a verified outcome; look happy during an
 * approval.
 */
enum class Mood(val wire: String) {
    Calm("calm"), Happy("happy"), Playful("playful"), Flirty("flirty"), Focused("focused"),
    Excited("excited"), Tired("tired"), Sad("sad"), Concerned("concerned");

    companion object {
        fun of(wire: String): Mood = entries.first { it.wire == wire }
    }
}

object MoodWords {
    // Events from the session and policy layer.
    const val VERIFIED_OUTCOME = "verified_outcome"
    const val FAILURE = "failure"
    const val APPROVAL_PENDING = "approval_pending"
    const val REFUSAL = "refusal"
    const val MILESTONE = "milestone"

    // Utterance flags, set by the language layer and never by a model.
    const val URGENT_HEALTH = "urgent_health"
    const val RISKY_REQUEST = "risky_request"
    const val SAFETY = "safety"
    const val USER_TIRED = "tired"
    const val USER_NOT_TIRED = "not_tired"
    const val USER_SAD = "sad"
    const val UPSET = "upset"
    const val CASUAL = "casual"
    const val GREETING = "greeting"
}

data class MoodSettings(
    val playfulness: Int = 0, // 0 to 10
    val flirtyAllowed: Boolean = false, // off by default
    val followTime: Boolean = true, // become tired late at night
)

data class MoodInputs(
    val hour: Int,
    val events: Set<String> = emptySet(),
    val flags: Set<String> = emptySet(),
    val domain: String? = null,
    val settings: MoodSettings = MoodSettings(),
    val workStreak: Int = 0,
    val workAppInFocus: Boolean = false,
    val minutesSinceSerious: Int? = null,
    val actionInFlight: Boolean = false,
    val verifiedActionId: String? = null,
)

data class MoodState(
    val mood: Mood = Mood.Calm,
    val turnsInMood: Int = 0,
    val tiredHeld: Boolean = false,
    val tiredSinceHour: Int? = null,
)

data class MoodAvatar(val expression: String, val clip: String, val then: String? = null, val soft: Boolean = false)

data class MoodVoice(val rate: Double, val pitchSt: Int, val softness: String)

data class MoodResult(
    val state: MoodState,
    val mood: Mood,
    val templateVariant: String,
    val voice: MoodVoice,
    val avatar: MoodAvatar,
    val reasons: List<String>,
)

/** An `avatar.expression` event the engine allows for this turn. */
data class ExpressionEvent(val name: String, val cause: String, val actionId: String? = null)

class MoodEngine(private val rules: JSONObject) {
    init {
        require(rules.optString("version") == "1.0") { "unsupported mood rules" }
    }

    private fun strings(array: JSONArray): List<String> = (0 until array.length()).map { array.getString(it) }
    private val thresholds = rules.getJSONObject("thresholds")
    private val restricted = rules.getJSONObject("restricted")
    private val flirtyOff = rules.getJSONObject("flirty_off_when")
    private val priority = strings(rules.getJSONArray("priority"))
    private val decays = strings(rules.getJSONArray("decays_to_calm")).toSet()
    private val positive = strings(rules.getJSONArray("positive_expressions")).toSet()
    private val restrictedDomains = strings(restricted.getJSONArray("domains")).toSet()
    private val restrictedEvents = strings(restricted.getJSONArray("events")).toSet()
    private val flirtyOffDomains = strings(flirtyOff.getJSONArray("domains")).toSet()
    private val flirtyOffEvents = strings(flirtyOff.getJSONArray("events")).toSet()
    private val flirtyOffFlags = strings(flirtyOff.getJSONArray("flags")).toSet()

    private fun sensitive(i: MoodInputs) = i.domain in restrictedDomains || i.events.any { it in restrictedEvents }

    private fun flirtyBlocked(i: MoodInputs) =
        i.domain in flirtyOffDomains || i.events.any { it in flirtyOffEvents } || i.flags.any { it in flirtyOffFlags }

    private fun isNight(hour: Int) = hour >= thresholds.getInt("tired_from_hour") && hour < thresholds.getInt("tired_until_hour")

    /** Whether "I'm tired" still holds: until 05:00, or until the user says otherwise. */
    private fun tiredHold(previous: MoodState, i: MoodInputs): Pair<Boolean, Int?> {
        val until = thresholds.getInt("tired_until_hour")
        val hour = i.hour
        if (MoodWords.USER_TIRED in i.flags) return true to hour
        if (MoodWords.USER_NOT_TIRED in i.flags || !previous.tiredHeld) return false to null
        val since = previous.tiredSinceHour ?: hour
        val crossedMorning = hour >= until && (since < until || hour < since)
        return if (crossedMorning) false to null else true to since
    }

    private fun candidate(previous: MoodState, i: MoodInputs, held: Boolean): Pair<Mood, String> {
        val events = i.events
        val flags = i.flags
        val seriousRecent = i.minutesSinceSerious != null && i.minutesSinceSerious < thresholds.getInt("serious_context_minutes")
        val lowStakes = (MoodWords.CASUAL in flags || MoodWords.GREETING in flags) && !sensitive(i) && !i.actionInFlight
        val rules: Map<String, Pair<Boolean, String>> = mapOf(
            "concerned" to (
                (flags.any { it in setOf(MoodWords.URGENT_HEALTH, MoodWords.RISKY_REQUEST, MoodWords.SAFETY) } ||
                    MoodWords.REFUSAL in events) to "concerned: health risk, risky request, safety or refusal"
                ),
            "sad" to ((MoodWords.FAILURE in events || MoodWords.USER_SAD in flags) to "sad: an action failed or bad news"),
            "tired" to (
                (held || (i.settings.followTime && isNight(i.hour))) to "tired: late at night or the user said so"
                ),
            "focused" to (
                (
                    i.workStreak >= thresholds.getInt("work_streak_for_focused") ||
                        i.workAppInFocus ||
                        (previous.mood == Mood.Focused && i.workStreak >= 1)
                    ) to "focused: work commands in a row or a work app in focus"
                ),
            "excited" to ((MoodWords.MILESTONE in events) to "excited: a milestone"),
            "happy" to ((MoodWords.VERIFIED_OUTCOME in events) to "happy: a verified success"),
            "flirty" to (
                (
                    i.settings.flirtyAllowed && lowStakes && !seriousRecent && !flirtyBlocked(i) &&
                        MoodWords.UPSET !in flags
                    ) to "flirty: opted in, casual, nothing serious lately"
                ),
            "playful" to (
                (
                    i.settings.playfulness >= thresholds.getInt("playfulness_min") && lowStakes &&
                        MoodWords.UPSET !in flags
                    ) to "playful: playfulness is high and the turn is casual"
                ),
        )
        for (name in priority) {
            val (matched, why) = rules[name] ?: (false to "")
            if (matched) return Mood.of(name) to why
        }
        return Mood.Calm to "calm: nothing else applies"
    }

    fun next(previous: MoodState, i: MoodInputs): MoodResult {
        val reasons = mutableListOf<String>()
        val (held, since) = tiredHold(previous, i)
        var (mood, why) = candidate(previous, i, held)
        val candidateMood = mood
        reasons += why

        if (mood == Mood.Calm && previous.mood in setOf(Mood.Happy, Mood.Excited, Mood.Sad)) {
            if (previous.mood.wire in decays && previous.turnsInMood < thresholds.getInt("decay_turns")) {
                mood = previous.mood
                reasons += "${previous.mood.wire} held until it has lasted ${thresholds.getInt("decay_turns")} turns"
            }
        }
        // Sensitive turns, errors, approvals and refusals only ever sound calm or concerned (sad too after a
        // failure). The mood never touches tiers, approvals or reported outcomes.
        if (sensitive(i)) {
            val allowed = strings(
                restricted.getJSONArray(if (MoodWords.FAILURE in i.events) "allowed_moods_when_failure" else "allowed_moods"),
            ).toSet()
            if (mood.wire !in allowed) {
                reasons += "${mood.wire} not allowed here; using calm"
                mood = Mood.Calm
            }
        }

        val fresh = candidateMood != Mood.Calm && mood.wire in decays
        val turns = if (fresh || mood != previous.mood) 1 else previous.turnsInMood + 1
        val state = MoodState(mood, turns, held, since)
        val tts = rules.getJSONObject("tts").getJSONObject(mood.wire)
        return MoodResult(
            state = state,
            mood = mood,
            templateVariant = mood.wire,
            voice = MoodVoice(tts.getDouble("rate"), tts.getInt("pitch_st"), tts.getString("softness")),
            avatar = avatarFor(mood, i),
            reasons = reasons,
        )
    }

    private fun avatarFor(mood: Mood, i: MoodInputs): MoodAvatar {
        val spec = rules.getJSONObject("avatar").getJSONObject(mood.wire)
        val avatar = MoodAvatar(
            spec.getString("expression"),
            spec.getString("clip"),
            if (spec.has("then")) spec.getString("then") else null,
            spec.optBoolean("soft", false),
        )
        // The approval pose with a neutral face: never happy while a decision is waiting.
        if (MoodWords.APPROVAL_PENDING in i.events) return MoodAvatar("neutral", "approval")
        if (avatar.expression in positive && i.actionInFlight) return MoodAvatar("neutral", avatar.clip)
        return avatar
    }

    fun ackPhrase(mood: Mood, turnNumber: Int): String {
        val phrases = rules.getJSONObject("ack").getJSONArray(mood.wire)
        return phrases.getString(Math.floorMod(turnNumber, phrases.length()))
    }

    /**
     * The `avatar.expression` event for this turn, or null when no expression change is allowed:
     * an action in flight blocks mood expressions, and a positive expression for an action result needs a
     * verified outcome and its action id.
     */
    fun expressionEvent(result: MoodResult, i: MoodInputs): ExpressionEvent? {
        if (MoodWords.APPROVAL_PENDING in i.events || i.actionInFlight) return null
        val name = result.avatar.expression
        val isPositive = name in positive
        if (MoodWords.VERIFIED_OUTCOME in i.events) {
            val id = i.verifiedActionId ?: return null // no evidence to point at: no expression for the result
            return ExpressionEvent(name, "verified_outcome", id)
        }
        if (isPositive && result.mood in setOf(Mood.Happy, Mood.Excited) && MoodWords.GREETING !in i.flags) return null
        return ExpressionEvent(name, "mood")
    }
}
