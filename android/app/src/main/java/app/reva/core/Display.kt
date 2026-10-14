package app.reva.core

import app.reva.data.Bill
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

/** Text the Finance screens show, kept out of the composables so it can be unit tested. */
object Display {
    private val monthDay = DateTimeFormatter.ofPattern("MMM d", Locale.ENGLISH)
    private val monthDayYear = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.ENGLISH)

    fun parseDate(iso: String?): LocalDate? = try {
        if (iso == null) null else LocalDate.parse(iso)
    } catch (_: DateTimeParseException) {
        null
    }

    /** "Today", "Yesterday", otherwise "Oct 11" (with the year when it is not this year). */
    fun relativeDate(iso: String?, today: LocalDate): String {
        val date = parseDate(iso) ?: return iso ?: ""
        return when (date) {
            today -> "Today"
            today.minusDays(1) -> "Yesterday"
            else -> shortDate(iso, today)
        }
    }

    fun shortDate(iso: String?, today: LocalDate): String {
        val date = parseDate(iso) ?: return iso ?: ""
        return if (date.year == today.year) date.format(monthDay) else date.format(monthDayYear)
    }

    /** "Due Oct 14", "Renews Dec 20" (subscriptions), "Overdue since Oct 10", "Expected Nov 1" (income). */
    fun dueText(bill: Bill, today: LocalDate): String {
        val date = shortDate(bill.dueDate, today)
        if (bill.overdue == true && bill.kind != "income") return "Overdue since $date"
        return when (bill.kind) {
            "subscription" -> "Renews $date"
            "income" -> "Expected $date"
            else -> "Due $date"
        }
    }

    /** Where a transaction came from, as the Source line shows it. */
    fun sourceText(sourceKind: String?): String = when (sourceKind) {
        "voice" -> "voice · confirmed"
        "csv" -> "csv import"
        "ofx" -> "ofx import"
        "json" -> "restored from export"
        "import" -> "import"
        "phone" -> "phone · synced"
        else -> "manual"
    }

    fun accountKindLabel(kind: String): String = when (kind) {
        "checking" -> "Checking"
        "savings" -> "Savings"
        "credit" -> "Credit card"
        "cash" -> "Cash"
        "investment" -> "Investment"
        "loan" -> "Loan"
        else -> "Account"
    }

    fun percent(usedBasisPoints: Long): Int = (usedBasisPoints / 100).coerceIn(0, 999).toInt()

    /** The share of the bar to fill, 0 to 1 (a budget over the limit fills the bar). */
    fun barFraction(usedBasisPoints: Long): Float = (usedBasisPoints / 10_000.0).coerceIn(0.0, 1.0).toFloat()

    /** Bars past 90% of the limit turn light orange (design rule). */
    fun isNearLimit(usedBasisPoints: Long): Boolean = usedBasisPoints > 9_000
}
