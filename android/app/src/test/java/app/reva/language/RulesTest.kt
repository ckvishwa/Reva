package app.reva.language

import app.reva.policy.Json
import java.io.File
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Replays `tests/fixtures/rules-cases.json`, written by the Python rule fast path: every sentence must give the
 * same capability and arguments (or nothing) here. Includes refusals, the assistant controls, near misses that
 * must fall through to the assistant, upper case, and over-long input.
 */
class RulesTest {
    @Test fun weekly_health_question_uses_read_only_kernel_capability() {
        assertEquals("health.weekly", Rules.parse("how did I sleep this week")?.capability)
        assertEquals("health.weekly", Rules.parse("show my health this week")?.capability)
    }
    private val cases = JSONObject(File(System.getProperty("reva.fixtures"), "rules-cases.json").readText()).getJSONArray("cases")

    @Test fun every_sentence_matches_the_python_rules() {
        assertTrue(cases.length() > 60)
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val text = case.getString("text")
            val got = Rules.parse(text)
            if (case.isNull("expected")) {
                assertNull("'${text.take(40)}' should fall through", got)
            } else {
                val want = case.getJSONObject("expected")
                assertNotNull("'${text.take(40)}' should match", got)
                assertEquals(text.take(40), want.getString("capability"), got!!.capability)
                assertEquals(text.take(40), Json.toMap(want.getJSONObject("args")), got.args)
            }
        }
    }

    @Test fun refusal_sentences_equal_the_python_templates() {
        val refusals = JSONObject(File(System.getProperty("reva.fixtures"), "rules-cases.json").readText()).getJSONArray("refusals")
        assertTrue(refusals.length() > 50)
        for (i in 0 until refusals.length()) {
            val row = refusals.getJSONObject(i)
            assertEquals(
                "${row.getString("reason")} ${row.getString("capability")}",
                row.getString("text"),
                Outcomes.refusalText(row.getString("reason"), row.getString("capability")),
            )
        }
    }

    @Test fun refusals_are_matched_before_anything_else() {
        for (text in listOf("pay my rent", "transfer 50 dollars to sam", "log into my bank", "run a command")) {
            val hit = Rules.parse(text)!!
            assertTrue(text, hit.capability.startsWith("finance.") || hit.capability.startsWith("shell."))
        }
    }

    @Test fun a_hit_never_carries_success_text_only_a_capability_and_arguments() {
        val hit = Rules.parse("remember that the wifi code is 4471")!!
        assertEquals("memory.remember", hit.capability)
        assertEquals(mapOf("content" to "the wifi code is 4471"), hit.args)
    }
}
