package app.reva.data

import app.reva.core.Money
import java.time.LocalDate
import java.time.YearMonth
import java.util.Currency

data class NewBudget(val categoryId: String, val currency: String, val amountMinor: Long, val startMonth: String)
data class NewBill(val name: String, val amountMinor: Long, val currency: String, val dueDate: String, val recurrence: String)

sealed interface EntryResult<out T> {
    data class Ok<T>(val value: T) : EntryResult<T>
    data class Invalid(val message: String) : EntryResult<Nothing>
}

/** UI validation before the Kernel's independent command validation. Values are never rounded or guessed. */
object FinanceEntry {
    private val recurrences = setOf("once", "weekly", "biweekly", "monthly", "quarterly", "yearly")

    private fun currency(code: String): Boolean = code.length == 3 && code.all { it in 'A'..'Z' } &&
        runCatching { Currency.getInstance(code) }.isSuccess

    private fun positiveAmount(input: String, code: String): Long? =
        (Money.parse(input, code) as? Money.Parsed.Ok)?.minor?.takeIf { it > 0 }

    fun budget(categoryId: String, currency: String, amount: String, month: String, categories: List<Category>): EntryResult<NewBudget> {
        if (categories.none { it.id == categoryId && it.kind == "expense" }) return EntryResult.Invalid("Choose an expense category.")
        if (!currency(currency)) return EntryResult.Invalid("Choose a valid currency.")
        val minor = positiveAmount(amount, currency) ?: return EntryResult.Invalid("Enter a positive exact amount.")
        val parsed = runCatching { YearMonth.parse(month) }.getOrNull() ?: return EntryResult.Invalid("Enter a valid YYYY-MM month.")
        return EntryResult.Ok(NewBudget(categoryId, currency, minor, parsed.toString()))
    }

    fun bill(name: String, amount: String, currency: String, dueDate: String, recurrence: String): EntryResult<NewBill> {
        val clean = name.trim()
        if (clean.isEmpty() || clean.length > 200) return EntryResult.Invalid("Enter a bill name (up to 200 characters).")
        if (!currency(currency)) return EntryResult.Invalid("Choose a valid currency.")
        val minor = positiveAmount(amount, currency) ?: return EntryResult.Invalid("Enter a positive exact amount.")
        val date = runCatching { LocalDate.parse(dueDate) }.getOrNull() ?: return EntryResult.Invalid("Enter a valid YYYY-MM-DD due date.")
        if (recurrence !in recurrences) return EntryResult.Invalid("Choose a supported recurrence.")
        return EntryResult.Ok(NewBill(clean, minor, currency, date.toString(), recurrence))
    }
}
