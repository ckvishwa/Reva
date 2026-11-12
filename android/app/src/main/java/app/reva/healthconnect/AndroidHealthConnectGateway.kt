package app.reva.healthconnect

import android.content.Context
import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateGroupByPeriodRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.LocalDate
import java.time.Period

/**
 * Health Connect through androidx.health.connect. Only aggregate reads: Health Connect merges overlapping data from
 * several apps itself, so a step is counted once whichever apps recorded it. Nothing is written back.
 */
class AndroidHealthConnectGateway(private val context: Context) : HealthConnectGateway {
    private val client by lazy { HealthConnectClient.getOrCreate(context) }

    override fun status(): HealthConnectStatus = when (HealthConnectClient.getSdkStatus(context)) {
        HealthConnectClient.SDK_AVAILABLE -> HealthConnectStatus.Available
        HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> HealthConnectStatus.NeedsUpdate
        else -> HealthConnectStatus.Unavailable
    }

    override suspend fun grantedTypes(): Set<HealthConnectType> {
        val granted = client.permissionController.getGrantedPermissions()
        return HealthConnectType.entries.filter { permission(it) in granted }.toSet()
    }

    override suspend fun dailySteps(start: LocalDate, end: LocalDate): List<DailySteps> =
        client.aggregateGroupByPeriod(request(setOf(StepsRecord.COUNT_TOTAL), start, end)).mapNotNull { day ->
            val steps = day.result[StepsRecord.COUNT_TOTAL] ?: return@mapNotNull null
            DailySteps(day.startTime.toLocalDate(), steps, day.result.dataOrigins.map { it.packageName }.toSet())
        }

    override suspend fun dailyHeartRate(start: LocalDate, end: LocalDate): List<DailyHeartRate> {
        val metrics = setOf(HeartRateRecord.BPM_MIN, HeartRateRecord.BPM_MAX, HeartRateRecord.MEASUREMENTS_COUNT)
        return client.aggregateGroupByPeriod(request(metrics, start, end)).mapNotNull { day ->
            val min = day.result[HeartRateRecord.BPM_MIN] ?: return@mapNotNull null
            val max = day.result[HeartRateRecord.BPM_MAX] ?: return@mapNotNull null
            val samples = day.result[HeartRateRecord.MEASUREMENTS_COUNT] ?: return@mapNotNull null
            DailyHeartRate(day.startTime.toLocalDate(), min, max, samples, day.result.dataOrigins.map { it.packageName }.toSet())
        }
    }

    /** Local calendar days, so a day here is the same day the Health screen shows. */
    private fun request(metrics: Set<androidx.health.connect.client.aggregate.AggregateMetric<*>>, start: LocalDate, end: LocalDate) =
        AggregateGroupByPeriodRequest(metrics, TimeRangeFilter.between(start.atStartOfDay(), end.plusDays(1).atStartOfDay()), Period.ofDays(1))

    companion object {
        fun permission(type: HealthConnectType): String = when (type) {
            HealthConnectType.Steps -> HealthPermission.getReadPermission(StepsRecord::class)
            HealthConnectType.HeartRate -> HealthPermission.getReadPermission(HeartRateRecord::class)
        }

        /** The system permission sheet for exactly the types passed in. */
        fun requestContract(): ActivityResultContract<Set<String>, Set<String>> = PermissionController.createRequestPermissionResultContract()

        /** Health Connect's own settings, where the user can see and revoke what REVA may read. */
        fun settingsIntent(): Intent = Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)
    }
}
