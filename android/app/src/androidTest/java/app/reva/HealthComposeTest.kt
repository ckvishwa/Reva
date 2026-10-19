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
import android.content.Context
import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.ui.test.onAllNodesWithTag
import app.reva.data.HealthDaily
import app.reva.data.HealthImportReport
import app.reva.healthconnect.DailyHeartRate
import app.reva.healthconnect.DailySteps
import app.reva.healthconnect.HealthConnectGateway
import app.reva.healthconnect.HealthConnectStatus
import app.reva.healthconnect.HealthConnectType
import app.reva.ui.health.HealthConnectUi
import java.time.LocalDate
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

    @Test fun health_connect_card_shows_per_type_grants_imports_and_same_day_conflict() {
        val repo = object : HealthRepository {
            var imported = 0
            override suspend fun daily(date: String) = Outcome.Ok(
                HealthDaily(date, 0, 0, 0, null, 0, 0, 2, steps = 5000, stepsCount = 2, stepsSource = "manual",
                    stepsConflict = true, stepsManual = 5000, stepsHealthConnect = 7000),
            )
            override suspend fun weekly(endDate: String) = Outcome.Ok(HealthWeekly("2026-10-12", endDate, 0, 0, 0, 0, 0, 0, 0, 2, 5000, 1, stepsConflictDates = listOf(endDate)))
            override suspend fun records(date: String) = Outcome.Ok(emptyList<HealthRecord>())
            override suspend fun schedules(date: String) = Outcome.Ok(emptyList<MedicationSchedule>())
            override suspend fun command(kind: String, payload: JSONObject) = Outcome.Ok(Unit)
            override suspend fun importData(format: String, bytes: ByteArray, dryRun: Boolean): Outcome<HealthImportReport> {
                imported++
                return Outcome.Ok(HealthImportReport(1, 0, 0, emptyList(), false))
            }
        }
        val gateway = object : HealthConnectGateway {
            override fun status() = HealthConnectStatus.Available
            override suspend fun grantedTypes() = setOf(HealthConnectType.Steps)
            override suspend fun dailySteps(start: LocalDate, end: LocalDate) = listOf(DailySteps(end, 7000, setOf("com.example.watch")))
            override suspend fun dailyHeartRate(start: LocalDate, end: LocalDate) = emptyList<DailyHeartRate>()
        }
        val contract = object : ActivityResultContract<Set<String>, Set<String>>() {
            override fun createIntent(context: Context, input: Set<String>) = Intent()
            override fun parseResult(resultCode: Int, intent: Intent?) = emptySet<String>()
        }
        val ui = HealthConnectUi(gateway, { it.permission }, contract, openSettings = {})
        rule.setContent { RevaTheme { HealthScreen(repo, healthConnect = ui) } }
        rule.onNodeWithTag("health_steps_conflict").assertIsDisplayed()
        rule.onNodeWithTag("health_screen").performScrollToNode(androidx.compose.ui.test.hasTestTag("health_connect_card"))
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("health_connect_state_Steps").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Steps: allowed").assertIsDisplayed()
        rule.onNodeWithText("Heart rate: not allowed").assertExists()
        rule.onNodeWithTag("health_connect_allow_HeartRate").assertExists()
        rule.onNodeWithTag("health_connect_import").performScrollTo().performClick()
        rule.waitUntil(5_000) { repo.imported == 1 }
        rule.waitUntil(5_000) { rule.onAllNodesWithTag("health_connect_result").fetchSemanticsNodes().isNotEmpty() }
    }
}
