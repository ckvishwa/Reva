package app.reva.phone

import java.time.OffsetDateTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class PhoneIntentsTest {
    @Test fun an_alarm_is_never_set_without_ui_skip_ui_is_false() {
        val spec = PhoneIntents.alarm(7, 30, "wake up")
        assertEquals(PhoneIntents.ACTION_SET_ALARM, spec.action)
        assertEquals(7, spec.extras[PhoneIntents.EXTRA_HOUR])
        assertEquals(30, spec.extras[PhoneIntents.EXTRA_MINUTES])
        assertEquals("wake up", spec.extras[PhoneIntents.EXTRA_MESSAGE])
        assertEquals(false, spec.extras[PhoneIntents.EXTRA_SKIP_UI])
    }

    @Test fun an_alarm_with_no_label_sends_no_message_extra() {
        assertFalse(PhoneIntents.alarm(7, 0, null).extras.containsKey(PhoneIntents.EXTRA_MESSAGE))
        assertFalse(PhoneIntents.alarm(7, 0, "   ").extras.containsKey(PhoneIntents.EXTRA_MESSAGE))
    }

    @Test fun an_out_of_range_time_is_refused() {
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.alarm(24, 0, null) }
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.alarm(0, 60, null) }
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.alarm(-1, 0, null) }
    }

    @Test fun a_calendar_event_targets_the_insert_action_and_the_events_table() {
        val start = OffsetDateTime.parse("2026-10-16T15:00:00Z")
        val spec = PhoneIntents.calendarEvent("team sync", start, start.plusHours(1), "Room 2", withAlarm = true)
        assertEquals(PhoneIntents.ACTION_INSERT, spec.action)
        assertEquals(PhoneIntents.CALENDAR_EVENTS, spec.data)
        assertEquals("team sync", spec.extras[PhoneIntents.EXTRA_TITLE])
        assertEquals(start.toInstant().toEpochMilli(), spec.extras[PhoneIntents.EXTRA_BEGIN])
        assertEquals("Room 2", spec.extras[PhoneIntents.EXTRA_LOCATION])
        assertEquals(true, spec.extras[PhoneIntents.EXTRA_HAS_ALARM])
    }

    @Test fun an_event_cannot_end_before_it_starts() {
        val start = OffsetDateTime.parse("2026-10-16T15:00:00Z")
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.calendarEvent("x", start, start.minusMinutes(1), null, false) }
    }

    @Test fun share_wraps_plain_text_with_a_chooser_title() {
        val spec = PhoneIntents.share("look at this")
        assertEquals(PhoneIntents.ACTION_SEND, spec.action)
        assertEquals("text/plain", spec.type)
        assertEquals("look at this", spec.extras[PhoneIntents.EXTRA_TEXT])
        assertEquals("Share with", spec.chooserTitle)
    }

    @Test fun long_text_and_labels_are_bounded() {
        assertEquals(100, (PhoneIntents.alarm(7, 0, "x".repeat(500)).extras[PhoneIntents.EXTRA_MESSAGE] as String).length)
        assertEquals(2000, (PhoneIntents.share("y".repeat(5000)).extras[PhoneIntents.EXTRA_TEXT] as String).length)
    }

    @Test fun open_targets_exactly_one_package_and_refuses_a_non_package_string() {
        assertEquals("app.reva.android", PhoneIntents.open("app.reva.android").launchPackage)
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.open("not a package; rm -rf") }
        assertThrows(IllegalArgumentException::class.java) { PhoneIntents.open("") }
    }
}
