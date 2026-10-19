package app.reva

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.HealthDaily
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import app.reva.ui.health.HealthScreen
import app.reva.ui.theme.RevaTheme
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HealthComposeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun manual_workout_is_submitted_and_daily_kernel_result_is_shown() {
        val repo = object : HealthRepository {
            val commands = mutableListOf<Pair<String, String>>()
            override suspend fun daily(date: String) = Outcome.Ok(HealthDaily(date, 35, 440, 1, 72500, 1, 1, 6, 1, 1))
            override suspend fun weekly(endDate: String) = Outcome.Ok(HealthWeekly("2026-10-10", endDate, 35, 1, 440, 1, 1, 7, 1, 6))
            override suspend fun records(date: String) = Outcome.Ok(emptyList<HealthRecord>())
            override suspend fun schedules(date: String) = Outcome.Ok(emptyList<MedicationSchedule>())
            override suspend fun command(kind: String, payload: JSONObject): Outcome<Unit> {
                commands += kind to payload.toString()
                return Outcome.Ok(Unit)
            }
        }
        rule.setContent { RevaTheme { HealthScreen(repo) } }
        rule.onNodeWithText("Workout 35 min · Sleep 440 min · Meals 1").assertIsDisplayed()
        rule.onNodeWithTag("health_screen").performScrollToNode(androidx.compose.ui.test.hasText("Log workout"))
        rule.onNodeWithText("Activity").performTextInput("Walk")
        rule.onNodeWithText("Minutes").performTextInput("35")
        rule.onNodeWithTag("health_log_workout").performScrollTo().performClick()
        rule.waitUntil(5_000) { repo.commands.isNotEmpty() }
        assertEquals("workout.log", repo.commands.single().first)
        assertEquals("Walk", JSONObject(repo.commands.single().second).getString("activity"))
    }
}
