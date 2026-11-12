package app.reva.brain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModeControllerTest {
    private class Store(var saved: ModeConfig = ModeConfig()) : ModeSettings {
        override fun load() = saved
        override fun save(config: ModeConfig) { saved = config }
    }

    @Test fun defaults_to_offline_with_no_cloud_processing() {
        val modes = ModeController(Store())

        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        assertFalse(modes.state.value.cloudAllowed)
    }

    @Test fun paired_mode_requires_a_trusted_reachable_pc() {
        val modes = ModeController(Store())
        modes.availability(ModeAvailability(pcTrusted = true, pcReachable = true))
        assertEquals(RunMode.Paired, modes.state.value.mode)

        modes.availability(ModeAvailability(pcTrusted = true, pcReachable = false))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
    }

    @Test fun a_pc_outage_does_not_silently_turn_on_cloud() {
        val modes = ModeController(Store())
        modes.configure(ModeConfig(hostedEnabled = true))
        modes.availability(ModeAvailability(pcTrusted = true, pcReachable = false, networkAvailable = true, hostedKeyConfigured = true))

        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        assertFalse(modes.state.value.cloudAllowed)
    }

    @Test fun opted_in_fallback_is_visible_and_requires_network_and_a_key() {
        val modes = ModeController(Store())
        modes.configure(ModeConfig(hostedEnabled = true, autoHostedFallback = true, financeConsent = true, memoryConsent = true))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))

        assertEquals(RunMode.Standalone, modes.state.value.mode)
        assertTrue(modes.state.value.cloudAllowed)
        assertTrue(modes.state.value.label.contains("Standalone"))

        modes.availability(ModeAvailability(networkAvailable = false))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
    }

    @Test fun hosted_timeout_stays_off_until_explicit_retry() {
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        assertEquals(RunMode.Standalone, modes.state.value.mode)

        modes.hostedTimedOut()
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        modes.configure(modes.config().copy(financeConsent = true))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        modes.retryHosted()
        assertEquals(RunMode.Standalone, modes.state.value.mode)
    }

    @Test fun revocation_and_cloud_disable_are_persisted() {
        val store = Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true))
        val modes = ModeController(store)
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        modes.disableCloud()

        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        assertFalse(store.saved.hostedEnabled)
        assertEquals(RunMode.OfflineLite, ModeController(store).state.value.mode)
    }

    @Test fun restart_never_assumes_network_or_pc_reachability() {
        val store = Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true, memoryConsent = true))
        val restarted = ModeController(store)

        assertEquals(RunMode.OfflineLite, restarted.state.value.mode)
        restarted.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        assertEquals(RunMode.Standalone, restarted.state.value.mode)
    }

    @Test fun either_domain_consent_off_keeps_free_form_hosted_reasoning_off() {
        val modes = ModeController(Store(ModeConfig(preferred = RunMode.Standalone, hostedEnabled = true, financeConsent = true)))
        modes.availability(ModeAvailability(networkAvailable = true, hostedKeyConfigured = true))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
        modes.configure(modes.config().copy(financeConsent = false, memoryConsent = true))
        assertEquals(RunMode.OfflineLite, modes.state.value.mode)
    }
}
