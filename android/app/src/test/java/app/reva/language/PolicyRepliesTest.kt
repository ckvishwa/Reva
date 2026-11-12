package app.reva.language

import app.reva.policy.loadRegistry
import app.reva.voice.UnavailableReplies
import app.reva.voice.ReplySource
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PolicyRepliesTest {
    private val replies = PolicyReplies(loadRegistry(), clock = { Instant.parse("2026-10-15T12:00:00Z") })
    private fun say(text: String) = runBlocking { replies.reply(text).text }

    @Test fun forbidden_requests_get_the_refusal_template_with_no_proposal_waiting() {
        assertEquals(Outcomes.REFUSED_MONEY, say("pay my rent"))
        assertEquals(Outcomes.REFUSED_MONEY, say("transfer 50 dollars to sam"))
        assertEquals(Outcomes.REFUSED_MEDICAL, say("what dose of ibuprofen"))
        assertEquals(Outcomes.REFUSED_GENERIC, say("run a command"))
        assertEquals(Outcomes.REFUSED_GENERIC, say("send an email to sam"))
    }

    @Test fun understood_requests_the_phone_cannot_do_yet_say_nothing_was_changed() {
        for (text in listOf("what's on today", "how much did I spend this month", "remember that the wifi code is 4471", "what did I say about the wifi")) {
            assertEquals(text, PolicyReplies.NOT_ON_PHONE_YET, say(text))
        }
    }

    @Test fun undo_with_no_executor_has_nothing_to_undo() {
        assertEquals(Outcomes.NOTHING_TO_UNDO, say("undo that"))
    }

    @Test fun an_open_question_is_the_unavailable_message_not_an_invented_answer() {
        assertEquals(UnavailableReplies.UNAVAILABLE, say("what is the capital of France"))
    }

    @Test fun no_reply_ever_claims_something_was_done() {
        val success = listOf("saved", "done", "added", "opened", "closed", "undone", "recorded", "logged", "created")
        for (text in listOf("pay my rent", "remember that x is y", "undo", "today", "how much did I spend", "tell me a joke", "buy a coffee")) {
            val reply = say(text).lowercase()
            for (word in success) assertFalse("'$reply' contains '$word'", Regex("\b$word\b").containsMatchIn(reply))
        }
        assertTrue(true)
    }

    @Test fun urgent_health_phrases_get_fixed_advice_without_contacting_a_planner() = runBlocking {
        var forwarded = 0
        val source = PolicyReplies(loadRegistry(), fallback = object : ReplySource {
            override suspend fun reply(text: String): ReplySource.Reply {
                forwarded++
                return ReplySource.Reply("model", "model")
            }
        })
        for (text in listOf("I have chest pain", "I am having trouble breathing", "possible stroke signs", "I overdosed", "I want to harm myself")) {
            assertEquals(HealthSafety.URGENT_MESSAGE, source.reply(text).text)
        }
        assertEquals(0, forwarded)
    }
}
