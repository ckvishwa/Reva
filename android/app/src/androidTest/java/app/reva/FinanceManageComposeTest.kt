package app.reva

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.Samples
import app.reva.ui.finance.FinanceManageForm
import app.reva.ui.theme.RevaTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class FinanceManageComposeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun recording_bill_as_paid_requires_a_second_explicit_confirmation() {
        val repo = FakeFinanceRepository().apply { bills += Samples.bill("Rent", "2026-10-20", 4) }
        rule.setContent { RevaTheme { FinanceManageForm(repo) } }
        rule.waitUntil(5_000) { repo.calls.contains("bills") }
        rule.onNodeWithTag("finance_bill_paid_${repo.bills.single().id}").performScrollTo().performClick()
        assertEquals(0, repo.paidBills.size)
        rule.onNodeWithText("Confirm record as paid").performClick()
        rule.waitUntil(5_000) { repo.paidBills.size == 1 }
    }
}
