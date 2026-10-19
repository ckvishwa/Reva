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
)

data class HealthRecord(val id: String, val kind: String, val date: String, val label: String, val scheduleId: String? = null)
data class MedicationSchedule(val id: String, val name: String)

object HealthJson {
    fun daily(day: String, rowsJson: String, sourceIds: List<String>): HealthDaily {
        val row = JSONArray(rowsJson).getJSONObject(0)
        return HealthDaily(day, row.getLong("workout_minutes"), row.getLong("sleep_minutes"), row.getInt("meal_count"),
            if (row.isNull("weight_grams")) null else row.getLong("weight_grams"),
            row.getInt("medications_scheduled"), row.getInt("medications_taken"), sourceIds.distinct().size,
            row.getInt("workout_count"), row.getInt("sleep_count"))
    }
}

interface HealthRepository {
    suspend fun daily(date: String): Outcome<HealthDaily>
    suspend fun records(date: String): Outcome<List<HealthRecord>>
    suspend fun schedules(date: String): Outcome<List<MedicationSchedule>>
    suspend fun command(kind: String, payload: JSONObject): Outcome<Unit>
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
                    "medication_taken" -> "Medication taken · ${row.getString("schedule_id")}"
                    else -> kind
                }
                HealthRecord(row.getString("id"), kind, row.getString("date"), label,
                    if (kind == "medication_taken") row.getString("schedule_id") else null)
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
}
