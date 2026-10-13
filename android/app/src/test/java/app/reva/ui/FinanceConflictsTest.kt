@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package app.reva.ui

import app.reva.data.Conflict
import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.Samples
import app.reva.ui.finance.FinanceViewModel
import java.time.LocalDate
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FinanceConflictsTest : MainDispatcherTest() {
    private val day = LocalDate.of(2026, 10, 12)

    private fun repo(): FakeFinanceRepository = Samples.populated().apply {
        conflicts = mutableListOf(
            Conflict(7, "Corner Cafe", "amount_minor", "USD", -1_111, -2_222),
            Conflict(8, "Rent", "amount_minor", "USD", -120_000, -125_000),
        )
    }

    @Test fun differing_amounts_become_banner_rows_with_both_values() = runTest {
        val vm = FinanceViewModel(repo(), { day })
        vm.refreshNow()
        val rows = vm.state.value.conflicts
        assertEquals(2, rows.size)
        assertEquals("Corner Cafe", rows[0].title)
        assertEquals("-$11.11", rows[0].mineText)
        assertEquals("-$22.22", rows[0].pcText)
        assertTrue(rows[0].a11y.contains("this phone says"))
    }

    @Test fun keep_mine_and_keep_the_pcs_go_through_the_repository_and_the_row_disappears() = runTest {
        val repo = repo()
        val vm = FinanceViewModel(repo, { day })
        vm.refreshNow()
        vm.resolveConflict(7, keepMine = true)
        vm.resolveConflict(8, keepMine = false)
        assertEquals(listOf(7L to true, 8L to false), repo.resolved)
        assertTrue(vm.state.value.conflicts.isEmpty())
    }

    @Test fun a_failed_resolution_shows_the_error_and_keeps_the_row() = runTest {
        val repo = repo().apply { failures["resolveConflict"] = FinanceError(ErrorKind.Conflict, "This conflict is already resolved.") }
        val vm = FinanceViewModel(repo, { day })
        vm.refreshNow()
        vm.resolveConflict(7, keepMine = true)
        assertEquals("This conflict is already resolved.", vm.state.value.error)
        assertEquals(2, vm.state.value.conflicts.size)
        assertFalse(vm.state.value.isBusy)
    }

    @Test fun no_conflicts_means_no_banner() = runTest {
        val vm = FinanceViewModel(Samples.populated(), { day })
        vm.refreshNow()
        assertTrue(vm.state.value.conflicts.isEmpty())
    }
}
