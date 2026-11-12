package app.reva.healthconnect

import app.reva.data.HealthImportReport
import app.reva.data.HealthRepository
import app.reva.data.Outcome
import java.time.LocalDate
import org.json.JSONArray
import org.json.JSONObject

/**
 * The Health Connect data REVA may READ, one permission per type so the user can allow one and not the other.
 * REVA never writes to Health Connect and declares no write permission (ManifestTest checks this).
 */
enum class HealthConnectType(val permission: String, val label: String, val reason: String) {
    Steps(
        "android.permission.health.READ_STEPS",
        "Steps",
        "Daily step totals, so Health and Today can show your steps without typing them in.",
    ),
    HeartRate(
        "android.permission.health.READ_HEART_RATE",
        "Heart rate",
        "The lowest and highest reading and the number of readings per day. REVA does not interpret them.",
    ),
}

enum class HealthConnectStatus { Available, NeedsUpdate, Unavailable }

/** Health Connect's own de-duplicated daily total (its aggregation counts each step once across apps). */
data class DailySteps(val date: LocalDate, val steps: Long, val origins: Set<String>)
data class DailyHeartRate(val date: LocalDate, val minBpm: Long, val maxBpm: Long, val samples: Long, val origins: Set<String>)

/** The narrow surface REVA uses. The real one wraps HealthConnectClient; tests use a fake. */
interface HealthConnectGateway {
    fun status(): HealthConnectStatus
    /** Asked again before every read: the user can revoke a type in system settings at any moment. */
    suspend fun grantedTypes(): Set<HealthConnectType>
    /** One entry per local day in [start, end] that has data. Throws SecurityException if access was revoked. */
    suspend fun dailySteps(start: LocalDate, end: LocalDate): List<DailySteps>
    suspend fun dailyHeartRate(start: LocalDate, end: LocalDate): List<DailyHeartRate>
}

sealed interface HealthConnectImport {
    data class Unavailable(val status: HealthConnectStatus) : HealthConnectImport
    data object NothingAllowed : HealthConnectImport
    /** [read] are the types read in this run; [revoked] were allowed when checked but refused when read. */
    data class Done(val report: HealthImportReport, val read: Set<HealthConnectType>, val revoked: Set<HealthConnectType>) : HealthConnectImport
    data class Failed(val message: String) : HealthConnectImport
}

/**
 * Reads the last [days] days of allowed types and hands them to the Health Kernel as one `health_connect` import.
 * The Kernel stores one record per day and type with the reported origins, so importing again updates or confirms
 * the same records: steps are never counted twice, and a day the user deleted is not brought back.
 */
class HealthConnectImporter(
    private val gateway: HealthConnectGateway,
    private val repository: HealthRepository,
    private val today: () -> LocalDate = LocalDate::now,
) {
    suspend fun import(days: Long = DEFAULT_DAYS): HealthConnectImport {
        val status = gateway.status()
        if (status != HealthConnectStatus.Available) return HealthConnectImport.Unavailable(status)
        val granted = try {
            gateway.grantedTypes()
        } catch (e: Exception) {
            return HealthConnectImport.Failed("Health Connect did not answer. Nothing was imported.")
        }
        if (granted.isEmpty()) return HealthConnectImport.NothingAllowed
        val end = today()
        val start = end.minusDays(days.coerceIn(1, MAX_DAYS) - 1)
        val entries = JSONArray()
        val read = mutableSetOf<HealthConnectType>()
        val revoked = mutableSetOf<HealthConnectType>()
        for (type in HealthConnectType.entries.filter { it in granted }) {
            try {
                when (type) {
                    HealthConnectType.Steps -> gateway.dailySteps(start, end).forEach {
                        entries.put(JSONObject().put("date", it.date.toString()).put("type", "steps").put("steps", it.steps).put("origins", JSONArray(it.origins.sorted())))
                    }
                    HealthConnectType.HeartRate -> gateway.dailyHeartRate(start, end).forEach {
                        entries.put(
                            JSONObject().put("date", it.date.toString()).put("type", "heart_rate").put("min_bpm", it.minBpm)
                                .put("max_bpm", it.maxBpm).put("samples", it.samples).put("origins", JSONArray(it.origins.sorted())),
                        )
                    }
                }
                read += type
            } catch (_: SecurityException) {
                revoked += type
            }
        }
        if (read.isEmpty()) return HealthConnectImport.Done(HealthImportReport(0, 0, 0, emptyList(), false), read, revoked)
        val payload = JSONObject().put("format", FORMAT).put("days", entries).toString().toByteArray(Charsets.UTF_8)
        return when (val result = repository.importData("health_connect", payload, dryRun = false)) {
            is Outcome.Ok -> HealthConnectImport.Done(result.value, read, revoked)
            is Outcome.Failed -> HealthConnectImport.Failed(result.error.message)
        }
    }

    companion object {
        const val FORMAT = "reva-health-connect-v1"
        /** Health Connect lets an app read 30 days before its first grant without the history permission. */
        const val DEFAULT_DAYS = 30L
        const val MAX_DAYS = 30L
    }
}

/** Plain-language result for the Health screen. Never claims more than the Kernel report says. */
fun HealthConnectImport.summary(): String = when (this) {
    is HealthConnectImport.Unavailable -> when (status) {
        HealthConnectStatus.NeedsUpdate -> "Health Connect needs an update before REVA can read from it."
        else -> "Health Connect is not available on this phone."
    }
    HealthConnectImport.NothingAllowed -> "No Health Connect data type is allowed. Nothing was read."
    is HealthConnectImport.Failed -> message
    is HealthConnectImport.Done -> buildString {
        append("Read ${if (read.isEmpty()) "nothing" else read.joinToString { it.label.lowercase() }}. ")
        append("${report.added} new, ${report.updated} updated, ${report.duplicates} unchanged")
        if (report.rejected.isNotEmpty()) append(", ${report.rejected.size} skipped")
        append(".")
        if (revoked.isNotEmpty()) append(" Access to ${revoked.joinToString { it.label.lowercase() }} was turned off, so it was not read.")
    }
}
