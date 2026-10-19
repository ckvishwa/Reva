package app.reva.data

import java.time.LocalDate
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.KeyProviderException

data class HealthDaily(
    val date: String,
    val workoutMinutes: Long,
    val sleepMinutes: Long,
    val mealCount: Int,
    val weightGrams: Long?,
    val medicationsScheduled: Int,
    val medicationsTaken: Int,
    val sourceCount: Int,
    val workoutCount: Int = 0,
    val sleepCount: Int = 0,
    val steps: Long? = null,
    val stepsCount: Int = 0,
    val heartRateCount: Int = 0,
    val heartRateMinBpm: Long? = null,
    val heartRateMaxBpm: Long? = null,
    /** "manual" or "health_connect": which record the step total uses. */
    val stepsSource: String? = null,
    /** A manual entry and a Health Connect day disagree; the manual value is used and both are shown. */
    val stepsConflict: Boolean = false,
    val stepsManual: Long? = null,
    val stepsHealthConnect: Long? = null,
)

data class HealthWeekly(
    val startDate: String,
    val endDate: String,
    val workoutMinutes: Long,
    val workoutCount: Int,
    val sleepMinutes: Long,
    val sleepCount: Int,
    val mealCount: Int,
    val medicationExpected: Int,
    val medicationTaken: Int,
    val sourceCount: Int,
    val stepsTotal: Long = 0,
    val stepsDays: Int = 0,
    val heartRateCount: Int = 0,
    val heartRateMinBpm: Long? = null,
    val heartRateMaxBpm: Long? = null,
    val stepsConflictDates: List<String> = emptyList(),
)

data class HealthRecord(
    val id: String,
    val kind: String,
    val date: String,
    val label: String,
    val scheduleId: String? = null,
    val source: String = "manual",
    val origins: List<String> = emptyList(),
)

/** What the Kernel did with each row of a Health import; every row is counted in exactly one bucket. */
data class HealthImportReport(
    val added: Int,
    val updated: Int,
    val duplicates: Int,
    val rejected: List<String>,
    val dryRun: Boolean,
)
data class MedicationSchedule(val id: String, val name: String)

object HealthJson {
    fun weekly(day: String, rowsJson: String, sourceIds: List<String>): HealthWeekly {
        val row = JSONArray(rowsJson).getJSONObject(0)
        return HealthWeekly(row.getString("start_date"), day, row.getLong("workout_minutes"),
            row.getInt("workout_count"), row.getLong("sleep_minutes"), row.getInt("sleep_count"),
            row.getInt("meal_count"), row.getInt("medication_expected"), row.getInt("medication_taken"),
            sourceIds.distinct().size, row.getLong("steps_total"), row.getInt("steps_days"),
            row.getInt("heart_rate_count"),
            if (row.isNull("heart_rate_min_bpm")) null else row.getLong("heart_rate_min_bpm"),
            if (row.isNull("heart_rate_max_bpm")) null else row.getLong("heart_rate_max_bpm"),
            row.optJSONArray("steps_conflict_dates")?.let { dates -> (0 until dates.length()).map(dates::getString) } ?: emptyList())
    }
    fun daily(day: String, rowsJson: String, sourceIds: List<String>): HealthDaily {
        val row = JSONArray(rowsJson).getJSONObject(0)
        return HealthDaily(day, row.getLong("workout_minutes"), row.getLong("sleep_minutes"), row.getInt("meal_count"),
            if (row.isNull("weight_grams")) null else row.getLong("weight_grams"),
            row.getInt("medications_scheduled"), row.getInt("medications_taken"), sourceIds.distinct().size,
            row.getInt("workout_count"), row.getInt("sleep_count"),
            if (row.isNull("steps")) null else row.getLong("steps"), row.getInt("steps_count"),
            row.getInt("heart_rate_count"),
            if (row.isNull("heart_rate_min_bpm")) null else row.getLong("heart_rate_min_bpm"),
            if (row.isNull("heart_rate_max_bpm")) null else row.getLong("heart_rate_max_bpm"),
            row.optStringOrNull("steps_source"), row.optBoolean("steps_conflict", false),
            row.optLongOrNull("steps_manual"), row.optLongOrNull("steps_health_connect"))
    }

    fun importReport(rowsJson: String, dryRun: Boolean): HealthImportReport {
        val rows = JSONArray(rowsJson)
        val statuses = (0 until rows.length()).map { rows.getJSONObject(it) }
        return HealthImportReport(
            added = statuses.count { it.getString("status") == "accepted" },
            updated = statuses.count { it.getString("status") == "updated" },
            duplicates = statuses.count { it.getString("status") == "duplicate" },
            rejected = statuses.filter { it.getString("status") == "rejected" }
                .map { "Row ${it.getLong("row")}: ${it.optString("reason", "rejected")}" },
            dryRun = dryRun,
        )
    }

    private fun JSONObject.optStringOrNull(key: String): String? = if (isNull(key)) null else optString(key)
    private fun JSONObject.optLongOrNull(key: String): Long? = if (isNull(key)) null else getLong(key)
}

interface HealthRepository {
    suspend fun daily(date: String): Outcome<HealthDaily>
    suspend fun weekly(endDate: String): Outcome<HealthWeekly>
    suspend fun records(date: String): Outcome<List<HealthRecord>>
    suspend fun schedules(date: String): Outcome<List<MedicationSchedule>>
    suspend fun command(kind: String, payload: JSONObject): Outcome<Unit>

    /** The `reva-health-v1` JSON backup: a plain, unencrypted copy of every Health record. */
    suspend fun exportJson(): Outcome<ByteArray> = Outcome.Failed(FinanceError(ErrorKind.Validation, "Health export is unavailable."))

    /** `format` is `json` (a Health backup) or `health_connect` (daily aggregates read from Health Connect). */
    suspend fun importData(format: String, bytes: ByteArray, dryRun: Boolean): Outcome<HealthImportReport> =
        Outcome.Failed(FinanceError(ErrorKind.Validation, "Health import is unavailable."))
}

/** Separate encrypted Health domain file and key. Every Kernel operation runs off the UI thread. */
class KernelHealthRepository(
    private val openHandle: () -> DomainHandle,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
) : HealthRepository {
    private val lock = Any()
    private var handle: DomainHandle? = null
    private fun handle(): DomainHandle = synchronized(lock) { handle ?: openHandle().also { handle = it } }

    private suspend fun <T> run(block: (DomainHandle) -> T): Outcome<T> = withContext(dispatcher) {
        try {
            Outcome.Ok(block(handle()))
        } catch (_: KeyProviderException) {
            Outcome.Failed(FinanceError(ErrorKind.KeyLost, "Health is locked. Your records were not changed."))
        } catch (e: DomainException) {
            Outcome.Failed(FinanceError(ErrorKind.Validation, e.message ?: "Health record could not be saved."))
        } catch (_: JSONException) {
            Outcome.Failed(FinanceError(ErrorKind.Corrupt, "Health data could not be read. Your records were not changed."))
        }
    }

    private fun validDate(date: String): String? = try { LocalDate.parse(date).toString() } catch (_: Exception) { null }

    override suspend fun daily(date: String): Outcome<HealthDaily> {
        val day = validDate(date) ?: return Outcome.Failed(FinanceError(ErrorKind.Validation, "Choose a valid date."))
        return run { h ->
            val result = h.query("daily_summary", JSONObject().put("date", day).toString())
            HealthJson.daily(day, result.rowsJson, result.sourceIds)
        }
    }

    override suspend fun weekly(endDate: String): Outcome<HealthWeekly> {
        val day = validDate(endDate) ?: return Outcome.Failed(FinanceError(ErrorKind.Validation, "Choose a valid date."))
        return run { h ->
            val result = h.query("weekly_summary", JSONObject().put("date", day).toString())
            HealthJson.weekly(day, result.rowsJson, result.sourceIds)
        }
    }

    override suspend fun records(date: String): Outcome<List<HealthRecord>> {
        val day = validDate(date) ?: return Outcome.Failed(FinanceError(ErrorKind.Validation, "Choose a valid date."))
        return run { h ->
            val rows = JSONArray(h.query("daily_records", JSONObject().put("date", day).toString()).rowsJson)
            (0 until rows.length()).map { i ->
                val row = rows.getJSONObject(i)
                val kind = row.getString("kind")
                val label = when (kind) {
                    "workout" -> "${row.getString("activity")} · ${row.getLong("duration_minutes")} min"
                    "sleep" -> "Sleep · ${row.getLong("duration_minutes")} min"
                    "meal" -> "Meal · ${row.getString("description")}"
                    "weight" -> "Weight · ${row.getLong("weight_grams")} g"
                    "steps_day" -> "Steps · ${row.getLong("steps")}"
                    "heart_rate_day" -> "Heart rate range · ${row.getLong("min_bpm")}-${row.getLong("max_bpm")} bpm in ${row.getLong("samples")} samples"
                    "heart_rate_sample" -> "Heart rate · ${row.getLong("bpm")} bpm"
                    "medication_taken" -> "Medication taken · ${row.getString("schedule_id")}"
                    else -> kind
                }
                val source = row.optString("source", "manual")
                val origins = row.optJSONArray("origins")?.let { list -> (0 until list.length()).map(list::getString) } ?: emptyList()
                HealthRecord(row.getString("id"), kind, row.getString("date"),
                    if (source == "health_connect") "$label · from Health Connect" else label,
                    if (kind == "medication_taken") row.getString("schedule_id") else null, source, origins)
            }
        }
    }

    override suspend fun schedules(date: String): Outcome<List<MedicationSchedule>> {
        val day = validDate(date) ?: return Outcome.Failed(FinanceError(ErrorKind.Validation, "Choose a valid date."))
        return run { h ->
            val rows = JSONArray(h.query("list_schedules", JSONObject().put("date", day).toString()).rowsJson)
            (0 until rows.length()).map { i -> rows.getJSONObject(i).let { MedicationSchedule(it.getString("id"), it.getString("name")) } }
        }
    }

    override suspend fun command(kind: String, payload: JSONObject): Outcome<Unit> = run { h -> h.command(kind, payload.toString()); Unit }

    override suspend fun exportJson(): Outcome<ByteArray> = run { h -> h.export("json") }

    override suspend fun importData(format: String, bytes: ByteArray, dryRun: Boolean): Outcome<HealthImportReport> {
        if (format != "json" && format != "health_connect") {
            return Outcome.Failed(FinanceError(ErrorKind.Validation, "Choose a REVA Health backup file."))
        }
        return run { h ->
            val report = h.importData(format, bytes, JSONObject().put("dry_run", dryRun).toString())
            HealthJson.importReport(report.rowsJson, report.dryRun)
        }
    }
}
