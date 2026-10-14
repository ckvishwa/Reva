@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package app.reva.sync

import app.reva.testing.FakeSyncService
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class MemorySettings(override var enabled: Boolean = true) : AutoSyncSettings

/** SYNC-1e: sync on foreground and every 60 s while the app is open, only when paired and switched on. */
class AutoSyncControllerTest {
    private class World(scope: TestScope, paired: Boolean = true, enabled: Boolean = true) {
        var seconds = 1_000_000L
        val service = FakeSyncService().apply {
            if (paired) pc = FakeSyncService.PC.copy(lastSyncAtSeconds = null)
            nowSeconds = { seconds }
        }
        val settings = MemorySettings(enabled)
        val controller = AutoSyncController(service, settings, scope, intervalMillis = 60_000, tickMillis = 30_000, nowSeconds = { seconds })
    }

    @Test fun it_syncs_as_soon_as_the_app_comes_to_the_front() = runTest {
        val w = World(this)
        w.controller.onForeground()
        runCurrent()

        assertEquals(1, w.service.syncs)
        assertEquals("Synced just now", w.controller.status.value.text)
        w.controller.onBackground()
    }

    @Test fun it_repeats_every_sixty_seconds_while_in_front() = runTest {
        val w = World(this)
        w.controller.onForeground()
        runCurrent()

        advanceTimeBy(59_000)
        runCurrent()
        assertEquals(1, w.service.syncs)
        advanceTimeBy(1_001)
        runCurrent()
        assertEquals(2, w.service.syncs)
        advanceTimeBy(60_000)
        runCurrent()
        assertEquals(3, w.service.syncs)
        w.controller.onBackground()
    }

    @Test fun it_stops_when_the_app_goes_to_the_background() = runTest {
        val w = World(this)
        w.controller.onForeground()
        runCurrent()
        w.controller.onBackground()

        advanceTimeBy(300_000)
        runCurrent()

        assertEquals(1, w.service.syncs)
    }

    @Test fun coming_to_the_front_twice_does_not_start_two_loops() = runTest {
        val w = World(this)
        w.controller.onForeground()
        w.controller.onForeground()
        runCurrent()
        advanceTimeBy(60_001)
        runCurrent()

        assertEquals(2, w.service.syncs)
        w.controller.onBackground()
    }

    @Test fun nothing_syncs_when_no_pc_is_paired() = runTest {
        val w = World(this, paired = false)
        w.controller.onForeground()
        runCurrent()
        advanceTimeBy(120_000)
        runCurrent()

        assertEquals(0, w.service.syncs)
        assertNull(w.controller.status.value.text)
        w.controller.onBackground()
    }

    @Test fun nothing_syncs_when_the_setting_is_off_and_it_resumes_when_turned_on() = runTest {
        val w = World(this, enabled = false)
        w.controller.onForeground()
        runCurrent()
        advanceTimeBy(120_000)
        runCurrent()
        assertEquals(0, w.service.syncs)
        assertEquals("Not synced yet", w.controller.status.value.text)

        w.controller.setEnabled(true)
        runCurrent()

        assertEquals(1, w.service.syncs)
        assertTrue(w.settings.enabled)
        w.controller.onBackground()
    }

    @Test fun the_setting_is_remembered_and_defaults_on() = runTest {
        val w = World(this)
        assertTrue(w.controller.enabled.value)

        w.controller.setEnabled(false)

        assertFalse(w.settings.enabled)
        assertFalse(w.controller.enabled.value)
    }

    @Test fun a_failed_attempt_is_quiet_and_the_next_interval_tries_again() = runTest {
        val w = World(this)
        w.service.syncResult = SyncException(SyncFailure.Unreachable, "Could not reach the PC.")
        w.controller.onForeground()
        runCurrent()

        assertEquals(1, w.service.syncs)
        assertTrue(w.controller.status.value.needsAttention)

        w.service.syncResult = SyncReport(0, 1, 1, 0, 0, 0)
        advanceTimeBy(60_001)
        runCurrent()

        assertEquals(2, w.service.syncs)
        assertFalse(w.controller.status.value.needsAttention)
        w.controller.onBackground()
    }

    @Test fun the_status_text_ticks_forward_without_another_sync() = runTest {
        val w = World(this)
        w.controller.onForeground()
        runCurrent()
        assertEquals("Synced just now", w.controller.status.value.text)

        w.seconds += 3 * 60
        advanceTimeBy(31_000)
        runCurrent()

        assertEquals("Synced 3 min ago", w.controller.status.value.text)
        w.controller.onBackground()
    }

    @Test fun a_manual_sync_updates_the_status_when_asked() = runTest {
        val w = World(this)
        w.service.syncNow()
        w.controller.refreshStatus()

        assertEquals("Synced just now", w.controller.status.value.text)
    }

    @Test fun the_status_wording_covers_minutes_hours_and_days() {
        val pc = FakeSyncService.PC
        fun at(secondsAgo: Long) = SyncStatusText.format(pc.copy(lastSyncAtSeconds = 1_000_000 - secondsAgo), 1_000_000)

        assertEquals("Synced just now", at(20))
        assertEquals("Synced 5 min ago", at(300))
        assertEquals("Synced 2 h ago", at(2 * 3600))
        assertEquals("Synced 3 d ago", at(3 * 86_400))
        assertEquals("Not synced yet", SyncStatusText.format(pc.copy(lastSyncAtSeconds = null), 1_000_000))
        assertNull(SyncStatusText.format(null, 1_000_000))
    }
}
