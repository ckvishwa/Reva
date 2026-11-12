package app.reva

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.testing.FakeFinanceRepository
import app.reva.testing.FakeGymRepository
import app.reva.ui.RevaRoot
import app.reva.ui.theme.RevaTheme
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** APK-01: the five-destination bar, the Life hub, back navigation and state restoration (AR-APK-001). */
@RunWith(AndroidJUnit4::class)
class LifeNavigationUiTest {
    @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

    private val context: Context = ApplicationProvider.getApplicationContext()
    private fun clearPins() = context.getSharedPreferences("reva_life", Context.MODE_PRIVATE).edit().clear().commit()

    @Before fun setUp() { clearPins() }
    @After fun tearDown() { clearPins() }

    private fun count(tag: String) = rule.onAllNodesWithTag(tag).fetchSemanticsNodes().size

    private fun back() {
        rule.runOnUiThread { rule.activity.onBackPressedDispatcher.onBackPressed() }
        rule.waitForIdle()
    }

    private fun app() {
        rule.setContent {
            RevaTheme { RevaRoot(FakeFinanceRepository(), "0.1.0", onShare = { _, _ -> }, gymRepository = FakeGymRepository()) }
        }
    }

    @Test fun the_bar_has_today_talk_life_more_and_no_plan_or_domain_tabs() {
        app()
        for (tag in listOf("tab_today", "tab_talk", "tab_life", "tab_more")) rule.onNodeWithTag(tag).assertIsDisplayed()
        for (tag in listOf("tab_plan", "tab_finance", "tab_health", "tab_gym")) assertEquals(tag, 0, count(tag))
    }

    @Test fun life_lists_only_the_domains_this_build_has_and_each_opens_its_screen() {
        app()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_hub").assertIsDisplayed()
        rule.onNodeWithTag("life_finance").assertIsDisplayed()
        rule.onNodeWithTag("life_gym").assertIsDisplayed()
        assertEquals("no Health repository was given, so Health is not offered", 0, count("life_health"))

        rule.onNodeWithTag("life_finance").performClick()
        rule.onNodeWithTag("finance_list").assertIsDisplayed()
        rule.onNodeWithTag("life_back").performClick()
        rule.onNodeWithTag("life_gym").performClick()
        rule.onNodeWithTag("gym_host").assertIsDisplayed()
    }

    @Test fun back_from_a_domain_returns_to_the_hub_and_the_bar_button_does_the_same() {
        app()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_gym").performClick()
        rule.onNodeWithTag("gym_host").assertIsDisplayed()
        back()
        rule.onNodeWithTag("life_hub").assertIsDisplayed()
        rule.onNodeWithTag("tab_life").assertIsSelected()

        rule.onNodeWithTag("life_finance").performClick()
        rule.onNodeWithTag("life_back").performClick()
        rule.onNodeWithTag("life_hub").assertIsDisplayed()
    }

    @Test fun switching_tabs_keeps_the_open_domain_and_tapping_life_again_returns_to_the_hub() {
        app()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_gym").performClick()
        rule.onNodeWithTag("tab_more").performClick()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("gym_host").assertIsDisplayed()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_hub").assertIsDisplayed()
    }

    @Test fun the_selected_tab_and_open_domain_survive_recreation() {
        val tester = StateRestorationTester(rule)
        tester.setContent {
            RevaTheme { RevaRoot(FakeFinanceRepository(), "0.1.0", onShare = { _, _ -> }, gymRepository = FakeGymRepository()) }
        }
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_gym").performClick()
        tester.emulateSavedInstanceStateRestore()
        rule.onNodeWithTag("gym_host").assertIsDisplayed()
        rule.onNodeWithTag("tab_life").assertIsSelected()
    }

    @Test fun unpinning_an_entry_moves_it_below_the_pinned_ones_and_is_remembered() {
        app()
        rule.onNodeWithTag("tab_life").performClick()
        rule.onNodeWithTag("life_finance_pin").performClick()
        rule.onNodeWithText("Pin").assertIsDisplayed()
        assertEquals("health,gym", context.getSharedPreferences("reva_life", Context.MODE_PRIVATE).getString("pinned", null))
        val finance = rule.onNodeWithTag("life_finance").fetchSemanticsNode().positionInRoot.y
        val gym = rule.onNodeWithTag("life_gym").fetchSemanticsNode().positionInRoot.y
        assertEquals("Gym, still pinned, is listed above Finance", true, gym < finance)
    }
}
