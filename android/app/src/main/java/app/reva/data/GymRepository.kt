package app.reva.data

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.KeyProviderException

/**
 * GYM-01: the training program, the live workout and the finished session's receipt, read from
 * and written to the Health domain in the Rust Kernel.
 *
 * Nothing here decides anything: every rule, every total and every duration comes from the Kernel,
 * so the phone and the PC can never disagree about a number the user sees. This file only turns the
 * Kernel's JSON into Kotlin and back.
 */

/** Thousandths of a unit, so 2.5 lb steps and 55 lb are exact and nothing is rounded for the user. */
const val GYM_LOAD_SCALE = 1_000L

/** `55000` with unit `lb` reads as "55 lb"; `52500` reads as "52.5 lb". */
fun formatLoad(loadMilli: Long?, unit: String): String? {
    if (loadMilli == null) return null
    val whole = loadMilli / GYM_LOAD_SCALE
    val fraction = loadMilli % GYM_LOAD_SCALE
    return if (fraction == 0L) "$whole $unit" else "${"%.3f".format(loadMilli / GYM_LOAD_SCALE.toDouble()).trimEnd('0').trimEnd('.')} $unit"
}

/** `"55"` and `"52.5"` become 55000 and 52500. Returns null for anything that is not a load. */
fun parseLoadMilli(text: String): Long? {
    val cleaned = text.trim().replace(',', '.')
    if (cleaned.isEmpty()) return null
    val value = cleaned.toDoubleOrNull() ?: return null
    if (value < 0 || value > 2_000) return null
    return Math.round(value * GYM_LOAD_SCALE)
}

fun formatDuration(seconds: Long): String {
    val total = if (seconds < 0) 0 else seconds
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%02d:%02d".format(m, s)
}

data class GymPrescription(
    val exerciseKey: String,
    val name: String,
    val equipment: String?,
    val order: Int,
    val plannedSets: Int,
    val minReps: Int,
    val maxReps: Int,
    val restSeconds: Int?,
) {
    val repRange: String get() = if (minReps == maxReps) "$minReps reps" else "$minReps-$maxReps reps"
    val target: String get() = "$plannedSets x $repRange"
}

data class GymPlanDay(
    val dayId: String,
    val dayIndex: Int,
    val label: String,
    val isRest: Boolean,
    val exercises: List<GymPrescription>,
) {
    val plannedWorkingSets: Int get() = exercises.sumOf { it.plannedSets }
}

data class GymProgram(
    val id: String,
    val name: String,
    val anchorDate: String,
    val planVersion: Int,
    val days: List<GymPlanDay>,
) {
    fun day(dayId: String): GymPlanDay? = days.firstOrNull { it.dayId == dayId }
}

/** What the plan prescribed for this session, kept as it was on the day it ran. */
data class GymSetRecord(
    val id: String,
    val exerciseKey: String,
    val exerciseName: String,
    val equipment: String?,
    val exerciseOrder: Int,
    val setOrder: Int,
    val setType: String,
    val loadMilli: Long?,
    val weightUnit: String,
    val loadSemantics: String,
    val reps: Int?,
    val rir: Int?,
    val completed: Boolean,
    val completedAt: String?,
    val notes: String?,
) {
    val isWorking: Boolean get() = setType == "working"
    val load: String? get() = formatLoad(loadMilli, weightUnit)
}

data class GymSession(
    val id: String,
    val programId: String,
    val planVersion: Int,
    val dayId: String,
    val label: String,
    val state: String,
    val date: String,
    val startedAt: String,
    val endedAt: String?,
    val notes: String?,
    val effortNote: String?,
    val snapshot: GymPlanDay?,
) {
    val isPaused: Boolean get() = state == "paused"
    val isOpen: Boolean get() = state == "in_progress" || state == "paused"
    val isCompleted: Boolean get() = state == "completed"
}

data class GymVolume(val unit: String, val volumeMilli: Long, val sets: Int) {
    val text: String get() = formatLoad(volumeMilli, unit) ?: "0 $unit"
}

data class GymMetrics(
    val elapsedSeconds: Long,
    val activeSeconds: Long,
    val pausedSeconds: Long,
    val exercisesPerformed: Int,
    val plannedWorkingSets: Int,
    val workingSetsCompleted: Int,
    val workingSetsPending: Int,
    val warmupSetsCompleted: Int,
    val volumeByUnit: List<GymVolume>,
    val volumeExcludedSets: Int,
)

data class GymExerciseBlock(
    val exerciseKey: String,
    val exerciseName: String,
    val equipment: String?,
    val exerciseOrder: Int,
    val planned: GymPrescription?,
    val workingSetsLogged: Int,
    val workingSetsCompleted: Int,
    val sets: List<GymSetRecord>,
)

data class GymSessionDetail(
    val session: GymSession,
    val metrics: GymMetrics,
    val exercises: List<GymExerciseBlock>,
) {
    fun blockFor(exerciseKey: String): GymExerciseBlock? = exercises.firstOrNull { it.exerciseKey == exerciseKey }
}

data class GymSessionSummary(
    val id: String,
    val label: String,
    val dayId: String,
    val date: String,
    val state: String,
    val metrics: GymMetrics,
)

/** The last completed session that holds working sets for one exercise. Absent means no record. */
data class GymPreviousPerformance(
    val exerciseKey: String,
    val sessionId: String,
    val date: String,
    val label: String,
    val sets: List<GymSetRecord>,
) {
    /** "55 lb x 10, 9, 8" - what was actually done, never a suggestion. */
    val summary: String
        get() {
            val first = sets.firstOrNull() ?: return "No previous record."
            val sameLoad = sets.all { it.loadMilli == first.loadMilli && it.weightUnit == first.weightUnit }
            val reps = sets.joinToString(", ") { it.reps?.toString() ?: "-" }
            return if (sameLoad && first.load != null) "${first.load} x $reps" else sets.joinToString(", ") {
                "${it.load ?: "-"} x ${it.reps ?: "-"}"
            }
        }
}

/** One logged set on its way to the Kernel. The Kernel, not this class, decides whether it is valid. */
data class GymSetInput(
    val exerciseKey: String,
    val setType: String = "working",
    val loadMilli: Long? = null,
    val weightUnit: String = "lb",
    val loadSemantics: String = "external",
    val reps: Int? = null,
    val rir: Int? = null,
    val completed: Boolean = true,
    val notes: String? = null,
    val exerciseName: String? = null,
)

object GymJson {
    fun program(rowsJson: String): GymProgram? {
        val rows = JSONArray(rowsJson)
        if (rows.length() == 0) return null
        val row = rows.getJSONObject(0)
        return GymProgram(
            id = row.getString("id"),
            name = row.getString("name"),
            anchorDate = row.getString("anchor_date"),
            planVersion = row.getInt("plan_version"),
            days = row.getJSONArray("days").objects().map(::planDay),
        )
    }

    fun planDay(row: JSONObject): GymPlanDay = GymPlanDay(
        dayId = row.getString("day_id"),
        dayIndex = row.getInt("day_index"),
        label = row.getString("label"),
        isRest = row.getString("day_type") == "rest",
        exercises = row.getJSONArray("exercises").objects().map { e ->
            GymPrescription(
                exerciseKey = e.getString("exercise_key"),
                name = e.getString("name"),
                equipment = e.stringOrNull("equipment"),
                order = e.getInt("order"),
                plannedSets = e.getInt("planned_sets"),
                minReps = e.getInt("min_reps"),
                maxReps = e.getInt("max_reps"),
                restSeconds = e.intOrNull("rest_seconds"),
            )
        },
    )

    fun session(row: JSONObject): GymSession = GymSession(
        id = row.getString("id"),
        programId = row.getString("program_id"),
        planVersion = row.getInt("plan_version"),
        dayId = row.getString("day_id"),
        label = row.getString("label"),
        state = row.getString("state"),
        date = row.getString("date"),
        startedAt = row.getString("started_at"),
        endedAt = row.stringOrNull("ended_at"),
        notes = row.stringOrNull("notes"),
        effortNote = row.stringOrNull("effort_note"),
        snapshot = row.optJSONObject("plan_snapshot")?.let(::planDay),
    )

    fun set(row: JSONObject): GymSetRecord = GymSetRecord(
        id = row.getString("id"),
        exerciseKey = row.getString("exercise_key"),
        exerciseName = row.getString("exercise_name"),
        equipment = row.stringOrNull("equipment"),
        exerciseOrder = row.getInt("exercise_order"),
        setOrder = row.getInt("set_order"),
        setType = row.getString("set_type"),
        loadMilli = row.longOrNull("load_milli"),
        weightUnit = row.getString("weight_unit"),
        loadSemantics = row.getString("load_semantics"),
        reps = row.intOrNull("reps"),
        rir = row.intOrNull("rir"),
        completed = row.getBoolean("completed"),
        completedAt = row.stringOrNull("completed_at"),
        notes = row.stringOrNull("notes"),
    )

    fun metrics(row: JSONObject): GymMetrics = GymMetrics(
        elapsedSeconds = row.getLong("elapsed_seconds"),
        activeSeconds = row.getLong("active_seconds"),
        pausedSeconds = row.getLong("paused_seconds"),
        exercisesPerformed = row.getInt("exercises_performed"),
        plannedWorkingSets = row.getInt("planned_working_sets"),
        workingSetsCompleted = row.getInt("working_sets_completed"),
        workingSetsPending = row.getInt("working_sets_pending"),
        warmupSetsCompleted = row.getInt("warmup_sets_completed"),
        volumeByUnit = row.getJSONArray("volume_by_unit").objects().map {
            GymVolume(it.getString("unit"), it.getLong("volume_milli"), it.getInt("sets"))
        },
        volumeExcludedSets = row.getInt("volume_excluded_sets"),
    )

    fun detail(rowsJson: String): GymSessionDetail? {
        val rows = JSONArray(rowsJson)
        if (rows.length() == 0) return null
        val row = rows.getJSONObject(0)
        return GymSessionDetail(
            session = session(row.getJSONObject("session")),
            metrics = metrics(row.getJSONObject("metrics")),
            exercises = row.getJSONArray("exercises").objects().map { block ->
                GymExerciseBlock(
                    exerciseKey = block.getString("exercise_key"),
                    exerciseName = block.getString("exercise_name"),
                    equipment = block.stringOrNull("equipment"),
                    exerciseOrder = block.getInt("exercise_order"),
                    planned = block.optJSONObject("planned")?.let {
                        GymPrescription(
                            exerciseKey = block.getString("exercise_key"),
                            name = block.getString("exercise_name"),
                            equipment = block.stringOrNull("equipment"),
                            order = block.getInt("exercise_order"),
                            plannedSets = it.getInt("planned_sets"),
                            minReps = it.getInt("min_reps"),
                            maxReps = it.getInt("max_reps"),
                            restSeconds = null,
                        )
                    },
                    workingSetsLogged = block.getInt("working_sets_logged"),
                    workingSetsCompleted = block.getInt("working_sets_completed"),
                    sets = block.getJSONArray("sets").objects().map(::set),
                )
            },
        )
    }

    fun sessions(rowsJson: String): List<GymSessionSummary> = JSONArray(rowsJson).objects().map { row ->
        GymSessionSummary(
            id = row.getString("id"),
            label = row.getString("label"),
            dayId = row.getString("day_id"),
            date = row.getString("date"),
            state = row.getString("state"),
            metrics = metrics(row.getJSONObject("metrics")),
        )
    }

    fun previous(rowsJson: String): GymPreviousPerformance? {
        val rows = JSONArray(rowsJson)
        if (rows.length() == 0) return null
        val row = rows.getJSONObject(0)
        return GymPreviousPerformance(
            exerciseKey = row.getString("exercise_key"),
            sessionId = row.getString("session_id"),
            date = row.getString("date"),
            label = row.getString("label"),
            sets = row.getJSONArray("sets").objects().map(::set),
        )
    }

    fun setPayload(sessionId: String, input: GymSetInput): JSONObject {
        val payload = JSONObject()
            .put("session_id", sessionId)
            .put("exercise_key", input.exerciseKey)
            .put("set_type", input.setType)
            .put("weight_unit", input.weightUnit)
            .put("load_semantics", input.loadSemantics)
            .put("completed", input.completed)
        input.loadMilli?.let { payload.put("load_milli", it) }
        input.reps?.let { payload.put("reps", it) }
        input.rir?.let { payload.put("rir", it) }
        input.notes?.let { payload.put("notes", it) }
        input.exerciseName?.let { payload.put("exercise_name", it) }
        return payload
    }

    /** The plan as the Kernel's `gym.program.update` expects it back. */
    fun daysPayload(days: List<GymPlanDay>): JSONArray {
        val out = JSONArray()
        days.forEachIndexed { index, day ->
            val exercises = JSONArray()
            day.exercises.forEachIndexed { position, e ->
                exercises.put(
                    JSONObject()
                        .put("exercise_key", e.exerciseKey)
                        .put("name", e.name)
                        .put("equipment", e.equipment ?: JSONObject.NULL)
                        .put("order", position + 1)
                        .put("planned_sets", e.plannedSets)
                        .put("min_reps", e.minReps)
                        .put("max_reps", e.maxReps)
                        .put("rest_seconds", e.restSeconds ?: JSONObject.NULL),
                )
            }
            out.put(
                JSONObject()
                    .put("day_id", day.dayId)
                    .put("day_index", index + 1)
                    .put("label", day.label)
                    .put("day_type", if (day.isRest) "rest" else "training")
                    .put("exercises", exercises),
            )
        }
        return out
    }

    private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map(::getJSONObject)
    private fun JSONObject.stringOrNull(key: String): String? = if (isNull(key)) null else optString(key)
    private fun JSONObject.intOrNull(key: String): Int? = if (isNull(key)) null else getInt(key)
    private fun JSONObject.longOrNull(key: String): Long? = if (isNull(key)) null else getLong(key)
}

/**
 * Everything the three Gym screens need. Suspend functions: the real implementation runs every
 * Kernel call on Dispatchers.IO, never on the main thread (AR-DOM-015). Tests use a fake.
 */
interface GymRepository {
    suspend fun activeProgram(): Outcome<GymProgram?>

    /** Creates the reviewed default program. Refused with a conflict if one already exists. */
    suspend fun createDefaultProgram(anchorDate: String? = null): Outcome<GymProgram>

    suspend fun updatePlan(programId: String, days: List<GymPlanDay>): Outcome<GymProgram>

    /** The workout still in progress or paused, recovered after a restart. Null when there is none. */
    suspend fun activeSession(): Outcome<GymSessionDetail?>

    suspend fun startWorkout(programId: String, dayId: String): Outcome<String>

    suspend fun pause(sessionId: String): Outcome<Unit>

    suspend fun resume(sessionId: String): Outcome<Unit>

    suspend fun addSet(sessionId: String, input: GymSetInput): Outcome<String>

    suspend fun updateSet(sessionId: String, setId: String, changes: JSONObject): Outcome<Unit>

    suspend fun removeSet(setId: String): Outcome<Unit>

    suspend fun note(sessionId: String, notes: String?, effortNote: String?): Outcome<Unit>

    suspend fun complete(sessionId: String): Outcome<Unit>

    suspend fun discard(sessionId: String): Outcome<Unit>

    suspend fun delete(sessionId: String): Outcome<Unit>

    suspend fun sessionDetails(sessionId: String): Outcome<GymSessionDetail>

    suspend fun recentSessions(limit: Int = 20): Outcome<List<GymSessionSummary>>

    suspend fun previousPerformance(exerciseKey: String, beforeSessionId: String?): Outcome<GymPreviousPerformance?>
}

/**
 * The Gym tables live in the Health domain file, so this shares the Health domain handle: one
 * encrypted file, one key, one event log.
 */
class KernelGymRepository(
    private val openHandle: () -> DomainHandle,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
) : GymRepository {
    private val lock = Any()
    private var handle: DomainHandle? = null
    private fun handle(): DomainHandle = synchronized(lock) { handle ?: openHandle().also { handle = it } }

    private suspend fun <T> run(block: (DomainHandle) -> T): Outcome<T> = withContext(dispatcher) {
        try {
            Outcome.Ok(block(handle()))
        } catch (_: KeyProviderException) {
            Outcome.Failed(FinanceError(ErrorKind.KeyLost, "Gym is locked. Your workouts were not changed."))
        } catch (e: DomainException) {
            // The same words the Finance screens show, so one Kernel refusal reads the same everywhere.
            Outcome.Failed(KernelFinanceRepository.translate(e))
        } catch (_: JSONException) {
            Outcome.Failed(FinanceError(ErrorKind.Corrupt, "Workout data could not be read. Nothing was changed."))
        }
    }

    private fun DomainHandle.ask(name: String, params: JSONObject = JSONObject()) =
        query(name, params.toString())

    override suspend fun activeProgram(): Outcome<GymProgram?> =
        run { h -> GymJson.program(h.ask("active_program").rowsJson) }

    override suspend fun createDefaultProgram(anchorDate: String?): Outcome<GymProgram> = run { h ->
        val payload = JSONObject()
        anchorDate?.let { payload.put("anchor_date", it) }
        h.command("gym.program.create_default", payload.toString())
        GymJson.program(h.ask("active_program").rowsJson) ?: error("the program was not stored")
    }

    override suspend fun updatePlan(programId: String, days: List<GymPlanDay>): Outcome<GymProgram> = run { h ->
        val payload = JSONObject().put("program_id", programId).put("days", GymJson.daysPayload(days))
        h.command("gym.program.update", payload.toString())
        GymJson.program(h.ask("active_program").rowsJson) ?: error("the program was not stored")
    }

    override suspend fun activeSession(): Outcome<GymSessionDetail?> =
        run { h -> GymJson.detail(h.ask("active_session").rowsJson) }

    override suspend fun startWorkout(programId: String, dayId: String): Outcome<String> = run { h ->
        val payload = JSONObject().put("program_id", programId).put("day_id", dayId)
        h.command("gym.session.start", payload.toString()).aggregateId
    }

    override suspend fun pause(sessionId: String): Outcome<Unit> = session("gym.session.pause", sessionId)

    override suspend fun resume(sessionId: String): Outcome<Unit> = session("gym.session.resume", sessionId)

    override suspend fun complete(sessionId: String): Outcome<Unit> = session("gym.session.complete", sessionId)

    override suspend fun discard(sessionId: String): Outcome<Unit> = session("gym.session.discard", sessionId)

    override suspend fun delete(sessionId: String): Outcome<Unit> = session("gym.session.delete", sessionId)

    private suspend fun session(kind: String, sessionId: String): Outcome<Unit> = run { h ->
        h.command(kind, JSONObject().put("session_id", sessionId).toString())
        Unit
    }

    override suspend fun addSet(sessionId: String, input: GymSetInput): Outcome<String> = run { h ->
        h.command("gym.set.add", GymJson.setPayload(sessionId, input).toString()).aggregateId
    }

    override suspend fun updateSet(sessionId: String, setId: String, changes: JSONObject): Outcome<Unit> = run { h ->
        h.command("gym.set.update", JSONObject(changes.toString()).put("set_id", setId).toString())
        Unit
    }

    override suspend fun removeSet(setId: String): Outcome<Unit> = run { h ->
        h.command("gym.set.remove", JSONObject().put("set_id", setId).toString())
        Unit
    }

    override suspend fun note(sessionId: String, notes: String?, effortNote: String?): Outcome<Unit> = run { h ->
        val payload = JSONObject().put("session_id", sessionId)
        payload.put("notes", notes ?: JSONObject.NULL)
        payload.put("effort_note", effortNote ?: JSONObject.NULL)
        h.command("gym.session.note", payload.toString())
        Unit
    }

    override suspend fun sessionDetails(sessionId: String): Outcome<GymSessionDetail> = run { h ->
        GymJson.detail(h.ask("session_details", JSONObject().put("session_id", sessionId)).rowsJson)
            ?: error("the session was not found")
    }

    override suspend fun recentSessions(limit: Int): Outcome<List<GymSessionSummary>> =
        run { h -> GymJson.sessions(h.ask("list_sessions", JSONObject().put("limit", limit)).rowsJson) }

    override suspend fun previousPerformance(
        exerciseKey: String,
        beforeSessionId: String?,
    ): Outcome<GymPreviousPerformance?> = run { h ->
        val payload = JSONObject().put("exercise_key", exerciseKey)
        beforeSessionId?.let { payload.put("before_session_id", it) }
        GymJson.previous(h.ask("previous_performance", payload).rowsJson)
    }
}
