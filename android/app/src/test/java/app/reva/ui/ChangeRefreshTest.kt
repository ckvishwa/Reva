@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package app.reva.ui

import app.reva.data.TodayBudgetLeft
import app.reva.data.TodaySummary
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.Samples
import app.reva.ui.finance.FinanceViewModel
import app.reva.ui.today.TodayViewModel
import java.time.LocalDate
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private val DAY = LocalDate.of(2026, 10, 12)

/**
 * SYNC-1e: a screen that is already open shows what a sync (or any commit) changed, with no tab switch.
 * The repository's change counter is the only signal; the view models reload from it, debounced.
 */
class ChangeRefreshTest {
    @After fun resetMain() = Dispatchers.resetMain()

    private fun TestScope.finance(repo: FakeFinanceRepository): FinanceViewModel {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        return FinanceViewModel(repo, { DAY }, searchDebounceMillis = 300, changeDebounceMillis = 300)
    }

    private fun TestScope.today(repo: FakeFinanceRepository): TodayViewModel {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        return TodayViewModel(repo, changeDebounceMillis = 300) { DAY }
    }

    private fun rows(vm: FinanceViewModel) = vm.state.value.transactions.map { it.description }

    @Test fun a_synced_new_transaction_appears_on_the_open_finance_screen() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()
        assertEquals(listOf("Lunch", "Market", "Paycheck"), rows(vm))

        // The sync client applied an event from the PC and bumped the counter.
        repo.transactions.add(0, Samples.transaction("t9", "2026-10-13", -450, "Coffee from the PC"))
        repo.markChanged()
        advanceTimeBy(301)
        runCurrent()

        assertEquals(listOf("Coffee from the PC", "Lunch", "Market", "Paycheck"), rows(vm))
    }

    @Test fun a_synced_edit_updates_the_visible_row() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()

        repo.transactions[1] = repo.transactions[1].copy(description = "Market (edited on the PC)", amountMinor = -9_999)
        repo.markChanged()
        advanceTimeBy(301)
        runCurrent()

        assertTrue(rows(vm).contains("Market (edited on the PC)"))
        assertFalse(rows(vm).contains("Market"))
        assertTrue(vm.state.value.transactions.first { it.description.startsWith("Market") }.amountText.contains("99.99"))
    }

    @Test fun a_synced_delete_removes_the_visible_row() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()

        repo.transactions.removeAt(0)
        repo.markChanged()
        advanceTimeBy(301)
        runCurrent()

        assertEquals(listOf("Market", "Paycheck"), rows(vm))
    }

    @Test fun a_burst_of_changes_reloads_once() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()
        val before = repo.calls.count { it == "balances" }

        repeat(5) {
            repo.markChanged()
            advanceTimeBy(100) // each change lands inside the previous one's window
        }
        advanceTimeBy(301)
        runCurrent()

        assertEquals(1, repo.calls.count { it == "balances" } - before)
    }

    @Test fun nothing_loads_before_the_screen_has_loaded_once() = runTest {
        val repo = Samples.populated()
        finance(repo)

        repo.markChanged()
        advanceTimeBy(1_000)
        runCurrent()

        assertEquals(emptyList<String>(), repo.calls)
    }

    @Test fun a_background_reload_does_not_flash_the_spinner() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()
        val gate = CompletableDeferred<Unit>()
        repo.gate = gate

        repo.markChanged()
        advanceTimeBy(301)
        runCurrent() // the reload is now waiting on the repository

        assertFalse("a sync-triggered reload must not show the loading spinner", vm.state.value.isLoading)
        gate.complete(Unit)
        runCurrent()
    }

    @Test fun the_caller_of_markChanged_never_waits_for_the_reload() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()
        repo.gate = CompletableDeferred() // every repository call now hangs

        repo.markChanged() // would hang if the counter did any work itself
        repo.markChanged()

        assertEquals(true, vm.state.value.hasLoaded)
    }

    @Test fun a_change_made_on_the_phone_itself_also_reloads_the_screen() = runTest {
        val repo = Samples.populated()
        val vm = finance(repo)
        vm.refreshNow()

        repo.addTransaction(app.reva.data.NewTransaction("acct-card", "2026-10-13", -100, "Gum", null, null))
        advanceTimeBy(301)
        runCurrent()

        assertTrue(rows(vm).contains("Gum"))
    }

    @Test fun the_today_card_follows_a_sync_too() = runTest {
        val repo = Samples.populated().apply {
            todaySummary = TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 70_000, 16_350, 53_650)), emptyList())
        }
        val vm = today(repo)
        vm.refreshNow()
        assertEquals("$536.50", vm.state.value.budgetLeftText)

        repo.todaySummary = TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 70_000, 30_000, 40_000)), emptyList())
        repo.markChanged()
        advanceTimeBy(301)
        runCurrent()

        assertEquals("$400.00", vm.state.value.budgetLeftText)
    }

    @Test fun today_does_not_load_until_it_was_opened() = runTest {
        val repo = Samples.populated()
        today(repo)

        repo.markChanged()
        advanceTimeBy(1_000)
        runCurrent()

        assertEquals(emptyList<String>(), repo.calls)
    }
}
