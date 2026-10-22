package app.reva.ui.gym

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.data.GymPlanDay
import app.reva.data.GymPreviousPerformance
import app.reva.data.GymProgram
import app.reva.data.GymRepository
import app.reva.data.GymSessionDetail
import app.reva.data.GymSessionSummary
import app.reva.data.GymSetInput
import app.reva.data.Outcome
import app.reva.data.parseLoadMilli
import java.time.LocalDate
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Which Gym screen is in front. One stack, so Back always has one place to go. */
enum class GymScreen { TrainingPlan, LiveWorkout, SessionDetails }

/**
 * Every state a Gym screen can be in. `Saving` and `Pending` are separate from `Ready` on purpose:
 * nothing is ever shown as saved before the Kernel has confirmed the write.
 */
enum class GymPhase { Loading, Ready, Empty, Saving, Error }

/** What the Set Logger holds while the user types. Nothing here is a commitment. */
data class SetDraft(
    val exerciseKey: String = "",
    val load: String = "",
    val reps: String = "",
    val rir: String = "",
    val warmUp: Boolean = false,
    val notes: String = "",
) {
    fun toInput(unit: String, semantics: String, exerciseName: String?): GymSetInput = GymSetInput(
        exerciseKey = exerciseKey,
        setType = if (warmUp) "warmup" else "working",
        loadMilli = parseLoadMilli(load),
        weightUnit = unit,
        loadSemantics = semantics,
        reps = reps.trim().toIntOrNull(),
        rir = rir.trim().toIntOrNull(),
        completed = true,
        notes = notes.trim().ifBlank { null },
        exerciseName = exerciseName,
    )

    /** Enough typed to try a save. The Kernel still has the last word. */
    val canLog: Boolean get() = reps.trim().toIntOrNull() != null
}

/** The rest timer runs in the ViewModel, so leaving the screen never loses it. */
data class RestTimer(
    val enabled: Boolean = false,
    val totalSeconds: Int = 90,
    val remainingSeconds: Int = 0,
    val running: Boolean = false,
) {
    val active: Boolean get() = enabled && remainingSeconds > 0
}

data class GymUiState(
    val screen: GymScreen = GymScreen.TrainingPlan,
    val phase: GymPhase = GymPhase.Loading,
    val program: GymProgram? = null,
    val selectedDayId: String? = null,
    val session: GymSessionDetail? = null,
    val recent: List<GymSessionSummary> = emptyList(),
    val currentExerciseIndex: Int = 0,
    val previous: GymPreviousPerformance? = null,
    val previousLoaded: Boolean = false,
    val draft: SetDraft = SetDraft(),
    val restTimer: RestTimer = RestTimer(),
    val unit: String = "lb",
    val error: String? = null,
    /** Set only after the Kernel confirmed a write, and cleared on the next action. */
    val savedNote: String? = null,
    val finishPrompt: Boolean = false,
    val editing: Boolean = false,
) {
    val selectedDay: GymPlanDay?
        get() = program?.days?.firstOrNull { it.dayId == selectedDayId } ?: program?.days?.firstOrNull()

    /** The exercise the Live Workout screen is on, from the session's own plan snapshot. */
    val currentPrescription get() = session?.session?.snapshot?.exercises?.getOrNull(currentExerciseIndex)

    val exerciseCount: Int get() = session?.session?.snapshot?.exercises?.size ?: 0

    val busy: Boolean get() = phase == GymPhase.Saving || phase == GymPhase.Loading
}

/**
 * The one place the Gym screens get their state. It never computes a workout number itself: counts,
 * durations and volume all come back from the Kernel with every read.
 */
class GymViewModel(
    private val repository: GymRepository,
    private val scope: CoroutineScope? = null,
    private val today: () -> LocalDate = { LocalDate.now() },
) : ViewModel() {
    private val _state = MutableStateFlow(GymUiState())
    val state: StateFlow<GymUiState> = _state.asStateFlow()

    private val jobScope: CoroutineScope get() = scope ?: viewModelScope

    /** First open, and every return to the Gym tab: the plan, any recoverable workout, recent history. */
    fun load() {
        _state.update { it.copy(phase = GymPhase.Loading, error = null) }
        jobScope.launch {
            when (val program = repository.activeProgram()) {
                is Outcome.Failed -> fail(program.error)
                is Outcome.Ok -> {
                    val value = program.value
                    if (value == null) {
                        _state.update { it.copy(phase = GymPhase.Empty, program = null) }
                    } else {
                        _state.update {
                            it.copy(
                                phase = GymPhase.Ready,
                                program = value,
                                selectedDayId = it.selectedDayId ?: value.days.firstOrNull { d -> !d.isRest }?.dayId,
                            )
                        }
                        refreshSessions()
                    }
                }
            }
        }
    }

    /** Creates the reviewed seven-day program, once. A second attempt is the Kernel's to refuse. */
    fun createDefaultProgram() {
        _state.update { it.copy(phase = GymPhase.Saving, error = null, savedNote = null) }
        jobScope.launch {
            when (val result = repository.createDefaultProgram(today().toString())) {
                is Outcome.Failed -> fail(result.error)
                is Outcome.Ok -> {
                    _state.update {
                        it.copy(
                            phase = GymPhase.Ready,
                            program = result.value,
                            selectedDayId = result.value.days.firstOrNull { d -> !d.isRest }?.dayId,
                            savedNote = "Training plan created",
                        )
                    }
                    refreshSessions()
                }
            }
        }
    }

    fun selectDay(dayId: String) = _state.update { it.copy(selectedDayId = dayId, error = null, savedNote = null) }

    fun openPlan() = _state.update { it.copy(screen = GymScreen.TrainingPlan, error = null, editing = false) }

    fun toggleEditing() = _state.update { it.copy(editing = !it.editing, error = null, savedNote = null) }

    fun savePlan(days: List<GymPlanDay>) {
        val programId = _state.value.program?.id ?: return
        _state.update { it.copy(phase = GymPhase.Saving, error = null, savedNote = null) }
        jobScope.launch {
            when (val result = repository.updatePlan(programId, days)) {
                is Outcome.Failed -> fail(result.error)
                is Outcome.Ok -> _state.update {
                    it.copy(
                        phase = GymPhase.Ready,
                        program = result.value,
                        editing = false,
                        savedNote = "Plan saved as version ${result.value.planVersion}",
                    )
                }
            }
        }
    }

    fun startWorkout(dayId: String) {
        val program = _state.value.program ?: return
        _state.update { it.copy(phase = GymPhase.Saving, error = null, savedNote = null) }
        jobScope.launch {
            when (val started = repository.startWorkout(program.id, dayId)) {
                is Outcome.Failed -> fail(started.error)
                is Outcome.Ok -> {
                    _state.update { it.copy(screen = GymScreen.LiveWorkout, currentExerciseIndex = 0) }
                    reloadSession(started.value, note = null)
                }
            }
        }
    }

    /** Called when the Gym tab opens: an unfinished workout comes back exactly as it was. */
    fun recoverActiveWorkout() {
        jobScope.launch {
            when (val active = repository.activeSession()) {
                is Outcome.Failed -> fail(active.error)
                is Outcome.Ok -> active.value?.let { detail ->
                    _state.update {
                        it.copy(
                            screen = GymScreen.LiveWorkout,
                            phase = GymPhase.Ready,
                            session = detail,
                            draft = SetDraft(exerciseKey = detail.session.snapshot?.exercises?.firstOrNull()?.exerciseKey ?: ""),
                        )
                    }
                    loadPrevious()
                }
            }
        }
    }

    fun selectExercise(index: Int) {
        val count = _state.value.exerciseCount
        if (index < 0 || index >= count) return
        _state.update {
            val key = it.session?.session?.snapshot?.exercises?.getOrNull(index)?.exerciseKey ?: ""
            it.copy(
                currentExerciseIndex = index,
                draft = SetDraft(exerciseKey = key),
                previous = null,
                previousLoaded = false,
                error = null,
                savedNote = null,
            )
        }
        loadPrevious()
    }

    fun nextExercise() = selectExercise(_state.value.currentExerciseIndex + 1)

    fun previousExercise() = selectExercise(_state.value.currentExerciseIndex - 1)

    fun editDraft(transform: (SetDraft) -> SetDraft) =
        _state.update { it.copy(draft = transform(it.draft), error = null, savedNote = null) }

    /** Copy the last logged set of this exercise into the draft, as editable text. */
    fun copyPreviousSet() {
        val state = _state.value
        val key = state.currentPrescription?.exerciseKey ?: return
        val last = state.session?.blockFor(key)?.sets?.lastOrNull()
            ?: state.previous?.sets?.lastOrNull()
            ?: return
        _state.update {
            it.copy(
                draft = it.draft.copy(
                    exerciseKey = key,
                    load = last.loadMilli?.let { milli -> trimmed(milli) } ?: "",
                    reps = last.reps?.toString() ?: "",
                    rir = last.rir?.toString() ?: "",
                ),
                error = null,
                savedNote = null,
            )
        }
    }

    fun logSet() {
        val state = _state.value
        val session = state.session?.session ?: return
        val prescription = state.currentPrescription
        val key = state.draft.exerciseKey.ifBlank { prescription?.exerciseKey ?: return }
        val semantics = if (state.draft.load.isBlank()) "bodyweight" else "external"
        val input = state.draft.copy(exerciseKey = key).toInput(state.unit, semantics, prescription?.name)
        _state.update { it.copy(phase = GymPhase.Saving, error = null, savedNote = null) }
        jobScope.launch {
            when (val saved = repository.addSet(session.id, input)) {
                is Outcome.Failed -> fail(saved.error)
                is Outcome.Ok -> {
                    // Only now, with the Kernel's commit in hand, is anything shown as saved.
                    _state.update {
                        it.copy(
                            draft = SetDraft(exerciseKey = key),
                            restTimer = if (it.restTimer.enabled && !input.setType.equals("warmup", true)) {
                                it.restTimer.copy(remainingSeconds = it.restTimer.totalSeconds, running = true)
                            } else {
                                it.restTimer
                            },
                        )
                    }
                    reloadSession(session.id, note = "Set saved")
                }
            }
        }
    }

    fun updateSet(setId: String, load: String?, reps: String?, rir: String?) {
        val session = _state.value.session?.session ?: return
        val changes = JSONObject()
        load?.let { changes.put("load_milli", parseLoadMilli(it) ?: JSONObject.NULL) }
        reps?.let { changes.put("reps", it.trim().toIntOrNull() ?: JSONObject.NULL) }
        rir?.let { changes.put("rir", it.trim().toIntOrNull() ?: JSONObject.NULL) }
        write(session.id, "Set updated") { repository.updateSet(session.id, setId, changes) }
    }

    fun removeSet(setId: String) {
        val session = _state.value.session?.session ?: return
        write(session.id, "Set removed") { repository.removeSet(setId) }
    }

    fun pauseOrResume() {
        val session = _state.value.session?.session ?: return
        if (session.isPaused) {
            write(session.id, "Resumed") { repository.resume(session.id) }
        } else {
            write(session.id, "Paused") { repository.pause(session.id) }
        }
    }

    fun saveNote(notes: String?, effortNote: String?) {
        val session = _state.value.session?.session ?: return
        write(session.id, "Note saved") { repository.note(session.id, notes, effortNote) }
    }

    fun askToFinish() = _state.update { it.copy(finishPrompt = true, error = null, savedNote = null) }

    fun dismissFinish() = _state.update { it.copy(finishPrompt = false) }

    /** One confirmed finish. A second tap finds the session already completed and is refused. */
    fun finishWorkout() {
        val session = _state.value.session?.session ?: return
        if (_state.value.phase == GymPhase.Saving) return
        _state.update { it.copy(phase = GymPhase.Saving, finishPrompt = false, error = null, savedNote = null) }
        jobScope.launch {
            when (val done = repository.complete(session.id)) {
                is Outcome.Failed -> fail(done.error)
                is Outcome.Ok -> {
                    _state.update {
                        it.copy(screen = GymScreen.SessionDetails, restTimer = it.restTimer.copy(running = false, remainingSeconds = 0))
                    }
                    reloadSession(session.id, note = "Workout saved")
                    refreshSessions()
                }
            }
        }
    }

    fun discardWorkout() {
        val session = _state.value.session?.session ?: return
        _state.update { it.copy(phase = GymPhase.Saving, finishPrompt = false, error = null) }
        jobScope.launch {
            when (val done = repository.discard(session.id)) {
                is Outcome.Failed -> fail(done.error)
                is Outcome.Ok -> {
                    _state.update { it.copy(screen = GymScreen.TrainingPlan, session = null, phase = GymPhase.Ready) }
                    refreshSessions()
                }
            }
        }
    }

    fun deleteSession(sessionId: String) {
        _state.update { it.copy(phase = GymPhase.Saving, error = null) }
        jobScope.launch {
            when (val done = repository.delete(sessionId)) {
                is Outcome.Failed -> fail(done.error)
                is Outcome.Ok -> {
                    _state.update {
                        it.copy(screen = GymScreen.TrainingPlan, session = null, phase = GymPhase.Ready, savedNote = "Workout deleted")
                    }
                    refreshSessions()
                }
            }
        }
    }

    fun openSession(sessionId: String) {
        _state.update { it.copy(screen = GymScreen.SessionDetails, phase = GymPhase.Loading) }
        jobScope.launch { reloadSession(sessionId, note = null) }
    }

    fun openLiveWorkout() = _state.update { it.copy(screen = GymScreen.LiveWorkout, error = null) }

    fun setUnit(unit: String) = _state.update { it.copy(unit = unit) }

    fun configureRest(enabled: Boolean, seconds: Int = _state.value.restTimer.totalSeconds) =
        _state.update {
            it.copy(
                restTimer = it.restTimer.copy(
                    enabled = enabled,
                    totalSeconds = seconds.coerceIn(10, 600),
                    remainingSeconds = if (enabled) it.restTimer.remainingSeconds else 0,
                    running = enabled && it.restTimer.running,
                ),
            )
        }

    fun pauseRest() = _state.update { it.copy(restTimer = it.restTimer.copy(running = false)) }

    fun resumeRest() =
        _state.update { it.copy(restTimer = it.restTimer.copy(running = it.restTimer.remainingSeconds > 0)) }

    fun skipRest() = _state.update { it.copy(restTimer = it.restTimer.copy(remainingSeconds = 0, running = false)) }

    fun extendRest(seconds: Int = 30) = _state.update {
        it.copy(restTimer = it.restTimer.copy(remainingSeconds = (it.restTimer.remainingSeconds + seconds).coerceAtMost(3_600), running = true))
    }

    /** One second of rest has passed. Driven by the screen's own ticker, so no background work. */
    fun tickRest() = _state.update {
        if (!it.restTimer.running || it.restTimer.remainingSeconds <= 0) {
            it
        } else {
            val left = it.restTimer.remainingSeconds - 1
            it.copy(restTimer = it.restTimer.copy(remainingSeconds = left, running = left > 0))
        }
    }

    fun clearMessages() = _state.update { it.copy(error = null, savedNote = null) }

    private fun write(sessionId: String, note: String, block: suspend () -> Outcome<Unit>) {
        _state.update { it.copy(phase = GymPhase.Saving, error = null, savedNote = null) }
        jobScope.launch {
            when (val result = block()) {
                is Outcome.Failed -> fail(result.error)
                is Outcome.Ok -> reloadSession(sessionId, note)
            }
        }
    }

    /** Read the session back from the Kernel, so what the screen shows is what was committed. */
    private suspend fun reloadSession(sessionId: String, note: String?) {
        when (val detail = repository.sessionDetails(sessionId)) {
            is Outcome.Failed -> fail(detail.error)
            is Outcome.Ok -> {
                _state.update {
                    val snapshot = detail.value.session.snapshot
                    val index = it.currentExerciseIndex.coerceIn(0, maxOf(0, (snapshot?.exercises?.size ?: 1) - 1))
                    it.copy(
                        phase = GymPhase.Ready,
                        session = detail.value,
                        currentExerciseIndex = index,
                        draft = if (it.draft.exerciseKey.isBlank()) {
                            SetDraft(exerciseKey = snapshot?.exercises?.getOrNull(index)?.exerciseKey ?: "")
                        } else {
                            it.draft
                        },
                        savedNote = note,
                        error = null,
                    )
                }
                if (!_state.value.previousLoaded) loadPrevious()
            }
        }
    }

    private fun loadPrevious() {
        val state = _state.value
        val key = state.currentPrescription?.exerciseKey ?: state.draft.exerciseKey
        if (key.isBlank()) return
        val sessionId = state.session?.session?.id
        jobScope.launch {
            when (val previous = repository.previousPerformance(key, sessionId)) {
                is Outcome.Failed -> _state.update { it.copy(previousLoaded = true) }
                is Outcome.Ok -> _state.update { it.copy(previous = previous.value, previousLoaded = true) }
            }
        }
    }

    private suspend fun refreshSessions() {
        when (val recent = repository.recentSessions()) {
            is Outcome.Failed -> Unit // history is not worth failing a screen over
            is Outcome.Ok -> _state.update { it.copy(recent = recent.value) }
        }
    }

    private fun fail(error: FinanceError) = _state.update {
        it.copy(
            // A refused write leaves what the user typed exactly where it was.
            phase = if (it.session != null || it.program != null) GymPhase.Ready else GymPhase.Error,
            error = message(error),
            savedNote = null,
        )
    }

    private fun message(error: FinanceError): String = when (error.kind) {
        ErrorKind.Locked, ErrorKind.KeyLost -> "Gym is locked on this device. Nothing was changed."
        ErrorKind.Corrupt -> "Workout data could not be read. Nothing was changed."
        else -> error.message
    }

    private fun trimmed(loadMilli: Long): String {
        val whole = loadMilli / 1_000
        val fraction = loadMilli % 1_000
        return if (fraction == 0L) whole.toString() else (loadMilli / 1_000.0).toString().trimEnd('0').trimEnd('.')
    }
}
