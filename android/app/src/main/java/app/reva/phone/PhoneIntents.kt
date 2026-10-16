package app.reva.phone

import java.time.OffsetDateTime

/**
 * An Android intent described as plain data, so every request the phone hands to another app can be checked on
 * the JVM exactly as it will be sent. [AndroidIntentPort] turns one into a real `Intent`. Only public, documented
 * intents are built here: no accessibility service, no package list, no privileged setting.
 */
data class IntentSpec(
    val action: String,
    val data: String? = null,
    val type: String? = null,
    val extras: Map<String, Any?> = emptyMap(),
    /** Set for "open this app": the launcher intent of exactly this package. */
    val launchPackage: String? = null,
    /** Wrap in the system chooser with this title (sharing). */
    val chooserTitle: String? = null,
)

object PhoneIntents {
    // android.provider.AlarmClock
    const val ACTION_SET_ALARM = "android.intent.action.SET_ALARM"
    const val EXTRA_HOUR = "android.intent.extra.alarm.HOUR"
    const val EXTRA_MINUTES = "android.intent.extra.alarm.MINUTES"
    const val EXTRA_MESSAGE = "android.intent.extra.alarm.MESSAGE"
    const val EXTRA_SKIP_UI = "android.intent.extra.alarm.SKIP_UI"

    // android.provider.CalendarContract
    const val ACTION_INSERT = "android.intent.action.INSERT"
    const val CALENDAR_EVENTS = "content://com.android.calendar/events"
    const val EXTRA_TITLE = "title"
    const val EXTRA_BEGIN = "beginTime"
    const val EXTRA_END = "endTime"
    const val EXTRA_LOCATION = "eventLocation"
    const val EXTRA_HAS_ALARM = "hasAlarm"

    // android.content.Intent
    const val ACTION_SEND = "android.intent.action.SEND"
    const val EXTRA_TEXT = "android.intent.extra.TEXT"
    const val ACTION_MAIN = "android.intent.action.MAIN"

    /**
     * The Clock app's alarm screen with the time filled in. `SKIP_UI` is explicitly false: the alarm is created
     * only when the owner taps Save in the Clock app, which is why REVA never says an alarm "was set".
     */
    fun alarm(hour: Int, minute: Int, label: String?): IntentSpec {
        require(hour in 0..23 && minute in 0..59) { "not a time" }
        val extras = linkedMapOf<String, Any?>(EXTRA_HOUR to hour, EXTRA_MINUTES to minute, EXTRA_SKIP_UI to false)
        if (!label.isNullOrBlank()) extras[EXTRA_MESSAGE] = label.take(100)
        return IntentSpec(ACTION_SET_ALARM, extras = extras)
    }

    /** The Calendar app's new-event screen, filled in. Saved only when the owner taps Save there. */
    fun calendarEvent(title: String, start: OffsetDateTime, end: OffsetDateTime, location: String?, withAlarm: Boolean): IntentSpec {
        require(!end.isBefore(start)) { "an event cannot end before it starts" }
        val extras = linkedMapOf<String, Any?>(
            EXTRA_TITLE to title.take(200),
            EXTRA_BEGIN to start.toInstant().toEpochMilli(),
            EXTRA_END to end.toInstant().toEpochMilli(),
        )
        if (!location.isNullOrBlank()) extras[EXTRA_LOCATION] = location.take(200)
        if (withAlarm) extras[EXTRA_HAS_ALARM] = true
        return IntentSpec(ACTION_INSERT, data = CALENDAR_EVENTS, extras = extras)
    }

    /** The system share sheet with plain text. The owner picks where it goes. */
    fun share(text: String): IntentSpec =
        IntentSpec(ACTION_SEND, type = "text/plain", extras = mapOf(EXTRA_TEXT to text.take(2000)), chooserTitle = "Share with")

    /** The launcher screen of one specific app. */
    fun open(packageName: String): IntentSpec {
        require(PACKAGE.matches(packageName)) { "not a package name" }
        return IntentSpec(ACTION_MAIN, launchPackage = packageName)
    }

    private val PACKAGE = Regex("^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+$")
}
