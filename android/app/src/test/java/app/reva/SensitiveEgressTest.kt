package app.reva

import app.reva.brain.BrainResult
import app.reva.brain.KernelQueries
import app.reva.brain.LocalBrain
import app.reva.brain.PlannerClient
import app.reva.brain.PlannerRegistry
import app.reva.data.HealthDaily
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import app.reva.language.HealthSafety
import app.reva.language.PolicyReplies
import app.reva.policy.loadRegistry
import app.reva.testing.FakeFinanceRepository
import java.io.File
import java.time.LocalDate
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Finance and Health are sensitive domains: their facts are answered from the local Kernel, safety phrases get a
 * fixed reply, and none of it reaches a planner, the PC request channel or the network. A registered "hosted"
 * planner records every sentence it is given so a leak would show up here.
 */
class SensitiveEgressTest {
    private val health = object : HealthRepository {
        override suspend fun daily(date: String) = Outcome.Ok(HealthDaily(date, 0, 0, 0, null, 0, 0, 0))
        override suspend fun weekly(endDate: String) = Outcome.Ok(HealthWeekly("2026-10-12", endDate, 30, 1, 900, 2, 3, 7, 5, 4))
        override suspend fun records(date: String) = Outcome.Ok(emptyList<HealthRecord>())
        override suspend fun schedules(date: String) = Outcome.Ok(emptyList<MedicationSchedule>())
        override suspend fun command(kind: String, payload: JSONObject) = Outcome.Ok(Unit)
    }

    private fun replies(sent: MutableList<String>) = PolicyReplies(
        loadRegistry(),
        local = KernelQueries(FakeFinanceRepository(), health, today = { LocalDate.parse("2026-10-18") }),
        fallback = LocalBrain(PlannerRegistry(mapOf("offline-lite" to PlannerClient { text ->
            sent += text
            BrainResult.Answer("invented", "hosted")
        }))),
    )

    @Test fun health_and_finance_questions_and_safety_phrases_never_reach_a_planner() = runBlocking {
        val sent = mutableListOf<String>()
        val replies = replies(sent)
        val sensitive = listOf(
            "how did I sleep this week",
            "show my health this week",
            "how much did I spend this month",
            "what did I spend last month",
            "I have chest pain",
            "I think I overdosed",
            "how many mg of ibuprofen should I take",
            "what dose of melatonin is right for me",
            "can you diagnose my headache",
            "pay my rent",
            "transfer 200 dollars to savings",
            "log into my bank",
        )
        for (sentence in sensitive) {
            val reply = replies.reply(sentence)
            assertFalse("$sentence must not be answered by a planner", reply.source == "hosted")
            assertFalse("$sentence produced planner text", reply.text.contains("invented"))
        }
        assertEquals("no sensitive sentence reached the planner", emptyList<String>(), sent)
    }

    @Test fun dosing_and_diagnosis_requests_are_refused_and_urgent_ones_get_the_fixed_safety_reply() = runBlocking {
        val replies = replies(mutableListOf())
        val urgent = replies.reply("I have chest pain and trouble breathing")
        assertEquals(HealthSafety.URGENT_MESSAGE, urgent.text)
        for (sentence in listOf("how many mg of ibuprofen should I take", "what dosage should I use", "diagnose this rash")) {
            val reply = replies.reply(sentence).text
            assertFalse("$sentence: no number may be suggested", Regex("\\d").containsMatchIn(reply))
            assertFalse(reply.contains("invented"))
        }
    }

    private fun source(path: String): File {
        val main = File(System.getProperty("reva.sourceManifest")).parentFile
        return File(main, "java/app/reva/$path")
    }

    @Test fun health_and_finance_data_code_has_no_network_or_pc_channel() {
        val files = listOf(
            "data/HealthRepository.kt", "data/FinanceReports.kt", "data/KernelFinanceRepository.kt",
            "ui/health/HealthScreen.kt", "healthconnect/HealthConnect.kt", "healthconnect/AndroidHealthConnectGateway.kt",
            "healthconnect/HealthPermissionsRationaleActivity.kt", "brain/KernelQueries.kt",
        ).map(::source)
        val forbidden = listOf("java.net.", "javax.net.", "okhttp", "HttpURLConnection", "Socket(", "app.reva.sync.", "app.reva.pcrequests.", "WebView")
        for (file in files) {
            assertTrue("missing ${file.path}", file.exists())
            val text = file.readText()
            for (token in forbidden) assertFalse("${file.name} uses $token", text.contains(token))
        }
    }

    @Test fun only_finance_is_synced_to_the_pc_and_health_lives_in_no_backup_storage() {
        val engine = source("sync/SyncEngine.kt").readText()
        assertTrue(engine.contains("const val DOMAIN = \"finance\""))
        assertFalse("Health must never be in a sync scope", engine.contains("\"health\""))
        val app = source("RevaApp.kt").readText()
        assertTrue(app.contains("val domainRoot: File get() = File(context.noBackupFilesDir, \"domains\")"))
        assertTrue(app.contains("File(domainRoot, \"health\")"))
    }
}
