package app.reva.brain

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class RunMode { Paired, Standalone, OfflineLite }

data class ModeConfig(
    val preferred: RunMode = RunMode.Paired,
    val hostedEnabled: Boolean = false,
    val autoHostedFallback: Boolean = false,
    val financeConsent: Boolean = false,
    val memoryConsent: Boolean = false,
    val model: String = "claude-opus-5-5",
)

interface ModeSettings {
    fun load(): ModeConfig
    fun save(config: ModeConfig)
}

data class ModeAvailability(
    val pcTrusted: Boolean = false,
    val pcReachable: Boolean = false,
    val networkAvailable: Boolean = false,
    val hostedKeyConfigured: Boolean = false,
)

data class ModeStatus(val mode: RunMode, val label: String, val reason: String, val cloudAllowed: Boolean, val keyConfigured: Boolean, val retryRequired: Boolean, val config: ModeConfig)

/** Mode is derived from fresh reachability, explicit owner choice and provider readiness. A restart begins
 * with unknown reachability, so saved settings alone cannot cause network egress. */
class ModeController(private val settings: ModeSettings) {
    private var config = settings.load()
    private var available = ModeAvailability()
    private var hostedTimedOut = false
    private val mutable = MutableStateFlow(resolve())
    val state: StateFlow<ModeStatus> = mutable.asStateFlow()

    fun configure(next: ModeConfig) {
        config = next
        settings.save(next)
        mutable.value = resolve()
    }

    fun availability(next: ModeAvailability) {
        available = next
        mutable.value = resolve()
    }

    fun hostedTimedOut() {
        hostedTimedOut = true
        mutable.value = resolve()
    }

    fun retryHosted() {
        hostedTimedOut = false
        mutable.value = resolve()
    }

    fun disableCloud() = configure(config.copy(hostedEnabled = false, autoHostedFallback = false))

    fun config(): ModeConfig = config

    private fun resolve(): ModeStatus {
        val paired = available.pcTrusted && available.pcReachable
        // Free-form text has no infallible local domain classifier. Both domain consents are required
        // before any hosted question can leave the phone; either revocation closes the egress path.
        val hosted = config.hostedEnabled && config.financeConsent && config.memoryConsent &&
            available.hostedKeyConfigured && available.networkAvailable && !hostedTimedOut
        val mode = when (config.preferred) {
            RunMode.OfflineLite -> RunMode.OfflineLite
            RunMode.Standalone -> if (hosted) RunMode.Standalone else RunMode.OfflineLite
            RunMode.Paired -> when {
                paired -> RunMode.Paired
                config.autoHostedFallback && hosted -> RunMode.Standalone
                else -> RunMode.OfflineLite
            }
        }
        val reason = when (mode) {
            RunMode.Paired -> "Connected to your trusted PC."
            RunMode.Standalone -> "Using the configured hosted model; your question may leave this phone."
            RunMode.OfflineLite -> when {
                hostedTimedOut -> "Hosted reasoning timed out; advanced reasoning is unavailable offline."
                config.hostedEnabled && (!config.financeConsent || !config.memoryConsent) ->
                    "Hosted questions require both Finance and Memory consent; advanced reasoning is unavailable offline."
                config.preferred == RunMode.Paired && !paired -> "PC unavailable; advanced reasoning is unavailable offline."
                else -> "Advanced reasoning is unavailable offline."
            }
        }
        return ModeStatus(mode, mode.name.replace("OfflineLite", "Offline-lite"), reason, mode == RunMode.Standalone, available.hostedKeyConfigured, hostedTimedOut, config)
    }
}
