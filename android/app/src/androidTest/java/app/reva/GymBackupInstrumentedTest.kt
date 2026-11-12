package app.reva

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import app.reva.data.GymRepository
import app.reva.data.KernelGymRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.data.Outcome
import app.reva.data.GymSetInput
import java.io.File
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.openDomain

/**
 * GYM-02 on the device: a finished workout written through the real Kernel is exported, restored
 * into a second encrypted store with its own key and data file, and imported again. Nothing here
 * is mocked, so the round trip is proved on the ABI the APK ships.
 */
@RunWith(AndroidJUnit4::class)
class GymBackupInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val roots = mutableListOf<File>()

    @After fun tearDown() {
        roots.forEach { it.deleteRecursively() }
    }

    private class Store(val handle: DomainHandle, val gym: GymRepository)

    /** A fresh install: a new key root and a new encrypted Health file. */
    private fun newStore(): Store {
        val root = File(context.noBackupFilesDir, "gym-backup-${System.nanoTime()}").also {
            it.mkdirs()
            roots += it
        }
        val keys = KeystoreKeyProvider(File(root, "keys"))
        val domains = File(root, "domains/health").also { it.mkdirs() }
        val open = { openDomain("health", keys, domains.absolutePath) }
        return Store(open(), KernelGymRepository(openHandle = open))
    }

    private fun <T> ok(outcome: Outcome<T>): T = when (outcome) {
        is Outcome.Ok -> outcome.value
        is Outcome.Failed -> throw AssertionError(outcome.error.message)
    }

    @Test fun a_finished_workout_survives_a_backup_a_restore_and_a_repeated_import() = runBlocking {
        val source = newStore()
        val program = ok(source.gym.createDefaultProgram("2026-10-22"))
        assertEquals(90, program.days.sumOf { it.plannedWorkingSets })
        val session = ok(source.gym.startWorkout(program.id, "day-2"))
        // Day 2 Pull A: 55 lb for 10, 9 and 8.
        for (reps in listOf(10, 9, 8)) {
            ok(
                source.gym.addSet(
                    session,
                    GymSetInput(exerciseKey = "lat_pulldown", loadMilli = 55_000, weightUnit = "lb", reps = reps),
                ),
            )
        }
        ok(source.gym.pause(session))
        ok(source.gym.resume(session))
        ok(source.gym.note(session, "Right elbow tight", null))
        ok(source.gym.complete(session))
        val before = ok(source.gym.sessionDetails(session))
        assertEquals(3, before.metrics.workingSetsCompleted)
        assertEquals(1_485_000L, before.metrics.volumeByUnit.first().volumeMilli)

        // The backup the Health screen shares, written by the Kernel on this device.
        val file = source.handle.export("json")
        val parsed = JSONObject(String(file, Charsets.UTF_8))
        assertEquals("reva-health-v2", parsed.getString("format"))
        val gym = parsed.getJSONObject("gym")
        assertEquals(1, gym.getJSONArray("programs").length())
        assertEquals(1, gym.getJSONArray("sessions").length())
        assertEquals(3, gym.getJSONArray("sets").length())

        // A second install restores it.
        val restored = newStore()
        assertNull(ok(restored.gym.activeProgram()))
        val report = restored.handle.importData("json", file, "{}")
        assertEquals(0, report.rejected.size)
        assertEquals("1 program + 1 session + 3 sets", 5L, report.accepted.toLong())

        val after = ok(restored.gym.sessionDetails(session))
        assertEquals(before.session.startedAt, after.session.startedAt)
        assertEquals(before.session.endedAt, after.session.endedAt)
        assertEquals(before.session.date, after.session.date)
        assertEquals("Right elbow tight", after.session.notes)
        assertEquals(before.metrics.activeSeconds, after.metrics.activeSeconds)
        assertEquals(before.metrics.pausedSeconds, after.metrics.pausedSeconds)
        assertEquals(before.metrics.workingSetsCompleted, after.metrics.workingSetsCompleted)
        assertEquals(1_485_000L, after.metrics.volumeByUnit.first().volumeMilli)
        val sets = after.blockFor("lat_pulldown")!!.sets
        assertEquals(listOf(10, 9, 8), sets.map { it.reps })
        assertEquals(listOf(55_000L, 55_000L, 55_000L), sets.map { it.loadMilli })
        assertEquals(before.exercises.first().sets.map { it.completedAt }, sets.map { it.completedAt })
        assertEquals(source.handle.projectionDigest(), restored.handle.projectionDigest())

        // Importing the same file again adds nothing.
        val again = restored.handle.importData("json", file, "{}")
        assertEquals(0L, again.accepted.toLong())
        assertEquals(5L, again.duplicates.toLong())
        assertEquals(1, ok(restored.gym.recentSessions(20)).size)
        assertNotNull(ok(restored.gym.activeProgram()))
        assertEquals(source.handle.projectionDigest(), restored.handle.projectionDigest())

        // And the restored device still refuses a second default program.
        assertTrue(restored.gym.createDefaultProgram(null) is Outcome.Failed)
    }
}
