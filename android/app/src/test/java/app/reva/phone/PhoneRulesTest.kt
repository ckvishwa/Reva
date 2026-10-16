package app.reva.phone

import java.time.Instant
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private val NOW = Instant.parse("2026-10-15T12:00:00Z") // Thursday, local noon at UTC
private val ZONE = ZoneOffset.UTC

private fun action(text: String): PhoneIntent =
    (PhoneRules.parse(text, NOW, ZONE) as PhoneParse.Action).intent

private fun ask(text: String): String =
    (PhoneRules.parse(text, NOW, ZONE) as PhoneParse.Ask).question

class PhoneRulesTimeTest {
    @Test fun the_am_pm_and_24_hour_spellings_all_read() {
        for ((text, expect) in listOf(
            "7:30 am" to "07:30", "7:30 pm" to "19:30", "7 am" to "07:00", "12 am" to "00:00",
            "12 pm" to "12:00", "noon" to "12:00", "midnight" to "00:00", "19:30" to "19:30",
            "07:30" to "07:30", "7.30pm" to "19:30", "7 30 pm" to "19:30",
        )) {
            val time = PhoneRules.readTime(text)
            assertTrue(text, time is SaidTime.Exact)
            val t = (time as SaidTime.Exact).time
            assertEquals(text, expect, "%02d:%02d".format(t.hour, t.minute))
        }
    }

    @Test fun a_bare_hour_with_no_am_pm_or_24_hour_form_is_ambiguous() {
        for (text in listOf("7", "7:30", "9")) {
            assertEquals(text, SaidTime.Ambiguous, PhoneRules.readTime(text))
        }
    }

    @Test fun garbage_is_not_a_time() {
        for (text in listOf("", "soon", "25:00", "7:99", "13 pm", "0 pm")) {
            assertEquals(text, SaidTime.None, PhoneRules.readTime(text))
        }
    }
}

class PhoneRulesAlarmTest {
    @Test fun an_unambiguous_time_proposes_an_alarm() {
        val intent = action("set an alarm for 7:30 am")
        assertEquals("android.alarm.set", intent.capability)
        assertEquals(mapOf("time" to "07:30"), intent.args)
        assertTrue(intent.summary.contains("7:30 AM"))
    }

    @Test fun wake_me_at_is_the_same_rule() {
        assertEquals(mapOf("time" to "06:45"), action("wake me at 6:45 am").args)
    }

    @Test fun an_ambiguous_time_is_asked_about_not_guessed() {
        val question = ask("set an alarm for 7:30")
        assertTrue(question.contains("AM or PM"))
    }

    @Test fun a_time_that_cannot_be_read_is_asked_about() {
        assertTrue(ask("set an alarm for whenever").contains("didn't understand"))
    }
}

class PhoneRulesReminderTest {
    @Test fun a_reminder_carries_the_text_and_an_iso_due_time() {
        val intent = action("remind me to call mom at 5 pm")
        assertEquals("android.reminder.set", intent.capability)
        assertEquals("call mom", intent.args["text"])
        assertEquals("2026-10-15T17:00:00Z", intent.args["due"])
    }

    @Test fun today_already_passed_rolls_to_tomorrow_and_tomorrow_is_explicit() {
        val past = action("remind me to call mom at 9 am") // before NOW (noon)
        assertEquals("2026-10-16T09:00:00Z", past.args["due"])
        val explicit = action("remind me to call mom tomorrow at 9 am")
        assertEquals("2026-10-16T09:00:00Z", explicit.args["due"])
        val todayLater = action("remind me to call mom today at 6 pm")
        assertEquals("2026-10-15T18:00:00Z", todayLater.args["due"])
    }

    @Test fun no_time_is_asked_about() {
        assertTrue(ask("remind me to call mom").contains("time"))
    }

    @Test fun no_content_is_asked_about() {
        assertTrue(ask("remind me at 5 pm").contains("about"))
    }
}

class PhoneRulesCalendarTest {
    @Test fun add_x_to_my_calendar_with_a_day_and_time() {
        val intent = action("add team sync to my calendar tomorrow at 3 pm")
        assertEquals("android.calendar.insert", intent.capability)
        assertEquals("team sync", intent.args["title"])
        assertEquals("2026-10-16T15:00:00Z", intent.args["start"])
        assertEquals("2026-10-16T16:00:00Z", intent.args["end"])
    }

    @Test fun schedule_x_at_y_is_the_same_rule() {
        val intent = action("schedule dentist today at 2 pm")
        assertEquals("dentist", intent.args["title"])
        assertEquals("2026-10-15T14:00:00Z", intent.args["start"])
    }

    @Test fun an_ambiguous_calendar_time_is_asked_about() {
        assertTrue(ask("add team sync to my calendar at 3").contains("AM or PM"))
    }
}

class PhoneRulesShareAndOpenTest {
    @Test fun share_carries_the_text() {
        assertEquals(mapOf("text" to "look at this"), action("share look at this").args)
    }

    @Test fun empty_share_is_asked_about() {
        assertTrue(ask("share").contains("share"))
    }

    @Test fun open_carries_the_raw_phrase_for_the_resolver_to_judge() {
        val intent = action("open spotify")
        assertEquals("android.app.open", intent.capability)
        assertEquals("spotify", intent.args["package_alias"])
    }

    @Test fun unrelated_sentences_are_not_phone_commands() {
        for (text in listOf("what's the weather", "how much did I spend", "", "   ", "tell me a joke")) {
            assertNull(text, PhoneRules.parse(text, NOW, ZONE))
        }
    }
}
