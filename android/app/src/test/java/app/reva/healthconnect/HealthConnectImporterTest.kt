package app.reva.healthconnect

import app.reva.data.HealthDaily
import app.reva.data.HealthImportReport
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import java.time.LocalDate
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HealthConnectImporterTest {
    private val day = LocalDate.parse("2026-10-18")

    private class FakeGateway(
        var status: HealthConnectStatus = HealthConnectStatus.Available,
        var granted: Set<HealthConnectType> = HealthConnectType.entries.toSet(),
        var refuseOnRead: Set<HealthConnectType> = emptySet(),
    ) : HealthConnectGateway {
        val reads = mutableListOf<Pair<HealthConnectType, ClosedRange<LocalDate>>>()
        var grantChecks = 0
        override fun status() = status
        override suspend fun grantedTypes(): Set<HealthConnectType> { grantChecks++; return granted }
        override suspend fun dailySteps(start: LocalDate, end: LocalDate): List<DailySteps> {
            if (HealthConnectType.Steps in refuseOnRead) throw SecurityException("revoked")
            reads += HealthConnectType.Steps to start..end
            return listOf(DailySteps(end, 6000, setOf("com.example.watch", "com.example.phone")))
        }
        override suspend fun dailyHeartRate(start: LocalDate, end: LocalDate): List<DailyHeartRate> {
            if (HealthConnectType.HeartRate in refuseOnRead) throw SecurityException("revoked")
            reads += HealthConnectType.HeartRate to start..end
            return listOf(DailyHeartRate(end, 55, 120, 300, setOf("com.example.watch")))
        }
    }

    private class RecordingRepo : HealthRepository {
        val imports = mutableListOf<Pair<String, JSONObject>>()
        override suspend fun daily(date: String) = Outcome.Ok(HealthDaily(date, 0, 0, 0, null, 0, 0, 0))
        override suspend fun weekly(endDate: String) = Outcome.Ok(HealthWeekly(endDate, endDate, 0, 0, 0, 0, 0, 0, 0, 0))
        override suspend fun records(date: String) = Outcome.Ok(emptyList<HealthRecord>())
        override suspend fun schedules(date: String) = Outcome.Ok(emptyList<MedicationSchedule>())
        override suspend fun command(kind: String, payload: JSONObject) = Outcome.Ok(Unit)
        override suspend fun importData(format: String, bytes: ByteArray, dryRun: Boolean): Outcome<HealthImportReport> {
            assertFalse("Health Connect imports are never dry runs", dryRun)
            imports += format to JSONObject(String(bytes))
            return Outcome.Ok(HealthImportReport(JSONObject(String(bytes)).getJSONArray("days").length(), 0, 0, emptyList(), false))
        }
    }

    @Test fun reads_only_allowed_types_for_the_last_30_local_days_and_hands_the_kernel_one_import() = runBlocking {
        val gateway = FakeGateway(granted = setOf(HealthConnectType.Steps))
        val repo = RecordingRepo()
        val result = HealthConnectImporter(gateway, repo) { day }.import()

        assertTrue(result is HealthConnectImport.Done)
        assertEquals(listOf(HealthConnectType.Steps), gateway.reads.map { it.first })
        assertEquals(LocalDate.parse("2026-09-19")..day, gateway.reads.single().second)
        val (format, payload) = repo.imports.single()
        assertEquals("health_connect", format)
        assertEquals("reva-health-connect-v1", payload.getString("format"))
        val entry = payload.getJSONArray("days").getJSONObject(0)
        assertEquals("steps", entry.getString("type"))
        assertEquals(6000, entry.getLong("steps"))
        assertEquals("[\"com.example.phone\",\"com.example.watch\"]", entry.getJSONArray("origins").toString())
    }

    @Test fun grants_are_checked_again_on_every_import_and_nothing_is_read_once_all_are_revoked() = runBlocking {
        val gateway = FakeGateway()
        val repo = RecordingRepo()
        val importer = HealthConnectImporter(gateway, repo) { day }
        importer.import()
        gateway.granted = emptySet()
        val second = importer.import()
        assertEquals(2, gateway.grantChecks)
        assertEquals(HealthConnectImport.NothingAllowed, second)
        assertEquals("only the first run read anything", 2, gateway.reads.size)
        assertEquals(1, repo.imports.size)
    }

    @Test fun a_type_revoked_between_the_check_and_the_read_is_skipped_and_reported() = runBlocking {
        val gateway = FakeGateway(refuseOnRead = setOf(HealthConnectType.HeartRate))
        val repo = RecordingRepo()
        val result = HealthConnectImporter(gateway, repo) { day }.import() as HealthConnectImport.Done
        assertEquals(setOf(HealthConnectType.Steps), result.read)
        assertEquals(setOf(HealthConnectType.HeartRate), result.revoked)
        val days = repo.imports.single().second.getJSONArray("days")
        assertEquals(1, days.length())
        assertTrue(result.summary().contains("Access to heart rate was turned off"))
    }

    @Test fun nothing_is_read_or_imported_when_health_connect_is_missing_or_every_read_is_refused() = runBlocking {
        val repo = RecordingRepo()
        val missing = HealthConnectImporter(FakeGateway(status = HealthConnectStatus.Unavailable), repo) { day }.import()
        assertEquals(HealthConnectImport.Unavailable(HealthConnectStatus.Unavailable), missing)
        val update = HealthConnectImporter(FakeGateway(status = HealthConnectStatus.NeedsUpdate), repo) { day }.import()
        assertTrue(update.summary().contains("needs an update"))
        val refused = HealthConnectImporter(FakeGateway(refuseOnRead = HealthConnectType.entries.toSet()), repo) { day }.import()
        assertTrue(refused is HealthConnectImport.Done && refused.read.isEmpty())
        assertEquals(0, repo.imports.size)
    }

    @Test fun permissions_are_read_only_one_per_type() {
        val permissions = HealthConnectType.entries.map { it.permission }
        assertEquals(listOf("android.permission.health.READ_STEPS", "android.permission.health.READ_HEART_RATE"), permissions)
        assertTrue(permissions.none { it.contains("WRITE") })
        HealthConnectType.entries.forEach { assertTrue(it.reason.isNotBlank()) }
    }
}
