package app.reva

import android.content.Context
import android.net.Uri
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.performScrollToNode
import androidx.core.app.ActivityOptionsCompat
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.data.GymRepository
import app.reva.data.GymSetInput
import app.reva.data.HealthDaily
import app.reva.data.HealthImportReport
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.KernelGymRepository
import app.reva.data.KernelHealthRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import app.reva.ui.gym.GymHost
import app.reva.ui.health.HealthScreen
import app.reva.ui.theme.RevaTheme
import java.io.File
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.openDomain

/**
 * GYM-02.1: the Health backup card as a user meets it - the system document picker, the dry-run
 * preview, the confirmation, and the result line - over a REAL encrypted Kernel (libreva_kernel.so,
 * SQLCipher, Android Keystore). The picker is replaced by an activity-result registry that hands back
 * a chosen content:// URI, exactly the contract the system picker fulfils; the end-to-end script
 * (tools/android/gym_backup_e2e.py) drives the real system picker itself.
 */
@RunWith(AndroidJUnit4::class)
class HealthBackupRestoreUiTest {
    @get:Rule val rule = createComposeRule()

    private val context: Context = ApplicationProvider.getApplicationContext()
    private val roots = mutableListOf<File>()

    @After fun tearDown() {
        roots.forEach { it.deleteRecursively() }
    }

    /** One phone: its own Keystore-wrapped key and its own encrypted Health file. */
    private class Device(val handle: DomainHandle, val health: HealthRepository, val gym: GymRepository)

    private fun newDevice(): Device {
        val root = File(context.noBackupFilesDir, "backup-ui-${System.nanoTime()}").also {
            it.mkdirs()
            roots += it
        }
        val keys = KeystoreKeyProvider(File(root, "keys"))
        val domains = File(root, "domains/health").also { it.mkdirs() }
        val open = { openDomain("health", keys, domains.absolutePath) }
        return Device(open(), KernelHealthRepository(openHandle = open), KernelGymRepository(openHandle = open))
    }

    private fun <T> ok(outcome: Outcome<T>): T = when (outcome) {
        is Outcome.Ok -> outcome.value
        is Outcome.Failed -> throw AssertionError(outcome.error.message)
    }

    /** The system picker's contract: whatever the user chose comes back as a Uri, or null if they backed out. */
    private class FakePicker : ActivityResultRegistryOwner {
        var next: Uri? = null
        var launches = 0
        override val activityResultRegistry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(
                requestCode: Int,
                contract: ActivityResultContract<I, O>,
                input: I,
                options: ActivityOptionsCompat?,
            ) {
                launches++
                @Suppress("UNCHECKED_CAST")
                dispatchResult(requestCode, next as O)
            }
        }
    }

    /** A real content:// URI for [bytes], served by the app's own FileProvider. */
    private fun documentWith(name: String, bytes: ByteArray): Uri {
        val dir = File(context.cacheDir, "exports").also { it.mkdirs() }
        val file = File(dir, name).also { it.writeBytes(bytes) }
        return FileProvider.getUriForFile(context, "${context.packageName}.exports", file)
    }

    /** Day 2 Pull A at 55 lb for 10, 9 and 8, finished; and a second workout that was deleted. */
    private fun seedPullA(device: Device): String = runBlocking {
        val program = ok(device.gym.createDefaultProgram("2026-10-22"))
        val session = ok(device.gym.startWorkout(program.id, "day-2"))
        for (reps in listOf(10, 9, 8)) {
            ok(device.gym.addSet(session, GymSetInput(exerciseKey = "lat_pulldown", loadMilli = 55_000, reps = reps)))
        }
        ok(device.gym.pause(session))
        ok(device.gym.resume(session))
        ok(device.gym.note(session, "Right elbow tight", "Felt strong"))
        ok(device.gym.complete(session))
        val deleted = ok(device.gym.startWorkout(program.id, "day-3"))
        ok(device.gym.addSet(deleted, GymSetInput(exerciseKey = "smith_squat", loadMilli = 135_000, reps = 8)))
        ok(device.gym.complete(deleted))
        ok(device.gym.delete(deleted))
        session
    }

    private fun clickRestore() {
        rule.onNodeWithTag("health_screen").performScrollToNode(hasTestTag("health_restore"))
        rule.onNodeWithTag("health_restore").performClick()
        rule.waitForIdle()
    }

    private fun textOf(tag: String): String {
        rule.onNodeWithTag("health_screen").performScrollToNode(hasTestTag(tag))
        val node = rule.onNodeWithTag(tag).fetchSemanticsNode()
        return node.config.getOrNull(SemanticsProperties.Text)?.joinToString("") { it.text } ?: ""
    }

    private fun noNode(tag: String): Boolean = rule.onAllNodes(hasTestTag(tag)).fetchSemanticsNodes().isEmpty()

    @Test fun a_restore_through_the_picker_commits_then_reports_and_a_repeat_is_all_duplicates() {
        val source = newDevice()
        val session = seedPullA(source)
        val before = ok(runBlocking { source.gym.sessionDetails(session) })
        val file = documentWith("pull-a.json", source.handle.export("json"))
        assertTrue(JSONObject(String(source.handle.export("json"))).getString("format") == "reva-health-v2")

        val target = newDevice()
        val picker = FakePicker().apply { next = file }
        rule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides picker) {
                RevaTheme { HealthScreen(target.health) }
            }
        }

        // Picker -> dry run: the preview counts records and deletions apart and commits nothing.
        clickRestore()
        rule.waitUntil(15_000) { !noNode("health_restore_preview") }
        assertEquals(
            "This file has 5 new records and 2 deletions, 0 already here and 0 that cannot be restored.",
            textOf("health_restore_preview"),
        )
        assertEquals("a dry run commits nothing", 0L, target.handle.eventCount())
        assertTrue("no success line before the commit", noNode("health_backup_result"))
        // The preview grows the last card downward. The confirm button must already be on screen, without
        // the user having to hunt for it below the fold.
        rule.onNodeWithTag("health_restore_confirm").assertIsDisplayed()

        // Confirm -> the Kernel commits -> only then the result line.
        rule.onNodeWithTag("health_restore_confirm").performClick()
        rule.waitUntil(15_000) { !noNode("health_backup_result") }
        rule.onNodeWithTag("health_backup_result").assertIsDisplayed()
        assertEquals("Restored 5 records and 2 deletions; 0 were already here; 0 skipped.", textOf("health_backup_result"))
        assertTrue("the Kernel holds what the line says", target.handle.eventCount() > 0)

        // The restored session reads back exactly, through the Kernel and then through the Gym UI.
        val after = ok(runBlocking { target.gym.sessionDetails(session) })
        assertEquals(before.session.startedAt, after.session.startedAt)
        assertEquals(before.session.endedAt, after.session.endedAt)
        assertEquals(before.session.planVersion, after.session.planVersion)
        assertEquals("Right elbow tight", after.session.notes)
        assertEquals("Felt strong", after.session.effortNote)
        assertEquals(before.metrics.activeSeconds, after.metrics.activeSeconds)
        assertEquals(before.metrics.pausedSeconds, after.metrics.pausedSeconds)
        val sets = after.blockFor("lat_pulldown")!!.sets
        assertEquals(listOf(10, 9, 8), sets.map { it.reps })
        assertEquals(listOf(55_000L, 55_000L, 55_000L), sets.map { it.loadMilli })
        assertEquals(1_485_000L, after.metrics.volumeByUnit.first().volumeMilli)
        assertEquals(source.handle.projectionDigest(), target.handle.projectionDigest())

        // Repeat the same restore: zero new, everything already here, and nothing can be confirmed.
        val digest = target.handle.projectionDigest()
        val events = target.handle.eventCount()
        clickRestore()
        rule.waitUntil(15_000) { !noNode("health_restore_preview") }
        assertEquals(
            "This file has 0 new records, 7 already here and 0 that cannot be restored.",
            textOf("health_restore_preview"),
        )
        assertTrue("choosing a new file clears the last result, so an old success never sits beside a new preview", noNode("health_backup_result"))
        rule.onNodeWithTag("health_restore_confirm").assertIsNotEnabled()
        assertEquals(digest, target.handle.projectionDigest())
        assertEquals(events, target.handle.eventCount())
        assertEquals("one workout, not two", 1, ok(runBlocking { target.gym.recentSessions(20) }).size)
    }

    @Test fun the_restored_workout_opens_in_the_real_gym_screens_with_the_three_sets() {
        val source = newDevice()
        val session = seedPullA(source)
        val target = newDevice()
        runBlocking { target.health.importData("json", source.handle.export("json"), dryRun = false) }

        rule.setContent { RevaTheme { GymHost(target.gym) } }
        rule.waitUntil(20_000) { rule.onAllNodes(hasTestTag("gym_plan")).fetchSemanticsNodes().isNotEmpty() }
        // Recent workouts sits below the plan's exercise rows, so it is composed only once scrolled to.
        rule.waitUntil(20_000) {
            runCatching { rule.onNodeWithTag("gym_plan").performScrollToNode(hasTestTag("gym_recent_$session")) }.isSuccess
        }
        rule.onNodeWithTag("gym_recent_$session").performClick()
        rule.waitUntil(20_000) { rule.onAllNodes(hasTestTag("gym_details")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("gym_details").performScrollToNode(hasTestTag("gym_block_lat_pulldown"))
        rule.onNodeWithTag("gym_block_lat_pulldown").assertIsDisplayed()
        for (line in listOf("55 lb x 10", "55 lb x 9", "55 lb x 8")) {
            assertEquals(line, 1, rule.onAllNodes(hasText(line)).fetchSemanticsNodes().size)
        }
        rule.onNodeWithTag("gym_details").performScrollToNode(hasTestTag("gym_volume"))
        assertEquals("1485 lb", 1, rule.onAllNodes(hasText("1485 lb")).fetchSemanticsNodes().size)
        assertTrue("plan v1", rule.onAllNodes(hasText("Workout receipt · plan v1")).fetchSemanticsNodes().isNotEmpty())
    }

    @Test fun cancelling_the_picker_changes_nothing() {
        val device = newDevice()
        seedPullA(device)
        val digest = device.handle.projectionDigest()
        val events = device.handle.eventCount()
        val picker = FakePicker().apply { next = null }
        rule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides picker) { RevaTheme { HealthScreen(device.health) } }
        }
        clickRestore()
        assertEquals("the picker opened", 1, picker.launches)
        assertTrue("no preview", noNode("health_restore_preview"))
        assertTrue("no message", noNode("health_backup_result"))
        assertEquals(digest, device.handle.projectionDigest())
        assertEquals(events, device.handle.eventCount())
    }

    @Test fun a_file_that_is_not_a_backup_is_refused_with_a_reason_and_data_is_untouched() {
        val device = newDevice()
        seedPullA(device)
        val digest = device.handle.projectionDigest()
        val events = device.handle.eventCount()
        val picker = FakePicker()
        rule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides picker) { RevaTheme { HealthScreen(device.health) } }
        }
        val cases = listOf(
            "bad.json" to ("{not json".toByteArray() to "not valid JSON"),
            "wrong.json" to ("""{"format":"other","records":[]}""".toByteArray() to "not a REVA Health backup"),
            "array.json" to ("[]".toByteArray() to "must be a JSON object"),
            "empty.json" to (ByteArray(0) to "not valid JSON"),
            "gym.json" to ("""{"format":"reva-health-v2","records":[],"gym":{"sets":7}}""".toByteArray() to "must be a list"),
        )
        for ((name, spec) in cases) {
            val (bytes, reason) = spec
            picker.next = documentWith(name, bytes)
            clickRestore()
            rule.waitUntil(15_000) { !noNode("health_backup_result") }
            val message = textOf("health_backup_result")
            assertTrue("$name: \"$message\" should mention \"$reason\"", message.contains(reason))
            assertTrue("$name: nothing to confirm", noNode("health_restore_confirm"))
            assertEquals("$name: events", events, device.handle.eventCount())
            assertEquals("$name: digest", digest, device.handle.projectionDigest())
        }
    }

    @Test fun a_document_the_app_may_not_read_cannot_be_restored_and_data_is_untouched() {
        val device = newDevice()
        seedPullA(device)
        val digest = device.handle.projectionDigest()
        val picker = FakePicker()
        rule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides picker) { RevaTheme { HealthScreen(device.health) } }
        }
        val unreadable = listOf(
            // A real document in shared storage that this app was never granted.
            Uri.parse("content://com.android.externalstorage.documents/document/primary%3ADownload%2Fnope.json"),
            // Another app's provider, no grant.
            Uri.parse("content://com.android.providers.downloads.documents/document/1"),
            // Our own provider, a file that is not there.
            FileProvider.getUriForFile(context, "${context.packageName}.exports", File(File(context.cacheDir, "exports").also { it.mkdirs() }, "gone.json")),
        )
        for (uri in unreadable) {
            picker.next = uri
            clickRestore()
            rule.waitUntil(15_000) { !noNode("health_backup_result") }
            assertEquals("$uri", "That file could not be read.", textOf("health_backup_result"))
            assertTrue("$uri: nothing to confirm", noNode("health_restore_confirm"))
            assertEquals("$uri", digest, device.handle.projectionDigest())
        }
    }

    /** A Health repository whose real restore waits until the test lets the Kernel "commit". */
    private class GatedHealth : HealthRepository {
        val commit = CompletableDeferred<Outcome<HealthImportReport>>()
        var dryRuns = 0
        var restores = 0
        override suspend fun daily(date: String) = Outcome.Ok(HealthDaily(date, 0, 0, 0, null, 0, 0, 0, 0, 0))
        override suspend fun weekly(endDate: String) = Outcome.Ok(HealthWeekly("2026-10-10", endDate, 0, 0, 0, 0, 0, 0, 0, 0))
        override suspend fun records(date: String) = Outcome.Ok(emptyList<HealthRecord>())
        override suspend fun schedules(date: String) = Outcome.Ok(emptyList<MedicationSchedule>())
        override suspend fun command(kind: String, payload: JSONObject): Outcome<Unit> = Outcome.Ok(Unit)
        override suspend fun importData(format: String, bytes: ByteArray, dryRun: Boolean): Outcome<HealthImportReport> =
            if (dryRun) {
                dryRuns++
                Outcome.Ok(HealthImportReport(added = 3, updated = 0, duplicates = 0, rejected = emptyList(), dryRun = true, deletions = 1))
            } else {
                restores++
                commit.await()
            }
    }

    private fun gatedRestore(): Pair<GatedHealth, FakePicker> {
        val repo = GatedHealth()
        val picker = FakePicker().apply { next = documentWith("any.json", """{"format":"reva-health-v2","records":[]}""".toByteArray()) }
        rule.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides picker) { RevaTheme { HealthScreen(repo) } }
        }
        clickRestore()
        rule.waitUntil(15_000) { !noNode("health_restore_preview") }
        rule.onNodeWithTag("health_restore_confirm").assertIsEnabled()
        return repo to picker
    }

    @Test fun success_is_reported_only_after_the_kernel_has_committed() {
        val (repo, _) = gatedRestore()
        rule.onNodeWithTag("health_restore_confirm").assertIsDisplayed()
        rule.onNodeWithTag("health_restore_confirm").performClick()
        rule.waitUntil(15_000) { repo.restores == 1 }
        rule.waitForIdle()
        // The restore is in flight and uncommitted: the screen must not say it worked.
        assertTrue("no result line while the Kernel is still committing", noNode("health_backup_result"))
        assertEquals(1, repo.restores)
        // And a second tap must not start a second restore whose result would overwrite the first one's.
        rule.onNodeWithTag("health_restore_confirm").assertIsNotEnabled()
        rule.onNodeWithTag("health_restore_confirm").performClick()
        rule.waitForIdle()
        assertEquals("a second tap while committing starts nothing", 1, repo.restores)

        repo.commit.complete(Outcome.Ok(HealthImportReport(3, 0, 0, emptyList(), false, 1)))
        rule.waitUntil(15_000) { !noNode("health_backup_result") }
        rule.onNodeWithTag("health_backup_result").assertIsDisplayed()
        assertEquals("Restored 3 records and 1 deletion; 0 were already here; 0 skipped.", textOf("health_backup_result"))
    }

    @Test fun a_refused_restore_never_says_restored() {
        val (repo, _) = gatedRestore()
        rule.onNodeWithTag("health_restore_confirm").performClick()
        rule.waitUntil(15_000) { repo.restores == 1 }
        repo.commit.complete(Outcome.Failed(FinanceError(ErrorKind.Validation, "records: too many records")))
        rule.waitUntil(15_000) { !noNode("health_backup_result") }
        val message = textOf("health_backup_result")
        assertEquals("records: too many records", message)
        assertTrue(!message.contains("Restored"))
        assertNotNull(repo)
    }
}
