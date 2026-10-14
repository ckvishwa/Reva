package app.reva

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.Conflict
import app.reva.sync.PairPoll
import app.reva.testing.FakeSyncService
import app.reva.testing.Samples
import app.reva.ui.RevaRoot
import app.reva.ui.devices.DevicesScreen
import app.reva.ui.devices.DevicesViewModel
import app.reva.ui.theme.RevaTheme
import android.graphics.Bitmap
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.io.FileOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** The Devices screen and the Finance conflict banner, driven like a person would, with fakes (no network, no camera). */
@RunWith(AndroidJUnit4::class)
class SyncComposeTest {
    @get:Rule val rule = createComposeRule()

    /** Opt-in (-e screenshots true): saves what is on screen for the design check. */
    private fun shot(name: String) {
        if (InstrumentationRegistry.getArguments().getString("screenshots") != "true") return
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        Thread.sleep(500)
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
        val dir = File(InstrumentationRegistry.getInstrumentation().targetContext.getExternalFilesDir(null), "screenshots").also { it.mkdirs() }
        FileOutputStream(File(dir, "$name.png")).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun waitFor(tag: String) = rule.waitUntil(10_000) { rule.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty() }

    @Test fun pairing_shows_the_digits_to_compare_then_the_paired_pc_and_sync_now_works() {
        val service = FakeSyncService().apply { polls.addAll(listOf(PairPoll.Pending, PairPoll.Pending, PairPoll.Approved(FakeSyncService.PC))) }
        val vm = DevicesViewModel(service, pollIntervalMillis = 1_500) // slow enough to look at the digits
        rule.setContent { RevaTheme { DevicesScreen(vm, onScan = {}, onBack = {}) } }

        waitFor("not_paired")
        shot("devices-1-not-paired")
        rule.onNodeWithTag("use_code").performClick() // disabled with nothing typed: no effect
        assertEquals(0, service.started)
        rule.onNodeWithTag("pairing_text").performTextInput("REVA-PAIR1:abc")
        rule.onNodeWithTag("use_code").performClick()

        waitFor("pairing_fingerprint")
        shot("devices-3-compare-digits")
        rule.onNodeWithTag("pairing_fingerprint").assertIsDisplayed()
        rule.onNodeWithTag("pairing_wait").assertIsDisplayed()
        rule.onNode(hasText("123 456")).assertIsDisplayed()

        waitFor("paired_pc")
        shot("devices-4-paired")
        rule.onNodeWithTag("paired_pc").assertIsDisplayed()
        rule.waitUntil(10_000) { service.syncs >= 1 } // pairing triggers one sync
        rule.onNodeWithTag("sync_now").performClick()
        rule.waitUntil(10_000) { service.syncs >= 2 }
        assertTrue(rule.onAllNodesWithTag("pairing_fingerprint").fetchSemanticsNodes().isEmpty())
    }

    @Test fun forgetting_the_pc_returns_to_the_pairing_card() {
        val service = FakeSyncService().apply { pc = FakeSyncService.PC }
        val vm = DevicesViewModel(service)
        rule.setContent { RevaTheme { DevicesScreen(vm, onScan = {}, onBack = {}) } }
        vm.load()
        waitFor("paired_pc")
        // Forgetting only removes the PC from the phone; the copy must say so and point at Revoke on the PC.
        rule.onNodeWithTag("forget_note")
            .assertTextEquals("Removes this PC from the phone. To fully cut access, also click Revoke on the PC.")
        rule.onNodeWithTag("forget_pc").performClick()
        waitFor("not_paired")
        assertEquals(1, service.forgotten)
    }

    @Test fun differing_amounts_show_a_banner_and_keep_mine_resolves_it() {
        val repo = Samples.populated().apply {
            conflicts = mutableListOf(Conflict(7, "Corner Cafe", "amount_minor", "USD", -1_111, -2_222))
        }
        rule.setContent { RevaTheme { RevaRoot(repo, "0.1.0", onShare = { _, _ -> }) } }
        rule.onNodeWithTag("tab_finance").performClick()
        waitFor("finance_list")
        rule.onNodeWithTag("finance_list").performScrollToNode(androidx.compose.ui.test.hasTestTag("conflict_banner"))
        shot("finance-conflict-banner")
        rule.onNodeWithTag("conflict_banner").assertIsDisplayed()
        rule.onNode(hasText("This phone: -$11.11 · PC: -$22.22")).assertIsDisplayed()
        rule.onNodeWithTag("keep_mine_7").performClick()
        rule.waitUntil(10_000) { rule.onAllNodesWithTag("conflict_banner").fetchSemanticsNodes().isEmpty() }
        assertEquals(listOf(7L to true), repo.resolved)
    }
}
