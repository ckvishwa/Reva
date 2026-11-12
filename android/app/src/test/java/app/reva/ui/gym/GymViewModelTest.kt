package app.reva.ui.gym

import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.testing.FakeGymRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * The Gym screens' state machine. Storage is proved in kernel/tests/gym.rs and on the device in
 * GymComposeTest; what is checked here is that the screens never get ahead of the Kernel.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class GymViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private fun model(repo: FakeGymRepository, scope: TestScope) = GymViewModel(repo, scope)

    @Test fun `no plan shows the empty state and creating one opens the plan`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.load()
        advanceUntilIdle()
        assertEquals(GymPhase.Empty, vm.state.value.phase)
        assertNull(vm.state.value.program)

        vm.createDefaultProgram()
        advanceUntilIdle()
        val state = vm.state.value
        assertEquals(GymPhase.Ready, state.phase)
        assertEquals("REVA Base Program", state.program?.name)
        assertEquals("day-2", state.selectedDayId)
        assertEquals("Training plan created", state.savedNote)
    }

    @Test fun `a second create is refused and the plan already on the device is kept`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        val first = vm.state.value.program

        vm.createDefaultProgram()
        advanceUntilIdle()
        val state = vm.state.value
        assertEquals(first, state.program)
        assertEquals("a gym program already exists", state.error)
        assertNull("nothing is reported as saved", state.savedNote)
    }

    @Test fun `a rest day cannot start a workout`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-4")
        advanceUntilIdle()
        assertEquals(GymScreen.TrainingPlan, vm.state.value.screen)
        assertTrue(vm.state.value.error!!.contains("rest day"))
    }

    @Test fun `logging a set only reports saved after the repository confirms it`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        assertEquals(GymScreen.LiveWorkout, vm.state.value.screen)

        vm.editDraft { it.copy(load = "55", reps = "10") }
        assertTrue(vm.state.value.draft.canLog)
        vm.logSet()
        // The command is in flight: nothing says saved yet.
        assertEquals(GymPhase.Saving, vm.state.value.phase)
        assertNull(vm.state.value.savedNote)
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals(GymPhase.Ready, state.phase)
        assertEquals("Set saved", state.savedNote)
        assertEquals(1, state.session?.metrics?.workingSetsCompleted)
        assertEquals(55_000L, state.session?.exercises?.first()?.sets?.first()?.loadMilli)
        assertEquals("", state.draft.load)
        assertTrue(repo.commands.contains("gym.set.add"))
    }

    @Test fun `a refused set keeps what was typed and says nothing was saved`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()

        repo.failNext = FinanceError(ErrorKind.Validation, "reps: a completed set records its repetitions")
        vm.editDraft { it.copy(load = "55", reps = "10") }
        vm.logSet()
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals("reps: a completed set records its repetitions", state.error)
        assertNull(state.savedNote)
        assertEquals("55", state.draft.load)
        assertEquals("10", state.draft.reps)
        assertEquals(0, state.session?.metrics?.workingSetsCompleted)
    }

    @Test fun `a warm-up set is logged as a warm-up and keeps working sets where they were`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        vm.editDraft { it.copy(load = "30", reps = "12", warmUp = true) }
        vm.logSet()
        advanceUntilIdle()

        val metrics = vm.state.value.session!!.metrics
        assertEquals(1, metrics.warmupSetsCompleted)
        assertEquals(0, metrics.workingSetsCompleted)
        assertFalse("the warm-up flag is not carried into the next set", vm.state.value.draft.warmUp)
    }

    @Test fun `pause and resume follow the session state`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()

        vm.pauseOrResume()
        advanceUntilIdle()
        assertEquals("paused", vm.state.value.session?.session?.state)
        assertEquals("Paused", vm.state.value.savedNote)

        vm.pauseOrResume()
        advanceUntilIdle()
        assertEquals("in_progress", vm.state.value.session?.session?.state)
        assertTrue(vm.state.value.session!!.metrics.pausedSeconds > 0)
    }

    @Test fun `finishing asks first, happens once, and opens the receipt`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        vm.editDraft { it.copy(load = "55", reps = "10") }
        vm.logSet()
        advanceUntilIdle()

        vm.askToFinish()
        assertTrue(vm.state.value.finishPrompt)
        vm.finishWorkout()
        advanceUntilIdle()
        assertEquals(GymScreen.SessionDetails, vm.state.value.screen)
        assertEquals("completed", vm.state.value.session?.session?.state)
        assertEquals("Workout saved", vm.state.value.savedNote)

        // A second tap on a finished workout is refused, and no second session appears.
        vm.finishWorkout()
        advanceUntilIdle()
        assertEquals("this workout is already finished", vm.state.value.error)
        assertEquals(1, vm.state.value.recent.size)
        assertEquals(1, repo.commands.count { it == "gym.session.complete" } - 1)
    }

    @Test fun `an unfinished workout is recovered when the tab opens`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val first = model(repo, this)
        first.createDefaultProgram()
        advanceUntilIdle()
        first.startWorkout("day-2")
        advanceUntilIdle()
        first.editDraft { it.copy(load = "55", reps = "9") }
        first.logSet()
        advanceUntilIdle()

        // A fresh ViewModel is what a restarted app has.
        val reopened = model(repo, this)
        reopened.load()
        reopened.recoverActiveWorkout()
        advanceUntilIdle()

        val state = reopened.state.value
        assertEquals(GymScreen.LiveWorkout, state.screen)
        assertEquals(1, state.session?.exercises?.first()?.sets?.size)
        assertEquals(9, state.session?.exercises?.first()?.sets?.first()?.reps)
    }

    @Test fun `editing and removing a set go through the repository`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        vm.editDraft { it.copy(load = "55", reps = "10") }
        vm.logSet()
        advanceUntilIdle()
        val setId = vm.state.value.session!!.exercises.first().sets.first().id

        vm.updateSet(setId, load = "52.5", reps = "11", rir = null)
        advanceUntilIdle()
        val updated = vm.state.value.session!!.exercises.first().sets.first()
        assertEquals(52_500L, updated.loadMilli)
        assertEquals(11, updated.reps)
        assertEquals("Set updated", vm.state.value.savedNote)

        vm.removeSet(setId)
        advanceUntilIdle()
        assertTrue(vm.state.value.session!!.exercises.isEmpty())
        assertEquals("Set removed", vm.state.value.savedNote)
    }

    @Test fun `the rest timer starts on a working set and never blocks logging`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        vm.configureRest(enabled = true, seconds = 90)

        vm.editDraft { it.copy(load = "55", reps = "10") }
        vm.logSet()
        advanceUntilIdle()
        assertEquals(90, vm.state.value.restTimer.remainingSeconds)
        assertTrue(vm.state.value.restTimer.running)

        vm.tickRest()
        assertEquals(89, vm.state.value.restTimer.remainingSeconds)
        vm.pauseRest()
        vm.tickRest()
        assertEquals("a paused timer does not count down", 89, vm.state.value.restTimer.remainingSeconds)
        vm.extendRest(30)
        assertEquals(119, vm.state.value.restTimer.remainingSeconds)

        // Logging still works while resting.
        vm.editDraft { it.copy(load = "55", reps = "9") }
        vm.logSet()
        advanceUntilIdle()
        assertEquals(2, vm.state.value.session!!.metrics.workingSetsCompleted)

        vm.skipRest()
        assertFalse(vm.state.value.restTimer.active)
    }

    @Test fun `a warm-up set does not start the rest timer`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        vm.configureRest(enabled = true, seconds = 60)
        vm.editDraft { it.copy(load = "30", reps = "12", warmUp = true) }
        vm.logSet()
        advanceUntilIdle()
        assertEquals(0, vm.state.value.restTimer.remainingSeconds)
    }

    @Test fun `the exercise navigator stays inside the plan snapshot`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        vm.startWorkout("day-2")
        advanceUntilIdle()
        assertEquals(2, vm.state.value.exerciseCount)
        assertEquals("lat_pulldown", vm.state.value.currentPrescription?.exerciseKey)

        vm.nextExercise()
        advanceUntilIdle()
        assertEquals("chest_supported_row", vm.state.value.currentPrescription?.exerciseKey)
        vm.nextExercise()
        advanceUntilIdle()
        assertEquals("the last exercise is the last", 1, vm.state.value.currentExerciseIndex)
        vm.previousExercise()
        vm.previousExercise()
        advanceUntilIdle()
        assertEquals(0, vm.state.value.currentExerciseIndex)
    }

    @Test fun `editing the plan saves a new version`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        vm.createDefaultProgram()
        advanceUntilIdle()
        val days = vm.state.value.program!!.days
        val edited = days.map { day ->
            if (day.dayId == "day-2") day.copy(label = "Pull A: Lats", exercises = day.exercises.take(1)) else day
        }
        vm.savePlan(edited)
        advanceUntilIdle()

        val program = vm.state.value.program!!
        assertEquals(2, program.planVersion)
        assertEquals("Pull A: Lats", program.day("day-2")?.label)
        assertEquals(1, program.day("day-2")?.exercises?.size)
        assertEquals("Plan saved as version 2", vm.state.value.savedNote)
    }

    @Test fun `a locked domain is reported without claiming a change`() = runTest(dispatcher) {
        val repo = FakeGymRepository()
        val vm = model(repo, this)
        repo.failNext = FinanceError(ErrorKind.KeyLost, "raw")
        vm.load()
        advanceUntilIdle()
        assertEquals(GymPhase.Error, vm.state.value.phase)
        assertEquals("Gym is locked on this device. Nothing was changed.", vm.state.value.error)
        assertNull(vm.state.value.savedNote)
    }
}
