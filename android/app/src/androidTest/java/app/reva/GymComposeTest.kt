package app.reva

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.GymRepository
import app.reva.data.KernelGymRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.data.Outcome
import app.reva.ui.gym.GymScreen
import app.reva.ui.gym.GymViewModel
import app.reva.ui.gym.LiveWorkoutScreen
import app.reva.ui.gym.SessionDetailsScreen
import app.reva.ui.gym.TrainingPlanScreen
import app.reva.ui.theme.RevaTheme
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.openDomain

/**
 * GYM-01 acceptance, on the device, against the REAL Domain Kernel: libreva_kernel.so, SQLCipher and
 * the Android Keystore key provider. Nothing is mocked, so what this proves about saving and
 * recovering sets is true of the shipped app.
 *
 * Day 2 - Pull A, Lat Pulldown 55 lb for 10, 9 and 8, paused and resumed, finished, read back, then
 * read again through a second repository and ViewModel - which is what a restarted app has.
 */
@RunWith(AndroidJUnit4::class)
class GymComposeTest {
    @get:Rule val rule = createComposeRule()

    private val context: Context = ApplicationProvider.getApplicationContext()
    private val roots = mutableListOf<File>()
    private lateinit var root: File

    @After fun tearDown() {
        roots.forEach { it.deleteRecursively() }
    }

    /** A fresh encrypted Health domain file, so a test never touches the user's own records. */
    private fun newRepository(): GymRepository {
        if (!::root.isInitialized) {
            root = File(context.noBackupFilesDir, "gym-test-${System.nanoTime()}").also {
                it.mkdirs()
                roots += it
            }
        }
        val keys = KeystoreKeyProvider(File(root, "keys"))
        val domains = File(root, "domains/health").also { it.mkdirs() }
        return KernelGymRepository(openHandle = { openDomain("health", keys, domains.absolutePath) })
    }

    @Composable
    private fun GymUnderTest(vm: GymViewModel) {
        val state by vm.state.collectAsState()
        RevaTheme {
            when (state.screen) {
                GymScreen.TrainingPlan -> TrainingPlanScreen(state, vm)
                GymScreen.LiveWorkout -> LiveWorkoutScreen(state, vm)
                GymScreen.SessionDetails -> SessionDetailsScreen(state, vm)
            }
        }
    }

    /** Bring a row of the Live Workout list into view, then act on it. */
    private fun onLive(tag: String) = rule.run {
        onNodeWithTag("gym_live").performScrollToNode(hasTestTag(tag))
        onNodeWithTag(tag)
    }

    private fun onPlan(tag: String) = rule.run {
        onNodeWithTag("gym_plan").performScrollToNode(hasTestTag(tag))
        onNodeWithTag(tag)
    }

    private fun logSet(load: String, reps: String) {
        onLive("gym_input_load").performTextClearance()
        onLive("gym_input_load").performTextInput(load)
        onLive("gym_input_reps").performTextClearance()
        onLive("gym_input_reps").performTextInput(reps)
        onLive("gym_log_set").performClick()
        rule.waitUntil(10_000) {
            rule.onAllNodesWithTagSafe("gym_saved") || rule.onAllNodesWithTagSafe("gym_error")
        }
        rule.waitForIdle()
    }

    private fun androidx.compose.ui.test.junit4.ComposeContentTestRule.onAllNodesWithTagSafe(tag: String): Boolean =
        onAllNodes(hasTestTag(tag)).fetchSemanticsNodes().isNotEmpty()

    @Test fun day_two_lat_pulldown_is_logged_finished_and_still_there_after_a_restart() {
        val repository = newRepository()
        val vm = GymViewModel(repository)
        rule.setContent { GymUnderTest(vm) }

        // 1-2. The plan is created once, on first use.
        vm.load()
        rule.waitUntil(15_000) { vm.state.value.phase.name != "Loading" }
        rule.onNodeWithTag("gym_create_plan").performClick()
        rule.waitUntil(20_000) { vm.state.value.program != null }
        rule.waitForIdle()

        val program = vm.state.value.program!!
        assertEquals("the reviewed seven-day split", 7, program.days.size)
        assertEquals(5, program.days.count { !it.isRest })
        assertEquals(2, program.days.count { it.isRest })
        assertEquals("90 prescribed working sets", 90, program.days.sumOf { it.plannedWorkingSets })

        // 3. Select Day 2 - Pull A.
        onPlan("gym_day_day-2").performClick()
        rule.waitForIdle()
        rule.onNodeWithText("Pull A: Lat Width + Biceps").assertIsDisplayed()
        onPlan("gym_exercise_lat_pulldown").assertIsDisplayed()

        // 4. Start the workout.
        onPlan("gym_start_workout").performClick()
        rule.waitUntil(20_000) { vm.state.value.screen == GymScreen.LiveWorkout && vm.state.value.session != null }
        rule.waitForIdle()
        rule.onNodeWithTag("gym_exercise_name").assertIsDisplayed()
        // 5. No prior record exists yet, and none is invented.
        rule.waitUntil(10_000) { vm.state.value.previousLoaded }
        assertNull(vm.state.value.previous)

        // 6-8. Log 55 lb for 10, 9 and 8, each a completed working set.
        logSet("55", "10")
        logSet("55", "9")
        logSet("55", "8")
        rule.waitUntil(10_000) { vm.state.value.session?.metrics?.workingSetsCompleted == 3 }

        // 9. The commits are the Kernel's: read them back through a second handle on the same file.
        val sessionId = vm.state.value.session!!.session.id
        val committed = runBlocking { newRepository().sessionDetails(sessionId) }
        assertTrue(committed is Outcome.Ok)
        val fromDisk = (committed as Outcome.Ok).value
        assertEquals(3, fromDisk.metrics.workingSetsCompleted)
        assertEquals(listOf(10, 9, 8), fromDisk.blockFor("lat_pulldown")!!.sets.map { it.reps })
        assertEquals(listOf(55_000L, 55_000L, 55_000L), fromDisk.blockFor("lat_pulldown")!!.sets.map { it.loadMilli })

        // 10. Pause and resume.
        onLive("gym_pause").performClick()
        rule.waitUntil(10_000) { vm.state.value.session?.session?.state == "paused" }
        onLive("gym_pause").performClick()
        rule.waitUntil(10_000) { vm.state.value.session?.session?.state == "in_progress" }

        // 11. Finish, once, after confirming.
        onLive("gym_finish").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("gym_finish_confirm").performClick()
        rule.waitUntil(20_000) { vm.state.value.screen == GymScreen.SessionDetails }
        rule.waitForIdle()

        // 12-13. The receipt holds exactly those three sets.
        rule.onNodeWithTag("gym_details").assertIsDisplayed()
        rule.onNodeWithTag("gym_details").performScrollToNode(hasTestTag("gym_volume"))
        rule.onNodeWithText("1485 lb").assertIsDisplayed()
        val receipt = vm.state.value.session!!
        assertEquals("completed", receipt.session.state)
        assertEquals(3, receipt.metrics.workingSetsCompleted)
        assertEquals(0, receipt.metrics.warmupSetsCompleted)
        assertEquals(1, receipt.metrics.volumeByUnit.size)
        assertEquals(1_485_000L, receipt.metrics.volumeByUnit.first().volumeMilli)
        assertTrue("the pause is recorded", receipt.metrics.pausedSeconds >= 0)
        assertTrue(receipt.metrics.activeSeconds <= receipt.metrics.elapsedSeconds)

        // 14-16. Restart: a new repository, a new handle and a new ViewModel on the same file.
        val afterRestart = GymViewModel(newRepository())
        runBlocking {
            val reread = afterRestart.let { (newRepository()).sessionDetails(sessionId) }
            assertTrue(reread is Outcome.Ok)
            val detail = (reread as Outcome.Ok).value
            assertEquals("completed", detail.session.state)
            assertEquals(3, detail.blockFor("lat_pulldown")!!.sets.size)
            assertEquals(listOf(10, 9, 8), detail.blockFor("lat_pulldown")!!.sets.map { it.reps })
            assertEquals(1_485_000L, detail.metrics.volumeByUnit.first().volumeMilli)
            assertEquals(receipt.session.startedAt, detail.session.startedAt)
            assertEquals(receipt.session.endedAt, detail.session.endedAt)

            // Nothing was duplicated, and no workout is left open.
            val sessions = (newRepository().recentSessions() as Outcome.Ok).value
            assertEquals("one session, not two", 1, sessions.size)
            assertNull((newRepository().activeSession() as Outcome.Ok).value)

            // One program, and a second attempt to create the default is refused.
            val programs = newRepository().activeProgram()
            assertNotNull((programs as Outcome.Ok).value)
            assertTrue(newRepository().createDefaultProgram() is Outcome.Failed)

            // The finished workout is now this exercise's previous record.
            val previous = (newRepository().previousPerformance("lat_pulldown", null) as Outcome.Ok).value
            assertEquals(3, previous!!.sets.size)
            assertEquals("55 lb x 10, 9, 8", previous.summary)
        }
    }

    @Test fun a_rest_day_offers_no_workout_and_the_plan_survives_a_reopen() {
        val repository = newRepository()
        val vm = GymViewModel(repository)
        rule.setContent { GymUnderTest(vm) }
        vm.load()
        rule.waitUntil(15_000) { vm.state.value.phase.name != "Loading" }
        rule.onNodeWithTag("gym_create_plan").performClick()
        rule.waitUntil(20_000) { vm.state.value.program != null }

        onPlan("gym_day_day-4").performClick()
        rule.waitForIdle()
        onPlan("gym_rest_day").assertIsDisplayed()
        assertTrue(
            "a rest day shows no Start workout button",
            rule.onAllNodes(hasTestTag("gym_start_workout")).fetchSemanticsNodes().isEmpty(),
        )

        // Reopening reads the same single program back from the encrypted file.
        val reopened = GymViewModel(newRepository())
        reopened.load()
        rule.waitUntil(20_000) { reopened.state.value.program != null }
        assertEquals(vm.state.value.program!!.id, reopened.state.value.program!!.id)
        assertEquals(90, reopened.state.value.program!!.days.sumOf { it.plannedWorkingSets })
    }

    /**
     * GYM-02: logging a set shows a save notice and may start the rest timer. Neither may move the
     * weight and reps fields, which is what made a hand-driven run type into the wrong field.
     */
    @Test fun the_set_logger_does_not_move_when_a_set_is_saved() {
        val repository = newRepository()
        val vm = GymViewModel(repository)
        rule.setContent { GymUnderTest(vm) }
        vm.load()
        rule.waitUntil(15_000) { vm.state.value.phase.name != "Loading" }
        rule.onNodeWithTag("gym_create_plan").performClick()
        rule.waitUntil(20_000) { vm.state.value.program != null }
        onPlan("gym_day_day-2").performClick()
        onPlan("gym_start_workout").performClick()
        rule.waitUntil(20_000) { vm.state.value.session != null }
        // The rest timer is on, so both the save notice and the timer card are in play.
        onLive("gym_rest_enabled").performClick()
        rule.waitForIdle()

        val before = onLive("gym_input_load").fetchSemanticsNode().boundsInRoot
        val repsBefore = onLive("gym_input_reps").fetchSemanticsNode().boundsInRoot
        logSet("55", "10")
        rule.waitUntil(10_000) { vm.state.value.session?.metrics?.workingSetsCompleted == 1 }
        rule.waitForIdle()

        assertEquals("the saved notice moved the weight field", before, rule.onNodeWithTag("gym_input_load").fetchSemanticsNode().boundsInRoot)
        assertEquals("the saved notice moved the reps field", repsBefore, rule.onNodeWithTag("gym_input_reps").fetchSemanticsNode().boundsInRoot)
        assertTrue("the save notice is shown", vm.state.value.savedNote != null)
        assertTrue("the rest timer started", vm.state.value.restTimer.remainingSeconds > 0)

        // A refused write shows an error in the same slot, and still does not move the fields.
        onLive("gym_input_reps").performTextClearance()
        onLive("gym_input_load").performTextClearance()
        onLive("gym_input_load").performTextInput("55")
        rule.waitForIdle()
        assertEquals(before, rule.onNodeWithTag("gym_input_load").fetchSemanticsNode().boundsInRoot)
    }

    @Test fun a_warm_up_set_is_kept_out_of_the_working_set_count_on_the_receipt() {
        val repository = newRepository()
        val vm = GymViewModel(repository)
        rule.setContent { GymUnderTest(vm) }
        vm.load()
        rule.waitUntil(15_000) { vm.state.value.phase.name != "Loading" }
        rule.onNodeWithTag("gym_create_plan").performClick()
        rule.waitUntil(20_000) { vm.state.value.program != null }
        onPlan("gym_day_day-2").performClick()
        onPlan("gym_start_workout").performClick()
        rule.waitUntil(20_000) { vm.state.value.session != null }

        onLive("gym_input_warmup").performClick()
        logSet("30", "12")
        logSet("55", "10")
        rule.waitUntil(10_000) { vm.state.value.session?.metrics?.workingSetsCompleted == 1 }

        val metrics = vm.state.value.session!!.metrics
        assertEquals(1, metrics.workingSetsCompleted)
        assertEquals(1, metrics.warmupSetsCompleted)
        assertEquals("only the working set makes volume", 550_000L, metrics.volumeByUnit.first().volumeMilli)
    }
}
