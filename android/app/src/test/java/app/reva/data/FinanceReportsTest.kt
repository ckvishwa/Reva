package app.reva.data

import app.reva.ui.more.availableSections
import app.reva.ui.more.comingSoon
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FinanceReportsTest {
    @Test fun recurring_summary_keeps_each_currency_separate_with_exact_minor_units() {
        val rows = FinanceReportsJson.recurring(
            """[{"currency":"EUR","yearly_outgoing_minor":15588,"yearly_income_minor":0,"yearly_net_minor":-15588,"due_soon_outgoing_minor":1299,"due_soon_income_minor":0,"due_until":"2026-11-18","as_of":"2026-10-19","items":[{}]},
               {"currency":"USD","yearly_outgoing_minor":1542988,"yearly_income_minor":7800000,"yearly_net_minor":6257012,"due_soon_outgoing_minor":121249,"due_soon_income_minor":300000,"due_until":"2026-11-18","as_of":"2026-10-19","items":[{},{},{},{},{},{}]}]""",
        )
        assertEquals(listOf("EUR", "USD"), rows.map { it.currency })
        val usd = rows[1]
        assertEquals(1_542_988L, usd.yearlyOutgoingMinor)
        assertEquals(usd.yearlyIncomeMinor - usd.yearlyOutgoingMinor, usd.yearlyNetMinor)
        assertEquals(6, usd.itemCount)
    }

    @Test fun networth_report_has_live_totals_and_a_null_change_for_the_first_snapshot() {
        val report = FinanceReportsJson.netWorth(
            """[{"as_of":"2026-10-19","current":{"USD":{"assets_minor":528001,"liabilities_minor":22001,"net_minor":506000}},
                "history":[{"id":"a","as_of":"2026-10-02","by_currency":{"USD":{"net_minor":510000,"change_minor":null}}},
                           {"id":"b","as_of":"2026-10-07","by_currency":{"USD":{"net_minor":506000,"change_minor":-4000}}}]}]""",
        )
        assertEquals(506_000L, report.current.getValue("USD").netMinor)
        assertNull(report.history[0].byCurrency.getValue("USD").second)
        assertEquals(-4_000L, report.history[1].byCurrency.getValue("USD").second)
    }

    @Test fun more_lists_health_as_built_not_coming_soon() {
        assertTrue("Health" in availableSections)
        assertFalse("Health" in comingSoon)
        assertFalse("Finance" in comingSoon)
    }
}
