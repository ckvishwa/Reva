package app.reva.testing

import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.data.GymExerciseBlock
import app.reva.data.GymMetrics
import app.reva.data.GymPlanDay
import app.reva.data.GymPrescription
import app.reva.data.GymPreviousPerformance
import app.reva.data.GymProgram
import app.reva.data.GymRepository
import app.reva.data.GymSession
import app.reva.data.GymSessionDetail
import app.reva.data.GymSessionSummary
import app.reva.data.GymSetInput
import app.reva.data.GymSetRecord
import app.reva.data.GymVolume
import app.reva.data.Outcome
import org.json.JSONObject

/**
 * A stand-in for the Kernel-backed [GymRepository], for ViewModel tests only. It keeps the rules the
 * screens depend on (one program, one open session, a finish that happens once) so the ViewModel is
 * tested against the same refusals the Kernel gives. It proves nothing about storage: the real
 * persistence proof is kernel/tests/gym.rs and GymComposeTest on a device.
 */
class FakeGymRepository(
    private val days: List<GymPlanDay> = defaultDays(),
) : GymRepository {
    val commands = mutableListOf<String>()
    var failNext: FinanceError? = null
    var program: GymProgram? = null
        private set

    private var session: GymSession? = null
    private val sets = mutableListOf<GymSetRecord>()
    private val finished = mutableListOf<GymSessionSummary>()
    private var pausedSeconds = 0L
    private var counter = 0

    /** The next call fails with this error, once. Typed at each call site so inference stays simple. */
    private fun takeFailure(): FinanceError? = failNext?.also { failNext = null }

    private fun nextId(prefix: String): String = "$prefix-${++counter}"

    override suspend fun activeProgram(): Outcome<GymProgram?> {
        commands += "active_program"
        takeFailure()?.let { return Outcome.Failed(it) }
        return Outcome.Ok(program)
    }

    override suspend fun createDefaultProgram(anchorDate: String?): Outcome<GymProgram> {
        commands += "gym.program.create_default"
        takeFailure()?.let { return Outcome.Failed(it) }
        if (program != null) {
            return Outcome.Failed(FinanceError(ErrorKind.Conflict, "a gym program already exists"))
        }
        val created = GymProgram("program-1", "REVA Base Program", anchorDate ?: "2026-10-22", 1, days)
        program = created
        return Outcome.Ok(created)
    }

    override suspend fun updatePlan(programId: String, days: List<GymPlanDay>): Outcome<GymProgram> {
        commands += "gym.program.update"
        takeFailure()?.let { return Outcome.Failed(it) }
        val current = program ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no program"))
        val updated = current.copy(planVersion = current.planVersion + 1, days = days)
        program = updated
        return Outcome.Ok(updated)
    }

    override suspend fun activeSession(): Outcome<GymSessionDetail?> {
        commands += "active_session"
        takeFailure()?.let { return Outcome.Failed(it) }
        val open = session?.takeIf { it.isOpen } ?: return Outcome.Ok(null)
        return Outcome.Ok(detail(open))
    }

    override suspend fun startWorkout(programId: String, dayId: String): Outcome<String> {
        commands += "gym.session.start"
        takeFailure()?.let { return Outcome.Failed(it) }
        if (session?.isOpen == true) {
            return Outcome.Failed(FinanceError(ErrorKind.Conflict, "a workout is already in progress"))
        }
        val day = program?.day(dayId) ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such day"))
        if (day.isRest) return Outcome.Failed(FinanceError(ErrorKind.Validation, "day_id: a rest day has no workout"))
        sets.clear()
        pausedSeconds = 0
        val id = nextId("session")
        session = GymSession(
            id = id,
            programId = programId,
            planVersion = program?.planVersion ?: 1,
            dayId = dayId,
            label = day.label,
            state = "in_progress",
            date = "2026-10-22",
            startedAt = "2026-10-22T17:00:00Z",
            endedAt = null,
            notes = null,
            effortNote = null,
            snapshot = day,
        )
        return Outcome.Ok(id)
    }

    override suspend fun pause(sessionId: String): Outcome<Unit> = transition(sessionId, "gym.session.pause") {
        if (it.state != "in_progress") null else it.copy(state = "paused")
    }

    override suspend fun resume(sessionId: String): Outcome<Unit> = transition(sessionId, "gym.session.resume") {
        if (it.state != "paused") null else { pausedSeconds += 180; it.copy(state = "in_progress") }
    }

    override suspend fun complete(sessionId: String): Outcome<Unit> = transition(sessionId, "gym.session.complete") {
        if (!it.isOpen) null else it.copy(state = "completed", endedAt = "2026-10-22T17:45:00Z")
    }

    override suspend fun discard(sessionId: String): Outcome<Unit> = transition(sessionId, "gym.session.discard") {
        if (!it.isOpen) null else it.copy(state = "discarded", endedAt = "2026-10-22T17:20:00Z")
    }

    override suspend fun delete(sessionId: String): Outcome<Unit> {
        commands += "gym.session.delete"
        takeFailure()?.let { return Outcome.Failed(it) }
        if (session?.id != sessionId) return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such workout"))
        session = null
        sets.clear()
        return Outcome.Ok(Unit)
    }

    private inline fun transition(
        sessionId: String,
        command: String,
        change: (GymSession) -> GymSession?,
    ): Outcome<Unit> {
        commands += command
        takeFailure()?.let { return Outcome.Failed(it) }
        val current = session?.takeIf { it.id == sessionId }
            ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such workout"))
        val next = change(current)
            ?: return Outcome.Failed(FinanceError(ErrorKind.Conflict, "this workout is already finished"))
        session = next
        if (next.state == "completed") {
            finished += GymSessionSummary(next.id, next.label, next.dayId, next.date, next.state, metrics(next))
        }
        return Outcome.Ok(Unit)
    }

    override suspend fun addSet(sessionId: String, input: GymSetInput): Outcome<String> {
        commands += "gym.set.add"
        takeFailure()?.let { return Outcome.Failed(it) }
        val current = session?.takeIf { it.id == sessionId }
            ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such workout"))
        if (!current.isOpen) return Outcome.Failed(FinanceError(ErrorKind.Conflict, "this workout is already finished"))
        if (input.completed && input.reps == null) {
            return Outcome.Failed(FinanceError(ErrorKind.Validation, "reps: a completed set records its repetitions"))
        }
        val prescription = current.snapshot?.exercises?.firstOrNull { it.exerciseKey == input.exerciseKey }
        val id = nextId("set")
        sets += GymSetRecord(
            id = id,
            exerciseKey = input.exerciseKey,
            exerciseName = input.exerciseName ?: prescription?.name ?: input.exerciseKey,
            equipment = prescription?.equipment,
            exerciseOrder = prescription?.order ?: 1,
            setOrder = sets.count { it.exerciseKey == input.exerciseKey } + 1,
            setType = input.setType,
            loadMilli = input.loadMilli,
            weightUnit = input.weightUnit,
            loadSemantics = input.loadSemantics,
            reps = input.reps,
            rir = input.rir,
            completed = input.completed,
            completedAt = if (input.completed) "2026-10-22T17:05:00Z" else null,
            notes = input.notes,
        )
        return Outcome.Ok(id)
    }

    override suspend fun updateSet(sessionId: String, setId: String, changes: JSONObject): Outcome<Unit> {
        commands += "gym.set.update"
        takeFailure()?.let { return Outcome.Failed(it) }
        val index = sets.indexOfFirst { it.id == setId }
        if (index < 0) return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such set"))
        val set = sets[index]
        sets[index] = set.copy(
            loadMilli = if (changes.has("load_milli") && !changes.isNull("load_milli")) changes.getLong("load_milli") else set.loadMilli,
            reps = if (changes.has("reps") && !changes.isNull("reps")) changes.getInt("reps") else set.reps,
            rir = if (changes.has("rir")) (if (changes.isNull("rir")) null else changes.getInt("rir")) else set.rir,
        )
        return Outcome.Ok(Unit)
    }

    override suspend fun removeSet(setId: String): Outcome<Unit> {
        commands += "gym.set.remove"
        takeFailure()?.let { return Outcome.Failed(it) }
        return if (sets.removeAll { it.id == setId }) Outcome.Ok(Unit) else Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such set"))
    }

    override suspend fun note(sessionId: String, notes: String?, effortNote: String?): Outcome<Unit> {
        commands += "gym.session.note"
        takeFailure()?.let { return Outcome.Failed(it) }
        val current = session?.takeIf { it.id == sessionId }
            ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such workout"))
        session = current.copy(notes = notes, effortNote = effortNote)
        return Outcome.Ok(Unit)
    }

    override suspend fun sessionDetails(sessionId: String): Outcome<GymSessionDetail> {
        commands += "session_details"
        takeFailure()?.let { return Outcome.Failed(it) }
        val current = session?.takeIf { it.id == sessionId }
            ?: return Outcome.Failed(FinanceError(ErrorKind.NotFound, "no such workout"))
        return Outcome.Ok(detail(current))
    }

    override suspend fun recentSessions(limit: Int): Outcome<List<GymSessionSummary>> {
        commands += "list_sessions"
        takeFailure()?.let { return Outcome.Failed(it) }
        return Outcome.Ok(finished.toList())
    }

    override suspend fun previousPerformance(
        exerciseKey: String,
        beforeSessionId: String?,
    ): Outcome<GymPreviousPerformance?> {
        commands += "previous_performance"
        takeFailure()?.let { return Outcome.Failed(it) }
        return Outcome.Ok(null)
    }

    private fun detail(current: GymSession): GymSessionDetail {
        val blocks = sets.groupBy { it.exerciseKey }.map { (key, logged) ->
            val prescription = current.snapshot?.exercises?.firstOrNull { it.exerciseKey == key }
            GymExerciseBlock(
                exerciseKey = key,
                exerciseName = logged.first().exerciseName,
                equipment = logged.first().equipment,
                exerciseOrder = logged.first().exerciseOrder,
                planned = prescription,
                workingSetsLogged = logged.count { it.isWorking },
                workingSetsCompleted = logged.count { it.isWorking && it.completed },
                sets = logged.sortedBy { it.setOrder },
            )
        }.sortedBy { it.exerciseOrder }
        return GymSessionDetail(current, metrics(current), blocks)
    }

    private fun metrics(current: GymSession): GymMetrics {
        val working = sets.filter { it.isWorking }
        val volume = working.filter { it.completed && it.loadSemantics == "external" }
            .groupBy { it.weightUnit }
            .map { (unit, rows) -> GymVolume(unit, rows.sumOf { (it.loadMilli ?: 0) * (it.reps ?: 0) }, rows.size) }
        val elapsed = if (current.endedAt == null) 600L else 2_700L
        return GymMetrics(
            elapsedSeconds = elapsed,
            activeSeconds = elapsed - pausedSeconds,
            pausedSeconds = pausedSeconds,
            exercisesPerformed = sets.map { it.exerciseKey }.distinct().size,
            plannedWorkingSets = current.snapshot?.plannedWorkingSets ?: 0,
            workingSetsCompleted = working.count { it.completed },
            workingSetsPending = working.count { !it.completed },
            warmupSetsCompleted = sets.count { !it.isWorking && it.completed },
            volumeByUnit = volume,
            volumeExcludedSets = working.count { it.completed && it.loadSemantics != "external" },
        )
    }

    companion object {
        /** Day 2 of the reviewed plan plus a rest day, enough for the screens' tests. */
        fun defaultDays(): List<GymPlanDay> = listOf(
            GymPlanDay(
                "day-2",
                1,
                "Pull A: Lat Width + Biceps",
                false,
                listOf(
                    GymPrescription("lat_pulldown", "Lat Pulldown", "Cable", 1, 3, 6, 10, null),
                    GymPrescription("chest_supported_row", "Chest-Supported Row", "Machine", 2, 3, 8, 12, null),
                ),
            ),
            GymPlanDay("day-4", 2, "REST", true, emptyList()),
        )
    }
}
