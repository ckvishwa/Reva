package app.reva

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import app.reva.brain.ModeConfig
import app.reva.brain.ModeController
import app.reva.brain.ModeSettings
import app.reva.ui.more.ModeSettingsCard
import org.junit.Rule
import org.junit.Test

class ModeSettingsUiTest {
    @get:Rule val rule = createComposeRule()

    @Test fun the_current_mode_cloud_choice_and_key_entry_are_visible() {
        val modes = ModeController(object : ModeSettings {
            override fun load() = ModeConfig()
            override fun save(config: ModeConfig) = Unit
        })
        rule.setContent { ModeSettingsCard(modes, saveKey = { true }, clearKey = {}) }

        rule.onNodeWithTag("more_modes").assertExists()
        rule.onNodeWithTag("mode_current").assertExists()
        rule.onNodeWithTag("hosted_enabled").assertExists()
        rule.onNodeWithTag("hosted_api_key").assertExists()
    }
}
