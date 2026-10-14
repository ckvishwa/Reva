package app.reva.core

import app.reva.data.Bill
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MoneyTest {
    @Test fun formats_with_symbol_commas_and_sign() {
        assertEquals("$1,234.56", Money.format(123_456, "USD"))
        assertEquals("-$12.00", Money.format(-1_200, "USD"))
        assertEquals("+$3,000.00", Money.format(300_000, "USD", showPlus = true))
        assertEquals("$0.05", Money.format(5, "USD"))
        assertEquals("€10.00", Money.format(1_000, "EUR"))
        assertEquals("CHF 1.50", Money.format(150, "CHF"))
    }

    @Test fun formats_currencies_without_two_decimals() {
        assertEquals("¥1,500", Money.format(1_500, "JPY"))
        assertEquals("KWD 1.234", Money.format(1_234, "KWD"))
    }

    @Test fun formats_the_extreme_values_without_overflow() {
        assertEquals("-$92,233,720,368,547,758.08", Money.format(Long.MIN_VALUE, "USD"))
        assertEquals("$92,233,720,368,547,758.07", Money.format(Long.MAX_VALUE, "USD"))
    }

    private fun ok(text: String, currency: String = "USD") = (Money.parse(text, currency) as Money.Parsed.Ok).minor

    private fun error(text: String?, currency: String = "USD") = (Money.parse(text, currency) as Money.Parsed.Error).message

    @Test fun parses_what_people_type() {
        assertEquals(1_200L, ok("12"))
        assertEquals(1_250L, ok("12.5"))
        assertEquals(-1_250L, ok("-12.50"))
        assertEquals(123_450L, ok("$1,234.50"))
        assertEquals(-500L, ok("(5.00)"))
        assertEquals(0L, ok("0"))
        assertEquals(1_500L, ok("1500", "JPY"))
        assertEquals(1_234L, ok("1.234", "KWD"))
    }

    @Test fun refuses_rather_than_rounds() {
        assertEquals("At most 2 decimal places for USD.", error("1.234"))
        assertEquals("JPY has no decimal places.", error("1.5", "JPY"))
        assertEquals("Use a point for decimals, for example 12.50.", error("12,50"))
        assertEquals("That is not a valid amount.", error("abc"))
        assertEquals("That is not a valid amount.", error("1.2.3"))
        assertEquals("Enter an amount.", error("  "))
        assertEquals("Enter an amount.", error(null))
        assertEquals("That amount is too large.", error("99999999999999999"))
        assertEquals(1_200L, ok("12.000")) // trailing zeros are not rounding
    }
}

class DisplayTest {
    private val today = LocalDate.of(2026, 10, 12)

    @Test fun relative_dates() {
        assertEquals("Today", Display.relativeDate("2026-10-12", today))
        assertEquals("Yesterday", Display.relativeDate("2026-10-11", today))
        assertEquals("Oct 1", Display.relativeDate("2026-10-01", today))
        assertEquals("Dec 31, 2025", Display.relativeDate("2025-12-31", today))
        assertEquals("not a date", Display.relativeDate("not a date", today))
    }

    private fun bill(kind: String, overdue: Boolean) = Bill("b", "x", kind, 1, "USD", "2026-10-14", 2, overdue)

    @Test fun due_text_depends_on_kind() {
        assertEquals("Due Oct 14", Display.dueText(bill("bill", false), today))
        assertEquals("Renews Oct 14", Display.dueText(bill("subscription", false), today))
        assertEquals("Expected Oct 14", Display.dueText(bill("income", false), today))
        assertEquals("Overdue since Oct 14", Display.dueText(bill("bill", true), today))
        assertEquals("Expected Oct 14", Display.dueText(bill("income", true), today))
    }

    @Test fun source_column_text() {
        assertEquals("manual", Display.sourceText(null))
        assertEquals("manual", Display.sourceText("manual"))
        assertEquals("voice · confirmed", Display.sourceText("voice"))
        assertEquals("csv import", Display.sourceText("csv"))
        assertEquals("ofx import", Display.sourceText("ofx"))
        assertEquals("restored from export", Display.sourceText("json"))
        assertEquals("phone · synced", Display.sourceText("phone"))
    }

    @Test fun budget_bar_rules() {
        assertEquals(0f, Display.barFraction(-5), 0f)
        assertEquals(0.9f, Display.barFraction(9_000), 0.0001f)
        assertEquals(1f, Display.barFraction(25_000), 0f)
        assertFalse(Display.isNearLimit(9_000))
        assertTrue(Display.isNearLimit(9_001))
        assertEquals(94, Display.percent(9_450))
    }
}

class CsvSnifferTest {
    private fun probe(text: String) = CsvSniffer.probe(text.toByteArray())!!

    @Test fun detects_delimiters() {
        assertEquals(",", probe("a,b,c\n1,2,3\n").delimiter)
        assertEquals(";", probe("a;b;c\n1;2;3\n").delimiter)
        assertEquals("\t", probe("a\tb\tc\n1\t2\t3\n").delimiter)
        assertEquals("|", probe("a|b|c\n1|2|3\n").delimiter)
    }

    @Test fun quoted_commas_do_not_confuse_columns() {
        val p = probe("Date,\"Memo, long\",Amount\n2026-10-01,\"Hi, there\",-1.00\n")
        assertEquals(listOf("Date", "Memo, long", "Amount"), p.headers)
        assertEquals(listOf("2026-10-01", "Hi, there", "-1.00"), p.sampleRows[0])
    }

    @Test fun bom_is_ignored_and_latin1_still_reads() {
        val bom = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte()) + "Date,Memo\n2026-10-01,Cafe\n".toByteArray()
        assertEquals("Date", CsvSniffer.probe(bom)!!.headers[0])
        val latin1 = byteArrayOf(0x44, 0x61, 0x74, 0x65, 0x2C, 0x4D, 0x0A, 0x31, 0x2C, 0x43, 0x61, 0x66, 0xE9.toByte(), 0x0A)
        assertEquals("Café", CsvSniffer.probe(latin1)!!.sampleRows[0][1])
    }

    @Test fun text_that_is_not_a_table_gives_no_probe() {
        assertNull(CsvSniffer.probe("just one column of text\nsecond line\n".toByteArray()))
        assertNull(CsvSniffer.probe(ByteArray(0)))
    }

    @Test fun guesses_columns_and_date_format_from_a_bank_header() {
        val g = CsvSniffer.guess(probe("Date,Description,Debit,Credit,Category\n05/10/2026,COFFEE,4.50,,Dining\n13/10/2026,PAY,,15.00,Income\n"))
        assertEquals("Date", g.date)
        assertEquals("Description", g.description)
        assertEquals("Debit", g.debit)
        assertEquals("Credit", g.credit)
        assertNull(g.amount)
        assertEquals("%d/%m/%Y", g.dateFormat) // 13/10/2026 can only be day-first
        assertFalse(g.dateFormatIsAmbiguous)
    }

    @Test fun ambiguous_dates_are_flagged_and_amount_wins_over_split_columns() {
        val g = CsvSniffer.guess(probe("Date,Memo,Amount\n05/10/2026,x,-1.00\n06/11/2026,y,-2.00\n"))
        assertTrue(g.dateFormatIsAmbiguous)
        assertEquals("%d/%m/%Y", g.dateFormat)
        assertEquals("Amount", g.amount)
        assertNull(g.debit)
    }

    @Test fun picks_posted_date_and_comma_decimals() {
        val g = CsvSniffer.guess(probe("Transaction Date;Posted Date;Details;Money out;Money in\n01.10.2026;02.10.2026;Shop;3,00;\n"))
        assertEquals("Posted Date", g.date)
        assertEquals("Details", g.description)
        assertEquals("Money out", g.debit)
        assertEquals("%d.%m.%Y", g.dateFormat)
        assertEquals(",", g.decimalSeparator)
    }
}
