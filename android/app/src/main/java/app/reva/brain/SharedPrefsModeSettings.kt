package app.reva.brain

import android.content.SharedPreferences

/** Non-secret mode and consent choices. The API key is stored separately under Android Keystore. */
class SharedPrefsModeSettings(private val prefs: SharedPreferences) : ModeSettings {
    override fun load(): ModeConfig {
        val preferred = RunMode.entries.firstOrNull { it.name == prefs.getString("preferred", null) } ?: RunMode.Paired
        return ModeConfig(
            preferred = preferred,
            hostedEnabled = prefs.getBoolean("hosted_enabled", false),
            autoHostedFallback = prefs.getBoolean("auto_fallback", false),
            financeConsent = prefs.getBoolean("finance_consent", false),
            memoryConsent = prefs.getBoolean("memory_consent", false),
            model = prefs.getString("model", null)?.takeIf { it.matches(Regex("claude-[a-z0-9-]{1,80}")) }
                ?: ModeConfig().model,
        )
    }

    override fun save(config: ModeConfig) {
        require(config.model.matches(Regex("claude-[a-z0-9-]{1,80}"))) { "Choose a supported Claude model ID." }
        prefs.edit()
            .putString("preferred", config.preferred.name)
            .putBoolean("hosted_enabled", config.hostedEnabled)
            .putBoolean("auto_fallback", config.autoHostedFallback)
            .putBoolean("finance_consent", config.financeConsent)
            .putBoolean("memory_consent", config.memoryConsent)
            .putString("model", config.model)
            .apply()
    }
}
