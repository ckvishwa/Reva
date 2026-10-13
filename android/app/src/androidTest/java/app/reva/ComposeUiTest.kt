package app.reva

import android.content.Context
import androidx.compose.ui.test.assertContentDescriptionContains
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.AndroidKeystoreWrapper
import app.reva.data.KernelFinanceRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.Samples
import app.reva.ui.RevaRoot
import app.reva.ui.finance.AddAccountForm
import app.reva.ui.finance.AddAccountViewModel
import app.reva.ui.finance.AddTransactionForm
import app.reva.ui.finance.AddTransactionViewModel
import app.reva.ui.theme.RevaTheme
import java.io.File
import java.security.KeyStore
import java.time.LocalDate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.openDomain

/** The add-transaction flow, driven the way a person drives it, with a fake repository (fast, deterministic). */
@RunWith(AndroidJUnit4::class)
class AddTransactionComposeTest {
    @get:Rule val rule = createComposeRule()

    private fun formWith(repo: FakeFinanceRepository, onSaved: () -> Unit = {}): AddTransactionViewModel {
        val vm = AddTransactionViewModel.create(repo, repo.balances, repo.categories, LocalDate.of(2026, 10, 12))
        rule.setContent { RevaTheme { AddTransactionForm(vm, onSaved = onSaved, onCancel = {}) } }
        return vm
    }

    @Test fun typing_an_expense_and_saving_records_it_with_the_right_sign() {
        val repo = Samples.populated()
        var saved = false
        formWith(repo) { saved = true }

        rule.onNodeWithTag("tx_amount").performTextInput("12.50")
        rule.onNodeWithTag("tx_description").performTextInput("Smoke lunch")
        rule.onNodeWithTag("tx_preview").assertIsDisplayed()
        rule.onNode(hasTestTag("tx_preview") and hasText("Will record $12.50 spent from Checking on 2026-10-12.")).assertIsDisplayed()
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()

        rule.waitUntil(5_000) { saved }
        val sent = repo.addedTransactions.single()
        assertEquals(-1_250L, sent.amountMinor)
        assertEquals("Smoke lunch", sent.description)
        assertEquals("2026-10-12", sent.date)
        assertEquals("acct-checking", sent.accountId)
    }

    @Test fun money_in_records_a_positive_amount() {
        val repo = Samples.populated()
        var saved = false
        formWith(repo) { saved = true }
        rule.onNodeWithTag("tx_income").performClick()
        rule.onNodeWithTag("tx_amount").performTextInput("100")
        rule.onNodeWithTag("tx_description").performTextInput("Refund")
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()
        rule.waitUntil(5_000) { saved }
        assertEquals(10_000L, repo.addedTransactions.single().amountMinor)
    }

    @Test fun an_empty_form_shows_the_problems_and_saves_nothing() {
        val repo = Samples.populated()
        formWith(repo)
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()
        rule.onNodeWithText("Enter an amount.").assertIsDisplayed()
        rule.onNodeWithText("Enter a description.").assertIsDisplayed()
        assertTrue(repo.addedTransactions.isEmpty())
    }

    @Test fun a_bad_amount_is_explained() {
        val repo = Samples.populated()
        formWith(repo)
        rule.onNodeWithTag("tx_amount").performTextInput("12,50")
        rule.onNodeWithTag("tx_description").performTextInput("x")
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()
        rule.onNodeWithText("Use a point for decimals, for example 12.50.").assertIsDisplayed()
        assertTrue(repo.addedTransactions.isEmpty())
    }

    @Test fun without_an_account_the_form_says_to_add_one() {
        val repo = FakeFinanceRepository()
        formWith(repo)
        rule.onNodeWithText("Add an account first.").assertIsDisplayed()
    }

    @Test fun the_account_form_adds_a_credit_card_as_a_negative_balance() {
        val repo = FakeFinanceRepository()
        var saved = false
        val vm = AddAccountViewModel(repo)
        rule.setContent { RevaTheme { AddAccountForm(vm, onSaved = { saved = true }, onCancel = {}) } }
        rule.onNodeWithTag("acct_name").performTextInput("Visa")
        rule.onNodeWithTag("acct_kind").performClick()
        rule.onNodeWithTag("acct_kind:credit").performClick()
        rule.onNodeWithTag("acct_opening").performTextInput("250.00")
        rule.onNodeWithTag("acct_save").performScrollTo().performClick()
        rule.waitUntil(5_000) { saved }
        assertEquals(-25_000L, repo.addedAccounts.single().openingBalanceMinor)
    }
}

/** The whole app (tabs, sheets) with a fake repository: navigation, the add-transaction sheet and Today. */
@RunWith(AndroidJUnit4::class)
class AppFlowComposeTest {
    @get:Rule val rule = createComposeRule()

    private fun app(repo: FakeFinanceRepository) {
        rule.setContent { RevaTheme { RevaRoot(repo, "0.1.0", onShare = { _, _ -> }) } }
    }

    @Test fun today_shows_budget_left_and_bills() {
        val repo = Samples.populated().apply {
            todaySummary = app.reva.data.TodaySummary(
                "2026-10-12", listOf(app.reva.data.TodayBudgetLeft("USD", 70_000, 16_350, 53_650)),
                listOf(Samples.bill("Rent", "2026-10-14", 2)),
            )
        }
        app(repo)
        // The card is one merged node for a screen reader; the tagged texts are in the unmerged tree.
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("today_budget_left", useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNode(hasTestTag("today_budget_left") and hasText("$536.50"), useUnmergedTree = true).assertIsDisplayed()
        rule.onNodeWithTag("today_bills", useUnmergedTree = true).assertIsDisplayed()
        rule.onNodeWithTag("today_card").assertContentDescriptionContains("Budget left this month: $536.50 of $700.00", substring = true)
    }

    @Test fun finance_shows_accounts_budgets_bills_transactions_and_the_fixed_note() {
        app(Samples.populated())
        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("finance_list").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Credit card"))
        rule.onNodeWithTag("finance_list").performScrollToNode(hasTestTag("no_money_note"))
        rule.onNodeWithText("REVA records and analyses money. It can't pay, transfer, buy or log in to a bank — those actions don't exist.").assertIsDisplayed()
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Lunch"))
        rule.onNodeWithText("voice · confirmed").assertIsDisplayed()
    }

    @Test fun adding_a_transaction_through_the_sheet_shows_it_in_the_list() {
        val repo = Samples.populated()
        app(repo)
        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("add_transaction").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("add_transaction").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("tx_amount").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("tx_amount").performTextInput("7.25")
        rule.onNodeWithTag("tx_description").performTextInput("Sheet coffee")
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("tx_amount").fetchSemanticsNodes().isEmpty() }
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Sheet coffee"))
        rule.onNodeWithText("Sheet coffee").assertIsDisplayed()
        assertEquals(-725L, repo.addedTransactions.single().amountMinor)
    }

    @Test fun talk_and_more_are_honest_placeholders() {
        app(Samples.populated())
        rule.onNodeWithTag("tab_talk").performClick()
        rule.onNodeWithTag("talk_placeholder").assertIsDisplayed()
        rule.onNodeWithTag("tab_more").performClick()
        rule.onNodeWithTag("more_sections").assertIsDisplayed()
        rule.onNodeWithText("Health").assertIsDisplayed()
    }

    @Test fun add_transaction_is_disabled_until_there_is_an_account() {
        app(FakeFinanceRepository())
        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("finance_empty").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("add_transaction").assertIsNotEnabled()
        rule.onNodeWithTag("add_account").assertIsEnabled()
    }
}

/** The whole app on the REAL Kernel and Android Keystore: add an account, add an expense, see it listed. */
@RunWith(AndroidJUnit4::class)
class RealKernelComposeTest {
    @get:Rule val rule = createComposeRule()
    private val context: Context = ApplicationProvider.getApplicationContext()
    private lateinit var root: File

    @Before fun setUp() {
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.apply { if (containsAlias("reva.domain.finance")) deleteEntry("reva.domain.finance") }
        root = File(context.noBackupFilesDir, "ui-${System.nanoTime()}").also { it.mkdirs() }
    }

    @After fun tearDown() {
        root.deleteRecursively()
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.apply { if (containsAlias("reva.domain.finance")) deleteEntry("reva.domain.finance") }
    }

    @Test fun add_an_account_then_an_expense_and_see_it_in_the_list() {
        val repository = KernelFinanceRepository(openHandle = {
            openDomain("finance", KeystoreKeyProvider(File(root, "keys"), AndroidKeystoreWrapper()), File(root, "data").also { it.mkdirs() }.absolutePath)
        })
        rule.setContent { RevaTheme { RevaRoot(repository, "0.1.0", onShare = { _, _ -> }) } }

        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(15_000) { rule.onAllNodesWithTag("empty_add_account").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("empty_add_account").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("acct_name").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("acct_name").performTextInput("Phone Checking")
        rule.onNodeWithTag("acct_opening").performTextInput("100.00")
        rule.onNodeWithTag("acct_save").performScrollTo().performClick()

        rule.waitUntil(15_000) { rule.onAllNodesWithTag("add_transaction").fetchSemanticsNodes().isNotEmpty() && rule.onAllNodesWithTag("acct_name").fetchSemanticsNodes().isEmpty() }
        rule.waitUntil(15_000) {
            runCatching { rule.onNodeWithTag("add_transaction").assertIsEnabled() }.isSuccess
        }
        rule.onNodeWithTag("add_transaction").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("tx_amount").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("tx_amount").performTextInput("12.50")
        rule.onNodeWithTag("tx_description").performTextInput("Airplane lunch")
        rule.onNodeWithTag("tx_save").performScrollTo().performClick()

        rule.waitUntil(15_000) { rule.onAllNodesWithTag("tx_amount").fetchSemanticsNodes().isEmpty() }
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Airplane lunch"))
        rule.onNodeWithText("Airplane lunch").assertIsDisplayed()
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("-$12.50"))
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("$87.50"))
    }
}
