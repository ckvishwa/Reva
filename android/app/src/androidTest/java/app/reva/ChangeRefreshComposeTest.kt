package app.reva

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.TodayBudgetLeft
import app.reva.data.TodaySummary
import app.reva.sync.AutoSyncController
import app.reva.sync.AutoSyncSettings
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.FakeSyncService
import app.reva.testing.Samples
import app.reva.ui.RevaRoot
import app.reva.ui.theme.RevaTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * SYNC-1e on a real device: what a sync changes shows on the screen that is already open. Nothing in
 * these tests navigates after the data changes; the only signal is the repository's change counter.
 */
@RunWith(AndroidJUnit4::class)
class ChangeRefreshComposeTest {
    @get:Rule val rule = createComposeRule()

    private val scopes = mutableListOf<CoroutineScope>()

    @After fun stop() = scopes.forEach { it.cancel() }

    private fun app(repo: FakeFinanceRepository, sync: FakeSyncService? = null, autoSync: AutoSyncController? = null) {
        rule.setContent { RevaTheme { RevaRoot(repo, "0.1.0", onShare = { _, _ -> }, sync = sync, autoSync = autoSync) } }
    }

    private fun openFinance() {
        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("finance_list").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Lunch"))
    }

    @Test fun a_synced_expense_appears_on_the_open_finance_list_without_switching_tabs() {
        val repo = Samples.populated()
        app(repo)
        openFinance()

        repo.transactions.add(0, Samples.transaction("t9", "2026-10-13", -450, "Coffee from the PC"))
        repo.markChanged() // what the sync client does after it applied the PC's events

        rule.waitUntil(5_000) { rule.onAllNodesWithText("Coffee from the PC").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Coffee from the PC"))
        rule.onNodeWithText("Coffee from the PC").assertIsDisplayed()
    }

    @Test fun a_synced_delete_disappears_from_the_open_finance_list() {
        val repo = Samples.populated()
        app(repo)
        openFinance()
        rule.onNodeWithText("Lunch").assertIsDisplayed()

        repo.transactions.removeAt(0)
        repo.markChanged()

        rule.waitUntil(5_000) { rule.onAllNodesWithText("Lunch").fetchSemanticsNodes().isEmpty() }
    }

    @Test fun a_synced_edit_changes_the_open_row() {
        val repo = Samples.populated()
        app(repo)
        openFinance()

        repo.transactions[0] = repo.transactions[0].copy(description = "Lunch (edited on the PC)")
        repo.markChanged()

        rule.waitUntil(5_000) { rule.onAllNodesWithText("Lunch (edited on the PC)").fetchSemanticsNodes().isNotEmpty() }
    }

    @Test fun the_today_card_updates_in_place() {
        val repo = Samples.populated().apply {
            todaySummary = TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 70_000, 16_350, 53_650)), emptyList())
        }
        app(repo)
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("today_budget_left", useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("$536.50", useUnmergedTree = true).assertIsDisplayed()

        repo.todaySummary = TodaySummary("2026-10-12", listOf(TodayBudgetLeft("USD", 70_000, 30_000, 40_000)), emptyList())
        repo.markChanged()

        rule.waitUntil(5_000) { rule.onAllNodesWithText("$400.00", useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
    }

    @Test fun auto_sync_runs_when_the_app_is_in_front_and_the_screens_say_when() {
        val repo = Samples.populated()
        val sync = FakeSyncService().apply { pc = FakeSyncService.PC.copy(lastSyncAtSeconds = null) }
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default).also { scopes += it }
        val settings = object : AutoSyncSettings { override var enabled = true }
        val controller = AutoSyncController(sync, settings, scope, nowSeconds = { 1_000_000L })
        app(repo, sync, controller)

        rule.waitUntil(8_000) { sync.syncs >= 1 }
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("sync_status").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("sync_status").assertIsDisplayed()
        rule.onNodeWithText("Synced just now").assertIsDisplayed()
        assertTrue(sync.syncs >= 1)
    }

    @Test fun auto_sync_stays_quiet_when_switched_off() {
        val repo = Samples.populated()
        val sync = FakeSyncService().apply { pc = FakeSyncService.PC.copy(lastSyncAtSeconds = null) }
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default).also { scopes += it }
        val settings = object : AutoSyncSettings { override var enabled = false }
        app(repo, sync, AutoSyncController(sync, settings, scope, nowSeconds = { 1_000_000L }))

        rule.waitUntil(5_000) { rule.onAllNodesWithTag("sync_status").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Not synced yet").assertIsDisplayed()
        Thread.sleep(1_500)
        assertTrue("auto sync was off but a sync ran", sync.syncs == 0)
    }

    @Test fun the_devices_screen_has_the_automatic_sync_switch() {
        val repo = Samples.populated()
        val sync = FakeSyncService().apply { pc = FakeSyncService.PC.copy(lastSyncAtSeconds = null) }
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default).also { scopes += it }
        val settings = object : AutoSyncSettings { override var enabled = true }
        app(repo, sync, AutoSyncController(sync, settings, scope, nowSeconds = { 1_000_000L }))

        rule.onNodeWithTag("tab_more").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("open_devices").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("open_devices").performClick()
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("auto_sync_switch").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("auto_sync_switch").performClick()

        rule.waitUntil(5_000) { !settings.enabled }
    }
}
