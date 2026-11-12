package app.reva.data

import org.junit.Assert.assertEquals
import org.junit.Test

class DailyFinanceTest {
    @Test fun parses_exact_per_currency_cashflow_and_category_spend() {
        val cashflow = Json.dailyCashflow("""[{"currency":"USD","income_minor":12000,"expense_minor":3499,"net_minor":8501,"from":"2026-10-16","to":"2026-10-16"}]""")
        val spending = Json.dailySpending("""[{"category_id":"food","category":"Food","currency":"USD","spent_minor":3499,"transactions":2}]""")

        assertEquals(DailyCashflow("USD", 12000, 3499, 8501), cashflow.single())
        assertEquals(DailySpendCategory("food", "Food", "USD", 3499, 2), spending.single())
    }

    @Test fun separate_currencies_are_never_summed_together() {
        val rows = Json.dailyCashflow("""[{"currency":"EUR","income_minor":0,"expense_minor":100,"net_minor":-100},{"currency":"USD","income_minor":0,"expense_minor":200,"net_minor":-200}]""")

        assertEquals(listOf("EUR", "USD"), rows.map { it.currency })
        assertEquals(listOf(-100L, -200L), rows.map { it.netMinor })
    }
}
