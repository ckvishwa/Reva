@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package app.reva.ui

import app.reva.data.ErrorKind
import app.reva.data.DailyCashflow
import app.reva.data.DailySpendCategory
import app.reva.data.FinanceDailyAnalysis
import app.reva.data.FinanceError
import app.reva.data.ImportReport
import app.reva.data.ImportRow
import app.reva.data.NetWorthEntry
import app.reva.data.NetWorthSnapshot
import app.reva.data.Outcome
import app.reva.data.TodayBudgetLeft
import app.reva.data.TodaySummary
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.Samples
import app.reva.ui.finance.AccountOption
import app.reva.ui.finance.AddAccountViewModel
import app.reva.ui.finance.AddTransactionViewModel
import app.reva.ui.finance.FinanceViewModel
import app.reva.ui.finance.ImportViewModel
import app.reva.ui.today.TodayViewModel
import java.time.LocalDate
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

private val TODAY = LocalDate.of(2026, 10, 12)

abstract class MainDispatcherTest {
    @Before fun setMain() = Dispatchers.setMain(UnconfinedTestDispatcher())

    @After fun resetMain() = Dispatchers.resetMain()
}

class FinanceViewModelTest : MainDispatcherTest() {
    private fun vm(repo: FakeFinanceRepository) = FinanceViewModel(repo, { TODAY }, searchDebounceMillis = 300)

    @Test fun refresh_loads_every_section() = runTest {
        val repo = Samples.populated().apply {
            snapshots = mutableListOf(NetWorthSnapshot("n1", "2026-10-12", mapOf("USD" to NetWorthEntry(650_000, 22_849, 627_151))))
        }
        val vm = vm(repo)
        vm.refreshNow()
        val s = vm.state.value
        assertTrue(s.hasLoaded)
        assertNull(s.error)
        assertEquals(listOf("Checking", "Credit card"), s.accounts.map { it.title })
        assertEquals("$6,500.00", s.accounts[0].balanceText)
        assertEquals("-$228.49", s.accounts[1].balanceText)
        assertEquals("Checking · USD", s.accounts[0].caption.replace("Checking · ", "Checking · "))
        assertEquals(2, s.budgets.size)
        assertEquals(2, s.bills.size)
        assertEquals(3, s.transactions.size)
        assertTrue(s.netWorth.hasSnapshot)
        assertEquals("$6,271.51", s.netWorth.valueText)
        assertEquals("Taken Oct 12", s.netWorth.caption)
        assertFalse(s.showEmptyState)
    }

    @Test fun budget_bars_over_ninety_percent_are_flagged_and_fill_is_capped() = runTest {
        val repo = FakeFinanceRepository().apply {
            balances = mutableListOf(Samples.checking())
            budgets = mutableListOf(
                Samples.budget("low", 10_000, 2_000),
                Samples.budget("edge", 10_000, 9_000),
                Samples.budget("near", 10_000, 9_100),
                Samples.budget("over", 10_000, 12_500, over = true),
            )
        }
        val vm = vm(repo)
        vm.refreshNow()
        val rows = vm.state.value.budgets
        assertEquals(listOf(false, false, true, true), rows.map { it.isNearLimit })
        assertEquals(listOf(0.2f, 0.9f, 0.91f, 1.0f), rows.map { Math.round(it.fraction * 100) / 100f })
        assertEquals("$20.00 / $100.00", rows[0].amountsText)
        assertTrue(rows[3].a11y.contains("over budget by $25.00"))
        assertTrue(rows[0].a11y.contains("20 percent used"))
    }

    @Test fun transactions_show_dates_signed_amounts_and_source() = runTest {
        val vm = vm(Samples.populated())
        vm.refreshNow()
        val rows = vm.state.value.transactions
        assertEquals(listOf("Today", "Yesterday", "Oct 1"), rows.map { it.dateText })
        assertEquals(listOf("-$12.00", "-$84.50", "+$3,000.00"), rows.map { it.amountText })
        assertEquals(listOf("voice · confirmed", "manual", "manual"), rows.map { it.sourceText })
        assertEquals(listOf("Food · Dining", "Groceries", "Uncategorized"), rows.map { it.categoryText })
        assertTrue(rows[2].isIncome)
        assertTrue(rows[0].isVoice)
        assertTrue(rows[0].a11y.contains("source voice · confirmed"))
    }

    @Test fun a_locked_finance_file_is_reported_plainly() = runTest {
        val repo = Samples.populated().apply {
            failures["balances"] = FinanceError(ErrorKind.Locked, "Finance is locked: this phone has no key that opens the Finance data.")
        }
        val vm = vm(repo)
        vm.refreshNow()
        val s = vm.state.value
        assertTrue(s.isLocked)
        assertTrue(s.hasLoaded)
        assertFalse(s.isLoading)
        assertTrue(s.error!!.contains("locked"))
        assertFalse(s.showEmptyState)
    }

    @Test fun a_fresh_install_offers_add_account_instead_of_an_error() = runTest {
        val vm = vm(FakeFinanceRepository())
        vm.refreshNow()
        val s = vm.state.value
        assertTrue(s.showEmptyState)
        assertNull(s.error)
        assertFalse(s.hasAccounts)
        assertEquals("No transactions yet.", s.transactionsEmptyText)
        assertFalse(s.netWorth.hasSnapshot)
    }

    @Test fun refresh_does_not_block_the_caller_while_the_kernel_is_slow() = runTest {
        val repo = Samples.populated().apply { gate = CompletableDeferred() }
        val vm = vm(repo)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { vm.refreshNow() }
        assertTrue(job.isActive)
        assertTrue(vm.state.value.isLoading)
        assertTrue(vm.state.value.accounts.isEmpty())
        repo.gate!!.complete(Unit)
        job.join()
        assertFalse(vm.state.value.isLoading)
        assertEquals(2, vm.state.value.accounts.size)
    }

    @Test fun a_newer_refresh_wins_over_an_older_slower_one() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.refreshNow()

        repo.balances = mutableListOf(Samples.checking().copy(name = "OLD"))
        val gate = CompletableDeferred<Unit>()
        repo.gate = gate
        val slow = launch(start = CoroutineStart.UNDISPATCHED) { vm.refreshNow() }
        repo.gate = null
        repo.balances = mutableListOf(Samples.checking().copy(name = "NEW"))
        vm.refreshNow()
        assertEquals("NEW", vm.state.value.accounts[0].title)

        gate.complete(Unit)
        slow.join()
        assertEquals("NEW", vm.state.value.accounts[0].title)
        assertFalse(vm.state.value.isLoading)
    }

    @Test fun search_asks_the_kernel_and_says_when_nothing_matches() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.refreshNow()
        vm.onSearchChange("lunch")
        vm.searchNow()
        assertEquals(listOf("Lunch"), vm.state.value.transactions.map { it.description })
        assertTrue(repo.calls.contains("transactions:q=lunch"))
        vm.onSearchChange("zzz")
        vm.searchNow()
        assertTrue(vm.state.value.transactions.isEmpty())
        assertEquals("No transactions match that search.", vm.state.value.transactionsEmptyText)
    }

    @Test fun typing_is_debounced_into_one_search() = runTest(StandardTestDispatcher()) {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.onSearchChange("l")
        vm.onSearchChange("lu")
        vm.onSearchChange("lunch")
        advanceTimeBy(299)
        assertEquals(0, repo.calls.count { it.startsWith("transactions") })
        advanceTimeBy(2)
        testScheduler.runCurrent()
        assertEquals(listOf("transactions:q=lunch"), repo.calls.filter { it.startsWith("transactions") })
    }

    @Test fun a_slow_old_search_never_overwrites_a_newer_one() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.refreshNow()
        val gate = CompletableDeferred<Unit>()
        repo.gate = gate
        vm.onSearchChange("lunch")
        val slow = launch(start = CoroutineStart.UNDISPATCHED) { vm.searchNow() }
        repo.gate = null
        vm.onSearchChange("market")
        vm.searchNow()
        assertEquals(listOf("Market"), vm.state.value.transactions.map { it.description })
        gate.complete(Unit)
        slow.join()
        assertEquals(listOf("Market"), vm.state.value.transactions.map { it.description })
    }

    @Test fun switching_the_budget_period_reloads_only_the_budgets() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.refreshNow()
        repo.calls.clear()
        vm.setBudgetPeriod(FinanceViewModel.LAST_MONTH)
        vm.setBudgetPeriod("nonsense")
        assertEquals(listOf("budgetStatus:last_month"), repo.calls)
        assertEquals(FinanceViewModel.LAST_MONTH, vm.state.value.budgetPeriod)
    }

    @Test fun taking_a_snapshot_updates_the_card() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.refreshNow()
        assertFalse(vm.state.value.netWorth.hasSnapshot)
        repo.snapshots.add(NetWorthSnapshot("n", "2026-10-12", mapOf("EUR" to NetWorthEntry(10_000, 0, 10_000), "USD" to NetWorthEntry(5_000, 1_000, 4_000))))
        vm.takeSnapshot()
        assertEquals("€100.00 · $40.00", vm.state.value.netWorth.valueText)
        assertTrue(repo.calls.contains("takeSnapshot"))
    }

    @Test fun export_returns_the_kernel_bytes_and_clears_busy() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        val result = vm.export("csv") as Outcome.Ok
        assertEquals(listOf<Byte>(1, 2, 3), result.value.toList())
        assertFalse(vm.state.value.isBusy)
    }

    @Test fun the_no_money_movement_note_is_fixed_text() {
        assertEquals(
            "REVA records and analyses money. It can't pay, transfer, buy or log in to a bank — those actions don't exist.",
            FinanceViewModel.NO_MONEY_MOVEMENT_NOTE,
        )
    }
}

class AddTransactionViewModelTest : MainDispatcherTest() {
    private fun vm(repo: FakeFinanceRepository = Samples.populated()) = AddTransactionViewModel(
        repo,
        listOf(AccountOption("acct-checking", "Checking", "USD"), AccountOption("acct-card", "Credit card", "USD")),
        listOf("Food · Dining", "Groceries"),
        TODAY,
    )

    private fun fill(vm: AddTransactionViewModel, amount: String = "12.00", description: String = "Lunch") {
        vm.setAmount(amount)
        vm.setDescription(description)
    }

    @Test fun starts_on_the_first_account_today_and_expense() {
        val vm = vm()
        assertEquals("Checking", vm.selectedAccount!!.name)
        assertEquals(TODAY, vm.state.value.date)
        assertTrue(vm.state.value.isExpense)
    }

    @Test fun the_preview_states_exactly_what_will_be_recorded() {
        val vm = vm()
        assertEquals("Enter an amount to see what will be recorded.", vm.previewText())
        fill(vm)
        assertEquals("Will record $12.00 spent from Checking on 2026-10-12.", vm.previewText())
        vm.setExpense(false)
        assertEquals("Will record $12.00 added to Checking on 2026-10-12.", vm.previewText())
        vm.setAmount("12.345")
        assertEquals("Enter an amount to see what will be recorded.", vm.previewText())
    }

    @Test fun the_sign_comes_from_money_out_or_in_never_from_a_typing_accident() {
        val vm = vm()
        for ((typed, expense, expected) in listOf(
            Triple("12.00", true, -1_200L), Triple("12.00", false, 1_200L), Triple("-12.00", true, -1_200L), Triple("-12.00", false, 1_200L),
        )) {
            vm.setAmount(typed)
            vm.setExpense(expense)
            assertEquals(expected, vm.signedAmountMinor())
        }
    }

    @Test fun an_empty_form_reports_every_problem_and_sends_nothing() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        assertFalse(vm.submit())
        val s = vm.state.value
        assertEquals("Enter an amount.", s.amountError)
        assertEquals("Enter a description.", s.descriptionError)
        assertNull(s.accountError)
        assertTrue(repo.addedTransactions.isEmpty())
    }

    @Test fun bad_amounts_are_explained_and_not_sent() = runTest {
        for ((typed, message) in listOf(
            "0" to "The amount can't be zero.", "abc" to "That is not a valid amount.",
            "1.234" to "At most 2 decimal places for USD.", "12,50" to "Use a point for decimals, for example 12.50.",
        )) {
            val repo = Samples.populated()
            val vm = vm(repo)
            fill(vm, typed)
            assertFalse(vm.submit())
            assertEquals(message, vm.state.value.amountError)
            assertTrue(repo.addedTransactions.isEmpty())
        }
    }

    @Test fun a_valid_form_is_sent_once_with_trimmed_text() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        vm.selectAccount("acct-card")
        fill(vm, "$1,234.50", "  Lunch with Sam  ")
        vm.setCategory(" lunch ")
        vm.setNotes("  team  ")
        vm.setDate(LocalDate.of(2026, 10, 9))
        assertTrue(vm.submit())
        val sent = repo.addedTransactions.single()
        assertEquals("acct-card", sent.accountId)
        assertEquals("2026-10-09", sent.date)
        assertEquals(-123_450L, sent.amountMinor)
        assertEquals("Lunch with Sam", sent.description)
        assertEquals("lunch", sent.category)
        assertEquals("team", sent.notes)
        assertFalse(vm.state.value.isBusy)
    }

    @Test fun blank_category_and_notes_are_not_sent() = runTest {
        val repo = Samples.populated()
        val vm = vm(repo)
        fill(vm)
        vm.submit()
        assertNull(repo.addedTransactions.single().category)
        assertNull(repo.addedTransactions.single().notes)
    }

    @Test fun the_kernel_rejecting_the_category_is_shown_next_to_the_category() = runTest {
        val repo = Samples.populated().apply {
            failures["addTransaction"] = FinanceError(ErrorKind.Validation, "category: no category or alias named \"zzz\"", "category", "no category or alias named \"zzz\"")
        }
        val vm = vm(repo)
        fill(vm)
        vm.setCategory("zzz")
        assertFalse(vm.submit())
        assertEquals("no category or alias named \"zzz\"", vm.state.value.categoryError)
        assertNull(vm.state.value.generalError)
    }

    @Test fun other_failures_show_a_safe_general_message() = runTest {
        val repo = Samples.populated().apply { failures["addTransaction"] = FinanceError(ErrorKind.Locked, "Finance is locked: this phone has no key that opens the Finance data.") }
        val vm = vm(repo)
        fill(vm)
        assertFalse(vm.submit())
        assertTrue(vm.state.value.generalError!!.contains("locked"))
    }

    @Test fun a_second_save_while_the_first_is_in_flight_is_ignored() = runTest {
        val repo = Samples.populated().apply { gate = CompletableDeferred() }
        val vm = vm(repo)
        fill(vm)
        val first = launch(start = CoroutineStart.UNDISPATCHED) { vm.submit() }
        assertTrue(vm.state.value.isBusy)
        assertFalse(vm.submit())
        repo.gate!!.complete(Unit)
        first.join()
        assertEquals(1, repo.addedTransactions.size)
    }

    @Test fun editing_a_field_clears_its_error() {
        val vm = vm()
        assertFalse(vm.validate())
        assertNotNull(vm.state.value.amountError)
        vm.setAmount("1")
        vm.setDescription("x")
        assertNull(vm.state.value.amountError)
        assertNull(vm.state.value.descriptionError)
    }

    @Test fun a_date_far_in_the_future_is_refused() {
        val vm = vm()
        fill(vm)
        vm.setDate(LocalDate.of(2028, 1, 1))
        assertFalse(vm.validate())
        assertEquals("That date is more than a year ahead.", vm.state.value.dateError)
    }

    @Test fun without_any_account_it_says_so() {
        val vm = AddTransactionViewModel(Samples.populated(), emptyList(), emptyList(), TODAY)
        fill(vm)
        assertFalse(vm.validate())
        assertEquals("Choose an account.", vm.state.value.accountError)
    }
}

class AddAccountViewModelTest : MainDispatcherTest() {
    @Test fun cards_and_loans_store_what_you_owe_as_a_negative_balance() = runTest {
        val repo = FakeFinanceRepository()
        val vm = AddAccountViewModel(repo)
        vm.setName("Visa"); vm.setKind("credit"); vm.setCurrency("usd"); vm.setOpening("250.00")
        assertTrue(vm.submit())
        val sent = repo.addedAccounts.single()
        assertEquals("Visa", sent.name)
        assertEquals("credit", sent.kind)
        assertEquals("USD", sent.currency)
        assertEquals(-25_000L, sent.openingBalanceMinor)
        assertTrue(vm.state.value.openingHint.contains("owe"))
    }

    @Test fun a_checking_account_keeps_the_balance_as_typed_and_blank_means_zero() = runTest {
        val repo = FakeFinanceRepository()
        val vm = AddAccountViewModel(repo)
        vm.setName("Main"); vm.setOpening("1,000.50")
        assertTrue(vm.submit())
        vm.setName("Second"); vm.setOpening("")
        assertTrue(vm.submit())
        assertEquals(listOf(100_050L, 0L), repo.addedAccounts.map { it.openingBalanceMinor })
    }

    @Test fun bad_input_is_explained_and_not_sent() = runTest {
        val repo = FakeFinanceRepository()
        val vm = AddAccountViewModel(repo)
        vm.setName(" "); vm.setCurrency("U5"); vm.setOpening("x")
        assertFalse(vm.submit())
        assertEquals("Enter a name.", vm.state.value.nameError)
        assertEquals("Use a 3-letter currency code such as USD.", vm.state.value.currencyError)
        assertTrue(repo.addedAccounts.isEmpty())
        vm.setCurrency("USD"); vm.setName("Ok")
        assertFalse(vm.submit())
        assertEquals("That is not a valid amount.", vm.state.value.openingError)
    }

    @Test fun a_duplicate_name_is_shown_next_to_the_name() = runTest {
        val repo = FakeFinanceRepository().apply {
            failures["addAccount"] = FinanceError(ErrorKind.Conflict, "an account named \"Main\" already exists", null, "an account named \"Main\" already exists")
        }
        val vm = AddAccountViewModel(repo)
        vm.setName("Main")
        assertFalse(vm.submit())
        assertEquals("an account named \"Main\" already exists", vm.state.value.nameError)
    }
}

class ImportViewModelTest : MainDispatcherTest() {
    private val bankCsv = "Date,Description,Debit,Credit,Category\n05/10/2026,COFFEE,4.50,,Dining\n13/10/2026,PAYCHECK,,1500.00,Income\n"

    private fun vm(repo: FakeFinanceRepository) = ImportViewModel(
        repo, listOf(AccountOption("acct-checking", "Checking", "USD"), AccountOption("acct-card", "Credit card", "USD")),
    )

    private fun report(dry: Boolean, accepted: Long = 2, duplicates: Long = 0, vararg rejected: ImportRow) = ImportReport(
        accepted, duplicates, rejected.size.toLong(),
        listOf(
            ImportRow(2, "accepted", null, "2026-10-05", -450, "COFFEE", null, "raw"),
            ImportRow(3, "accepted", null, "2026-10-13", 150_000, "PAYCHECK", "category not found", "raw"),
        ) + rejected,
        dry,
    )

    @Test fun a_csv_proposes_columns_and_date_format_from_the_header() {
        val vm = vm(FakeFinanceRepository())
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        val s = vm.state.value
        assertEquals("csv", s.format)
        assertTrue(s.isCsv && s.needsAccount)
        assertEquals("Date", s.dateColumn)
        assertEquals("Description", s.descriptionColumn)
        assertNull(s.amountColumn)
        assertEquals("Debit", s.debitColumn)
        assertEquals("Credit", s.creditColumn)
        assertEquals("Category", s.categoryColumn)
        assertEquals("%d/%m/%Y", s.dateFormat)
        assertFalse(s.dateFormatIsAmbiguous)
    }

    @Test fun ofx_and_json_need_no_mapping_and_unknown_files_are_refused() {
        val vm = vm(FakeFinanceRepository())
        vm.loadFile("bank.QFX", "<OFX>".toByteArray())
        assertEquals("ofx", vm.state.value.format)
        assertFalse(vm.state.value.isCsv)
        assertTrue(vm.state.value.needsAccount)
        vm.loadFile("backup.json", "{}".toByteArray())
        assertEquals("json", vm.state.value.format)
        assertFalse(vm.state.value.needsAccount)
        vm.loadFile("photo.png", byteArrayOf(1))
        assertEquals("", vm.state.value.format)
        assertTrue(vm.state.value.error!!.contains("isn't one of them"))
    }

    @Test fun check_runs_a_dry_run_with_the_mapping_and_saves_nothing() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.selectAccount("acct-card")
        assertTrue(vm.check())
        val call = repo.imports.single()
        assertEquals("csv", call.format)
        assertTrue(call.dryRun)
        assertEquals("acct-card", call.accountId)
        assertEquals("Date", call.mapping!!.date)
        assertEquals("%d/%m/%Y", call.mapping!!.dateFormat)
        assertEquals("Debit", call.mapping!!.debit)
        assertNull(call.mapping!!.amount)
        assertEquals(",", call.mapping!!.delimiter)
        val s = vm.state.value
        assertTrue(s.canConfirm)
        assertEquals("2 will import · 0 already there · 0 rejected. Nothing has been saved yet.", s.summaryText)
        assertEquals("Import 2 rows", s.confirmText)
        assertEquals("will import", s.reportRows[0].statusText)
        assertTrue(s.reportRows[0].summary.contains("-$4.50"))
    }

    @Test fun import_is_not_available_before_the_report_has_been_seen() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        assertFalse(vm.state.value.canConfirm)
        assertFalse(vm.confirm())
        assertTrue(repo.imports.isEmpty())
        assertEquals("Check the file first. Nothing is saved until you confirm.", vm.state.value.summaryText)
    }

    @Test fun confirm_runs_the_real_import_exactly_once() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.check()
        assertTrue(vm.confirm())
        assertFalse(vm.confirm())
        assertEquals(listOf(true, false), repo.imports.map { it.dryRun })
        assertEquals("Imported 2 rows. 0 were already there, 0 were rejected.", vm.state.value.resultText)
        assertFalse(vm.state.value.canConfirm)
        assertFalse(vm.state.value.canCheck)
    }

    @Test fun changing_any_choice_after_the_check_throws_the_report_away() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.check()
        assertTrue(vm.state.value.canConfirm)
        vm.setDateFormat("%m/%d/%Y")
        assertFalse(vm.state.value.hasReport)
        assertFalse(vm.state.value.canConfirm)
        assertTrue(vm.state.value.reportRows.isEmpty())
        assertFalse(vm.confirm())
        assertEquals(1, repo.imports.size)
    }

    @Test fun rejected_rows_are_listed_with_reason_and_raw_row() = runTest {
        val rejected = ImportRow(5, "rejected", "date does not match %d/%m/%Y", null, null, null, null, "31/02/2026,BAD,1.00")
        val repo = FakeFinanceRepository().apply { importResponder = { report(it, 2, 1, rejected) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.check()
        assertEquals("2 will import · 1 already there · 1 rejected. Nothing has been saved yet.", vm.state.value.summaryText)
        val row = vm.state.value.reportRows.single { it.status == "rejected" }
        assertEquals("5", row.rowText)
        assertEquals("31/02/2026,BAD,1.00", row.summary)
        assertEquals("date does not match %d/%m/%Y", row.detail)
        assertTrue(row.a11y.contains("Row 5, rejected"))
    }

    @Test fun nothing_to_import_cannot_be_confirmed() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it, 0, 3) } }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.check()
        assertTrue(vm.state.value.hasReport)
        assertFalse(vm.state.value.canConfirm)
        assertEquals("Import", vm.state.value.confirmText)
    }

    @Test fun missing_columns_are_explained_before_anything_is_sent() = runTest {
        val repo = FakeFinanceRepository()
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.setDescriptionColumn(null)
        assertFalse(vm.check())
        assertEquals("Choose which column holds the description.", vm.state.value.error)
        vm.setDateColumn(null)
        vm.check()
        assertEquals("Choose which column holds the date.", vm.state.value.error)
        assertTrue(repo.imports.isEmpty())
    }

    @Test fun one_amount_column_or_debit_and_credit_but_not_both() = runTest {
        val repo = FakeFinanceRepository()
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        vm.setAmountColumn("Debit")
        vm.check()
        assertEquals("Use either one Amount column or Debit/Credit columns, not both.", vm.state.value.error)
        vm.setAmountColumn(null); vm.setDebitColumn(null); vm.setCreditColumn(null)
        vm.check()
        assertEquals("Choose the Amount column, or the Debit and Credit columns.", vm.state.value.error)
        assertTrue(repo.imports.isEmpty())
    }

    @Test fun kernel_failures_leave_no_report() = runTest {
        val repo = FakeFinanceRepository().apply {
            failures["import"] = FinanceError(ErrorKind.Validation, "mapping: no column named \"Date\"", "mapping", "no column named \"Date\"")
        }
        val vm = vm(repo)
        vm.loadFile("statement.csv", bankCsv.toByteArray())
        assertFalse(vm.check())
        assertFalse(vm.state.value.hasReport)
        assertTrue(vm.state.value.error!!.contains("no column named"))
        assertFalse(vm.state.value.isBusy)
    }

    @Test fun ofx_sends_the_account_and_no_mapping_and_json_sends_no_account() = runTest {
        val repo = FakeFinanceRepository().apply { importResponder = { report(it) } }
        val vm = vm(repo)
        vm.loadFile("bank.ofx", "<OFX></OFX>".toByteArray())
        assertTrue(vm.check())
        assertEquals("acct-checking", repo.imports[0].accountId)
        assertNull(repo.imports[0].mapping)
        vm.loadFile("backup.json", "{}".toByteArray())
        assertTrue(vm.check())
        assertNull(repo.imports[1].accountId)
    }

    @Test fun a_file_over_the_kernel_limit_is_refused_up_front() {
        val vm = vm(FakeFinanceRepository())
        vm.loadFile("a.csv", bankCsv.toByteArray())
        vm.rejectTooLarge("huge.csv")
        assertFalse(vm.state.value.hasFile)
        assertFalse(vm.state.value.canCheck)
        assertTrue(vm.state.value.error!!.contains("larger than 8 MB"))
    }
}

class TodayViewModelTest : MainDispatcherTest() {
    private fun vm(summary: TodaySummary? = null, repo: FakeFinanceRepository = FakeFinanceRepository()): Pair<TodayViewModel, FakeFinanceRepository> {
        summary?.let { repo.todaySummary = it }
        return TodayViewModel(repo) { TODAY } to repo
    }

    @Test fun daily_finance_uses_exact_kernel_totals_and_shows_the_records_count() = runTest {
        val repo = FakeFinanceRepository().apply {
            dailyAnalysis = FinanceDailyAnalysis(
                "2026-10-12",
                listOf(DailyCashflow("USD", 12000, 3499, 8501), DailyCashflow("EUR", 0, 100, -100)),
                listOf(DailySpendCategory("food", "Food", "USD", 3499, 2)),
                listOf("tx-1", "tx-2"),
            )
        }
        val (vm, _) = vm(repo = repo)

        vm.refreshNow()

        assertEquals(2, vm.state.value.dailyRows.size)
        val byCurrency = vm.state.value.dailyRows.associateBy { it.currency }
        assertEquals("$120.00", byCurrency.getValue("USD").incomeText)
        assertEquals("$34.99", byCurrency.getValue("USD").expenseText)
        assertEquals("€1.00", byCurrency.getValue("EUR").expenseText)
        assertEquals("Food $34.99", vm.state.value.topSpendingText)
        assertEquals(2, vm.state.value.dailySourceCount)
    }

    @Test fun shows_budget_left_and_bills_in_seven_days() = runTest {
        val (vm, _) = vm(
            TodaySummary(
                "2026-10-12", listOf(TodayBudgetLeft("USD", 70_000, 16_350, 53_650)),
                listOf(Samples.bill("Gym", "2026-10-10", -2, overdue = true), Samples.bill("Internet", "2026-10-14", 2)),
            ),
        )
        vm.refreshNow()
        val s = vm.state.value
        assertTrue(s.hasBudget)
        assertEquals("$536.50", s.budgetLeftText)
        assertEquals("of $700.00", s.budgetOfText)
        assertEquals(0.2335f, s.budgetFraction, 0.0001f)
        assertFalse(s.budgetNearLimit)
        assertEquals("Bills in 7 days · Gym Oct 10 · Internet Oct 14", s.billsText)
        assertTrue(s.accessibleSummary.contains("Budget left this month: $536.50 of $700.00"))
    }

    @Test fun a_nearly_used_budget_turns_the_bar_light_orange() = runTest {
        val (vm, _) = vm(TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 10_000, 9_500, 500)), emptyList()))
        vm.refreshNow()
        assertTrue(vm.state.value.budgetNearLimit)
        assertEquals(0.95f, vm.state.value.budgetFraction, 0.0001f)
    }

    @Test fun income_is_not_listed_as_a_bill_and_an_empty_week_is_said_plainly() = runTest {
        val (vm, _) = vm(TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 100, 0, 100)), listOf(Samples.bill("Paycheck", "2026-10-15", 3, "income"))))
        vm.refreshNow()
        assertEquals("No bills in the next 7 days", vm.state.value.billsText)
    }

    @Test fun with_no_budgets_it_says_so_instead_of_showing_zero() = runTest {
        val (vm, _) = vm()
        vm.refreshNow()
        assertFalse(vm.state.value.hasBudget)
        assertEquals("No budgets set", vm.state.value.budgetLeftText)
        assertEquals(0f, vm.state.value.budgetFraction, 0f)
    }

    @Test fun other_currencies_get_a_short_line() = runTest {
        val (vm, _) = vm(TodaySummary("2026-10-12", listOf(TodayBudgetLeft("EUR", 5_000, 1_000, 4_000), TodayBudgetLeft("USD", 70_000, 16_350, 53_650)), emptyList()))
        vm.refreshNow()
        assertEquals("$536.50", vm.state.value.budgetLeftText)
        assertEquals("€40.00 left of €50.00", vm.state.value.otherCurrenciesText)
    }

    @Test fun a_failure_shows_a_safe_message_and_no_numbers() = runTest {
        val repo = FakeFinanceRepository().apply { failures["today"] = FinanceError(ErrorKind.Locked, "Finance is locked: this phone has no key that opens the Finance data.") }
        val (vm, _) = vm(repo = repo)
        vm.refreshNow()
        assertTrue(vm.state.value.error!!.contains("locked"))
        assertFalse(vm.state.value.hasBudget)
        assertEquals(vm.state.value.error, vm.state.value.accessibleSummary)
    }

    @Test fun refreshing_never_blocks_the_caller() = runTest {
        val repo = FakeFinanceRepository().apply { gate = CompletableDeferred() }
        val (vm, _) = vm(repo = repo)
        val job = launch(start = CoroutineStart.UNDISPATCHED) { vm.refreshNow() }
        assertTrue(job.isActive)
        assertTrue(vm.state.value.isLoading)
        repo.gate!!.complete(Unit)
        job.join()
        assertFalse(vm.state.value.isLoading)
    }
}
