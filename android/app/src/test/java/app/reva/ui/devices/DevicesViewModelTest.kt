@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package app.reva.ui.devices

import app.reva.sync.PairPoll
import app.reva.sync.SyncException
import app.reva.sync.SyncFailure
import app.reva.sync.SyncReport
import app.reva.testing.FakeSyncService
import app.reva.ui.MainDispatcherTest
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private val PC = FakeSyncService.PC

class DevicesViewModelTest : MainDispatcherTest() {
    private fun vm(service: FakeSyncService, onSynced: () -> Unit = {}) =
        DevicesViewModel(service, onSynced, pollIntervalMillis = 1_000, maxWaitMillis = 5_000, nowSeconds = { 1_000_000 })

    @Test fun load_shows_the_paired_pc_and_when_it_last_synced() = runTest {
        val service = FakeSyncService().apply { pc = PC.copy(lastSyncAtSeconds = 1_000_000 - 5 * 60) }
        val vm = vm(service)
        vm.load()
        assertTrue(vm.state.value.loaded)
        assertEquals(PC.host, vm.state.value.pc?.host)
        assertEquals("Synced 5 min ago", vm.state.value.lastSyncText)
    }

    @Test fun pairing_shows_the_digits_waits_for_the_pc_then_pairs_and_syncs_once() = runTest {
        val service = FakeSyncService().apply { polls.addAll(listOf(PairPoll.Pending, PairPoll.Pending, PairPoll.Approved(PC))) }
        var synced = 0
        val vm = vm(service) { synced++ }
        vm.onPairingCode("REVA-PAIR1:xxxx")
        assertEquals(DevicesPhase.WaitingForApproval, vm.state.value.phase)
        assertEquals("123456", vm.state.value.fingerprint)
        advanceTimeBy(1_100)
        assertEquals(DevicesPhase.WaitingForApproval, vm.state.value.phase)
        advanceTimeBy(2_200)
        val s = vm.state.value
        assertEquals(DevicesPhase.Idle, s.phase)
        assertNull("the digits go away once paired", s.fingerprint)
        assertNotNull(s.pc)
        assertEquals(1, service.syncs)
        assertEquals(1, synced)
        assertFalse(s.isError)
    }

    @Test fun a_refusal_on_the_pc_pairs_nothing() = runTest {
        val service = FakeSyncService().apply { polls.add(PairPoll.Denied) }
        val vm = vm(service)
        vm.onPairingCode("x")
        val s = vm.state.value
        assertEquals(DevicesPhase.Idle, s.phase)
        assertNull(s.pc)
        assertTrue(s.isError)
        assertEquals(0, service.syncs)
    }

    @Test fun a_bad_or_expired_code_shows_the_reason_and_stays_unpaired() = runTest {
        val message = "This pairing code has expired. Show a new one on the PC."
        val service = FakeSyncService().apply { startError = SyncException(SyncFailure.Other, message) }
        val vm = vm(service)
        vm.onPairingCode("old")
        assertEquals(message, vm.state.value.message)
        assertTrue(vm.state.value.isError)
        assertEquals(DevicesPhase.Idle, vm.state.value.phase)
    }

    @Test fun the_wait_for_approval_has_a_limit_and_cancels_the_session() = runTest {
        val service = FakeSyncService()
        val vm = vm(service)
        vm.onPairingCode("x")
        advanceTimeBy(7_000)
        assertEquals(DevicesPhase.Idle, vm.state.value.phase)
        assertTrue(vm.state.value.isError)
        assertEquals(1, service.cancelled)
    }

    @Test fun cancelling_while_waiting_stops_polling() = runTest {
        val service = FakeSyncService()
        val vm = vm(service)
        vm.onPairingCode("x")
        vm.cancelPairing()
        advanceTimeBy(10_000)
        assertEquals(DevicesPhase.Idle, vm.state.value.phase)
        assertNull(vm.state.value.fingerprint)
        assertFalse("cancelling is not an error", vm.state.value.isError)
    }

    @Test fun a_second_pairing_tap_while_busy_is_ignored() = runTest {
        val service = FakeSyncService()
        val vm = vm(service)
        vm.onPairingCode("x")
        vm.onPairingCode("y")
        assertEquals(1, service.started)
    }

    @Test fun sync_now_reports_what_moved_and_refreshes_the_screens() = runTest {
        val service = FakeSyncService().apply {
            pc = PC
            syncResult = SyncReport(2, 3, 3, 0, 1, 0)
        }
        var synced = 0
        val vm = vm(service) { synced++ }
        vm.load()
        vm.syncNow()
        val message = vm.state.value.message.orEmpty()
        assertTrue(message, message.contains("sent 2") && message.contains("received 3") && message.contains("1 amount(s) differ"))
        assertEquals(1, synced)
        assertFalse(vm.state.value.isError)
    }

    @Test fun nothing_to_send_or_receive_says_so() = runTest {
        val service = FakeSyncService().apply {
            pc = PC
            syncResult = SyncReport(0, 0, 0, 0, 0, 0)
        }
        val vm = vm(service)
        vm.load()
        vm.syncNow()
        assertEquals("Already up to date.", vm.state.value.message)
    }

    @Test fun a_pc_that_no_longer_accepts_this_phone_is_explained_and_the_screens_are_not_refreshed() = runTest {
        val service = FakeSyncService().apply {
            pc = PC
            syncResult = SyncException(SyncFailure.Unauthorized, "Your PC no longer accepts this phone. Pair again to sync.")
        }
        var synced = 0
        val vm = vm(service) { synced++ }
        vm.load()
        vm.syncNow()
        assertTrue(vm.state.value.isError)
        assertTrue(vm.state.value.message.orEmpty().contains("no longer accepts"))
        assertEquals(0, synced)
        assertNotNull("the record stays so the user can forget it or pair again", vm.state.value.pc)
    }

    @Test fun forgetting_clears_the_pc() = runTest {
        val service = FakeSyncService().apply { pc = PC }
        val vm = vm(service)
        vm.load()
        vm.forget()
        assertNull(vm.state.value.pc)
        assertEquals(1, service.forgotten)
    }
}
