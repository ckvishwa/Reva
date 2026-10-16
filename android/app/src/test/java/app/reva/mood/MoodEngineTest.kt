package app.reva.mood

import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Replays `tests/fixtures/mood-cases.json`, which the Python engine writes, against the Kotlin port. One
 * difference in any of ~660 cases (mood, voice, avatar, reasons, state or expression event) fails the build.
 */
class MoodEngineTest {
    private val fixtures = File(System.getProperty("reva.fixtures"))
    private val rulesText = File(System.getProperty("reva.contracts"), "mood-rules.v1.json").readText()
    private val engine = MoodEngine(JSONObject(rulesText))
    private val data = JSONObject(File(fixtures, "mood-cases.json").readText())

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }
    private fun JSONObject.stringOrNull(key: String) = if (isNull(key)) null else getString(key)
    private fun JSONObject.intOrNull(key: String) = if (isNull(key)) null else getInt(key)

    private fun state(o: JSONObject) = MoodState(
        Mood.of(o.getString("mood")), o.getInt("turns_in_mood"), o.getBoolean("tired_held"), o.intOrNull("tired_since_hour"),
    )

    private fun inputs(o: JSONObject) = MoodInputs(
        hour = o.getInt("hour"),
        events = o.getJSONArray("events").strings().toSet(),
        flags = o.getJSONArray("flags").strings().toSet(),
        domain = o.stringOrNull("domain"),
        settings = MoodSettings(o.getInt("playfulness"), o.getBoolean("flirty_allowed"), o.getBoolean("follow_time")),
        workStreak = o.getInt("work_streak"),
        workAppInFocus = o.getBoolean("work_app_in_focus"),
        minutesSinceSerious = o.intOrNull("minutes_since_serious"),
        actionInFlight = o.getBoolean("action_in_flight"),
        verifiedActionId = o.stringOrNull("verified_action_id"),
    )

    @Test fun every_case_matches_the_python_engine() {
        val cases = data.getJSONArray("cases")
        assertTrue("fixture should be large", cases.length() > 500)
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val previous = state(case.getJSONObject("previous"))
            val given = inputs(case.getJSONObject("inputs"))
            val want = case.getJSONObject("expected")

            val got = engine.next(previous, given)
            val label = "case $index: ${case.getJSONObject("inputs")}"

            assertEquals(label, want.getString("mood"), got.mood.wire)
            assertEquals(label, want.getString("template_variant"), got.templateVariant)
            assertEquals(label, state(want.getJSONObject("state")), got.state)
            val voice = want.getJSONObject("voice")
            assertEquals(label, MoodVoice(voice.getDouble("rate"), voice.getInt("pitch_st"), voice.getString("softness")), got.voice)
            val avatar = want.getJSONObject("avatar")
            assertEquals(
                label,
                MoodAvatar(avatar.getString("expression"), avatar.getString("clip"), avatar.stringOrNull("then"), avatar.getBoolean("soft")),
                got.avatar,
            )
            assertEquals(label, want.getJSONArray("reasons").strings(), got.reasons)

            val event = engine.expressionEvent(got, given)
            if (want.isNull("expression_event")) {
                assertNull(label, event)
            } else {
                val e = want.getJSONObject("expression_event")
                assertEquals(label, ExpressionEvent(e.getString("name"), e.getString("cause"), e.stringOrNull("action_id")), event)
            }
        }
    }

    @Test fun utterance_flags_match_the_python_answers() {
        val rows = data.getJSONArray("utterance_flags")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            assertEquals(row.getString("text"), row.getJSONArray("flags").strings().toSet(), MoodFlags.of(row.getString("text")))
        }
    }

    @Test fun ack_phrases_rotate_like_the_python_ones() {
        val acks = data.getJSONObject("acks")
        for (mood in Mood.entries) {
            val want = acks.getJSONArray(mood.wire).strings()
            assertEquals(mood.wire, want, (0 until 5).map { engine.ackPhrase(mood, it) })
        }
    }

    @Test fun safety_invariants_hold_for_every_fixture_case() {
        val cases = data.getJSONArray("cases")
        for (index in 0 until cases.length()) {
            val case = cases.getJSONObject(index)
            val given = inputs(case.getJSONObject("inputs"))
            val got = engine.next(state(case.getJSONObject("previous")), given)
            val event = engine.expressionEvent(got, given)
            if (MoodWords.APPROVAL_PENDING in given.events) {
                assertEquals("neutral", got.avatar.expression)
                assertNull("no expression event during an approval", event)
            }
            if (event?.cause == "verified_outcome") {
                assertTrue(MoodWords.VERIFIED_OUTCOME in given.events)
                assertTrue(event.actionId != null)
            }
            if (given.actionInFlight) assertNull(event)
            if (got.mood == Mood.Flirty) {
                assertTrue("flirty only when opted in", given.settings.flirtyAllowed)
                assertFalse(given.domain in setOf("finance", "health", "memory"))
            }
        }
    }

    @Test fun no_ack_phrase_creates_dependency_or_jealousy() {
        val rules = JSONObject(rulesText)
        val forbidden = rules.getJSONArray("forbidden_phrases").strings()
        val acks = rules.getJSONObject("ack")
        for (key in acks.keys()) for (phrase in acks.getJSONArray(key).strings()) {
            for (bad in forbidden) assertFalse("$phrase contains $bad", phrase.lowercase().contains(bad))
        }
    }
}
