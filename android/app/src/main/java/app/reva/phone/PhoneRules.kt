package app.reva.phone

import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** A request for something this phone itself can do: capability, arguments that fit the registry, and wording. */
data class PhoneIntent(
    val capability: String,
    val args: Map<String, Any?>,
    /** Short name for what was asked ("Alarm 07:30"). */
    val label: String,
    /** The one sentence on the confirm card (T2) or in the reply (T1), written before anything runs. */
    val summary: String,
)

sealed interface PhoneParse {
    data class Action(val intent: PhoneIntent) : PhoneParse

    /** The sentence is for the phone but cannot be acted on yet; ask, never guess. */
    data class Ask(val question: String) : PhoneParse
}

/** A time the owner said. [Ambiguous] is "7:30" with no AM/PM and no 24-hour form: REVA asks. */
sealed interface SaidTime {
    data class Exact(val time: LocalTime) : SaidTime
    data object Ambiguous : SaidTime
    data object None : SaidTime
}

/**
 * The phone's own commands: open an approved app, set an alarm, set a reminder, add a calendar event, share text.
 * A rule only proposes (capability + arguments + the sentence to show). It never decides and never says anything
 * happened. Times must be unambiguous (AM/PM or 24-hour); "7:30" alone is asked about, not guessed.
 */
object PhoneRules {
    private fun re(pattern: String) = Regex("(?iU)$pattern")

    private val open = re("^(?:please\\s+)?(?:open|launch|start)\\s+(.+)$")
    private val alarm = re("^(?:please\\s+)?(?:(?:set|make|create)\\s+(?:me\\s+)?(?:an?\\s+)?alarm|wake me(?: up)?)\\s+(?:for|at)\\s+(.+)$")
    private val remind = re("^(?:please\\s+)?remind me\\s+(.+)$")
    private val calendarA = re("^(?:please\\s+)?(?:add|put|schedule|create)\\s+(.+?)\\s+(?:to|on|in)\\s+my\\s+calendar\\b(.*)$")
    private val calendarB = re("^(?:please\\s+)?schedule\\s+(.+?)\\s+((?:today|tomorrow)\\b.*|at\\s+.+)$")
    private val share = re("^(?:please\\s+)?share(?:\\s+(?:this\\s+|the following\\s+)?(?:text\\s+|message\\s+)?(.+))?$")

    private const val CLOCK = "(?:noon|midnight|\\d{1,2}(?:\\s*[:.]\\s*\\d{2}|\\s+\\d{2})?\\s*(?:a\\.?m\\.?|p\\.?m\\.?)?)"
    private val timeExpr = re("\\b(?:at|by|for)\\s+($CLOCK)\\b")
    private val dayWord = re("\\b(today|tomorrow)\\b")

    private val timeText = DateTimeFormatter.ofPattern("h:mm a")
    private val dayText = DateTimeFormatter.ofPattern("EEEE d MMM")

    /** Result of reading a sentence for the phone: an action, a question, or null (not a phone command). */
    fun parse(text: String, now: Instant, zone: ZoneId): PhoneParse? {
        val cleaned = text.trim().trim { it in ".!?," }.replace(Regex("(?U)\\s+"), " ").trim()
        if (cleaned.isEmpty()) return null
        alarm.matchEntire(cleaned)?.let { return alarmFor(it.groupValues[1]) }
        remind.matchEntire(cleaned)?.let { return remindFor(it.groupValues[1], now, zone) }
        calendarA.matchEntire(cleaned)?.let { return calendarFor(it.groupValues[1], it.groupValues[2], now, zone) }
        calendarB.matchEntire(cleaned)?.let { return calendarFor(it.groupValues[1], it.groupValues[2], now, zone) }
        share.matchEntire(cleaned)?.let { return shareFor(it.groupValues[1]) }
        open.matchEntire(cleaned)?.let { return openFor(it.groupValues[1]) }
        return null
    }

    // ------------------------------------------------------------------ times

    /** "7:30 pm", "7 pm", "19:30", "07:30", "noon". Without AM/PM only a 24-hour reading is accepted. */
    fun readTime(text: String): SaidTime {
        val said = text.trim().lowercase()
        if (said == "noon") return SaidTime.Exact(LocalTime.NOON)
        if (said == "midnight") return SaidTime.Exact(LocalTime.MIDNIGHT)
        val m = Regex("^(\\d{1,2})(?:\\s*[:.]\\s*(\\d{2})|\\s+(\\d{2}))?\\s*(a\\.?m\\.?|p\\.?m\\.?)?$").matchEntire(said) ?: return SaidTime.None
        val hourText = m.groupValues[1]
        val hour = hourText.toInt()
        val minuteText = m.groupValues[2].ifEmpty { m.groupValues[3] }
        val minute = if (minuteText.isEmpty()) 0 else minuteText.toInt()
        val meridiem = m.groupValues[4].firstOrNull()?.lowercaseChar()
        if (minute > 59) return SaidTime.None
        if (meridiem != null) {
            if (hour !in 1..12) return SaidTime.None
            val h24 = when {
                meridiem == 'a' -> if (hour == 12) 0 else hour
                else -> if (hour == 12) 12 else hour + 12
            }
            return SaidTime.Exact(LocalTime.of(h24, minute))
        }
        if (minuteText.isEmpty()) return SaidTime.Ambiguous // a bare "7"
        if (hour > 23) return SaidTime.None // "25:00" is not a time at all, not merely unclear
        val twentyFour = hour >= 13 || hour == 0 || hourText.length == 2 && hourText.startsWith("0")
        return if (twentyFour) SaidTime.Exact(LocalTime.of(hour, minute)) else SaidTime.Ambiguous
    }

    private fun askAmPm(said: String) = PhoneParse.Ask("Did you mean ${said.trim()} AM or PM? Say the time with AM or PM.")

    // ------------------------------------------------------------------ the commands

    private fun alarmFor(timeText: String): PhoneParse {
        return when (val t = readTime(timeText)) {
            is SaidTime.Exact -> {
                val hhmm = "%02d:%02d".format(t.time.hour, t.time.minute)
                PhoneParse.Action(
                    PhoneIntent(
                        "android.alarm.set",
                        mapOf("time" to hhmm),
                        "Alarm $hhmm",
                        "Open the Clock app with an alarm for ${t.time.format(this.timeText)} ready?",
                    ),
                )
            }
            SaidTime.Ambiguous -> askAmPm(timeText)
            SaidTime.None -> PhoneParse.Ask("I didn't understand that time. Say it like 7:30 AM or 19:30.")
        }
    }

    private data class WhenSaid(val time: SaidTime, val day: String?)

    private fun readWhen(rest: String): WhenSaid {
        val time = timeExpr.find(rest)?.let { readTime(it.groupValues[1]) } ?: SaidTime.None
        return WhenSaid(time, dayWord.find(rest)?.groupValues?.get(1)?.lowercase())
    }

    private fun resolveDate(said: WhenSaid, time: LocalTime, now: Instant, zone: ZoneId): ZonedDateTime {
        val today: LocalDate = now.atZone(zone).toLocalDate()
        val base = when (said.day) {
            "tomorrow" -> today.plusDays(1)
            "today" -> today
            else -> if (ZonedDateTime.of(today, time, zone).toInstant().isAfter(now)) today else today.plusDays(1)
        }
        return ZonedDateTime.of(base, time, zone)
    }

    private fun whenWords(at: ZonedDateTime, now: Instant, zone: ZoneId): String {
        val today = now.atZone(zone).toLocalDate()
        val day = when (at.toLocalDate()) {
            today -> "today"
            today.plusDays(1) -> "tomorrow"
            else -> at.format(dayText)
        }
        return "$day at ${at.format(timeText)}"
    }

    private fun remindFor(rest: String, now: Instant, zone: ZoneId): PhoneParse {
        val said = readWhen(rest)
        val time = when (val t = said.time) {
            is SaidTime.Exact -> t.time
            SaidTime.Ambiguous -> return askAmPm(timeExpr.find(rest)!!.groupValues[1])
            SaidTime.None -> return PhoneParse.Ask("When should I remind you? Say a time, like at 7:30 PM.")
        }
        var what = rest
        what = timeExpr.replace(what, " ")
        what = dayWord.replace(what, " ")
        what = what.replace(Regex("(?iU)^\\s*to\\s+"), "").replace(Regex("(?iU)\\s+to\\s*$"), "")
        what = what.replace(Regex("(?U)\\s+"), " ").trim().trim { it in ".!?," }
        if (what.isEmpty()) return PhoneParse.Ask("What should I remind you about?")
        val at = resolveDate(said, time, now, zone)
        val due = at.toOffsetDateTime().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
        return PhoneParse.Action(
            PhoneIntent(
                "android.reminder.set",
                mapOf("text" to what.take(200), "due" to due),
                "Reminder",
                "Open Calendar with a reminder \"${what.take(60)}\" ${whenWords(at, now, zone)} ready?",
            ),
        )
    }

    private fun calendarFor(title: String, rest: String, now: Instant, zone: ZoneId): PhoneParse {
        val said = readWhen(rest)
        val time = when (val t = said.time) {
            is SaidTime.Exact -> t.time
            SaidTime.Ambiguous -> return askAmPm(timeExpr.find(rest)!!.groupValues[1])
            SaidTime.None -> return PhoneParse.Ask("What time is it? Say a time, like at 3 PM.")
        }
        val name = title.trim().trim { it in ".!?," }.take(200)
        if (name.isEmpty()) return PhoneParse.Ask("What should I call it?")
        val start = resolveDate(said, time, now, zone)
        val end = start.plusHours(1)
        val f = DateTimeFormatter.ISO_OFFSET_DATE_TIME
        return PhoneParse.Action(
            PhoneIntent(
                "android.calendar.insert",
                mapOf("title" to name, "start" to start.toOffsetDateTime().format(f), "end" to end.toOffsetDateTime().format(f)),
                "Calendar",
                "Open Calendar with \"${name.take(60)}\" ${whenWords(start, now, zone)} ready?",
            ),
        )
    }

    private fun shareFor(text: String): PhoneParse {
        val body = text.trim().take(2000)
        if (body.isEmpty()) return PhoneParse.Ask("What should I share?")
        return PhoneParse.Action(
            PhoneIntent("android.share", mapOf("text" to body), "Share", "Open the share sheet with \"${body.take(60)}\"?"),
        )
    }

    private fun openFor(app: String): PhoneParse {
        val phrase = app.trim().trim { it in ".!?," }
        return PhoneParse.Action(
            PhoneIntent("android.app.open", mapOf("package_alias" to phrase.take(100)), "Open $phrase", "Opening $phrase."),
        )
    }
}
