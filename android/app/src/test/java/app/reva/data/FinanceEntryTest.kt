package app.reva.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FinanceEntryTest {
    @Test fun budget_requires_existing_expense_category_and_exact_minor_amount() {
        val categories = listOf(Category("food", "Food", "expense", emptyList()))
        val good = FinanceEntry.budget("food", "USD", "125.25", "2026-10", categories)
        assertEquals(NewBudget("food", "USD", 12525, "2026-10"), (good as EntryResult.Ok).value)
        assertTrue(FinanceEntry.budget("unknown", "USD", "125.25", "2026-10", categories) is EntryResult.Invalid)
        assertTrue(FinanceEntry.budget("food", "USD", "125.251", "2026-10", categories) is EntryResult.Invalid)
    }

    @Test fun bill_requires_valid_date_currency_and_reviewed_recurrence() {
        val good = FinanceEntry.bill("Rent", "950.00", "USD", "2026-11-01", "monthly")
        assertEquals(NewBill("Rent", 95000, "USD", "2026-11-01", "monthly"), (good as EntryResult.Ok).value)
        assertTrue(FinanceEntry.bill("Rent", "950", "USD", "2026-02-30", "monthly") is EntryResult.Invalid)
        assertTrue(FinanceEntry.bill("Rent", "950", "USD", "2026-11-01", "daily") is EntryResult.Invalid)
    }
}
