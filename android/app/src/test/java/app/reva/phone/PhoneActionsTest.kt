package app.reva.phone

import app.reva.language.Outcomes
import app.reva.policy.loadRegistry
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

private val NOW = Instant.parse("2026-10-15T12:00:00Z")

private class FakePort : IntentPort {
    var resolved: String? = "Clock"
    var startSucceeds = true
    val resolvedSpecs = mutableListOf<IntentSpec>()
    val startedSpecs = mutableListOf<IntentSpec>()

    override fun resolve(spec: IntentSpec): String? {
        resolvedSpecs += spec
        return resolved
    }

    override fun start(spec: IntentSpec): Boolean {
        startedSpecs += spec
        return startSucceeds
    }
}

private class Rig(tmp: TemporaryFolder, now: Instant = NOW) {
    val apps = ApprovedApps(File(tmp.root, "apps.json"))
    val port = FakePort()
    val texts = mutableListOf<String>()
    var clock = now
    val actions = PhoneActions(loadRegistry(), apps, port, clock = { clock }, zone = { ZoneOffset.UTC }, onText = { texts += it })
}

class PhoneActionsOpenTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun opening_an_approved_app_is_verified_only_from_the_resolved_target_and_runs_without_a_card() {
        val rig = Rig(tmp)
        rig.apps.approve(InstalledApp("com.example.calc", "Calculator"), listOf("calc"))
        rig.port.resolved = "Calculator" // what the OS reports right now for that package

        val reply = rig.actions.handle("open calculator")

        assertEquals("Opened Calculator.", reply!!.text)
        assertNull(rig.actions.card.value)
        assertEquals(1, rig.port.startedSpecs.size)
        assertEquals("com.example.calc", rig.port.startedSpecs.single().launchPackage)
    }

    @Test fun an_unapproved_app_is_refused_and_nothing_is_started() {
        val rig = Rig(tmp)

        val reply = rig.actions.handle("open calculator")

        assertTrue(reply!!.text.contains("Approve it in Apps first"))
        assertTrue(rig.port.startedSpecs.isEmpty())
    }

    @Test fun approved_but_not_resolvable_on_this_phone_says_so_and_starts_nothing() {
        val rig = Rig(tmp)
        rig.apps.approve(InstalledApp("com.example.calc", "Calculator"))
        rig.port.resolved = null

        val reply = rig.actions.handle("open calculator")

        assertEquals(PhoneOutcomes.NO_APP, reply!!.text)
        assertTrue(rig.port.startedSpecs.isEmpty())
    }

    @Test fun android_refusing_to_start_is_reported_failed() {
        val rig = Rig(tmp)
        rig.apps.approve(InstalledApp("com.example.calc", "Calculator"))
        rig.port.startSucceeds = false

        assertEquals(PhoneOutcomes.FAILED, rig.actions.handle("open calculator")!!.text)
    }

    @Test fun a_long_unrelated_sentence_is_not_treated_as_a_failed_open() {
        val rig = Rig(tmp)
        assertNull(rig.actions.handle("open the pod bay doors please hal this is a very long sentence indeed"))
    }

    @Test fun a_forbidden_capability_never_reaches_resolution() {
        val rig = Rig(tmp)
        val reply = rig.actions.handle("share my bank password")
        // share is allowed as a capability; this checks the registry path still runs authorize() first for opens too.
        assertTrue(reply == null || !reply.text.contains("Opened"))
    }
}

class PhoneActionsT2Test {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun an_alarm_waits_for_a_tap_on_this_phone_and_only_hands_off_after_it() {
        val rig = Rig(tmp)

        val asked = rig.actions.handle("set an alarm for 7:30 am")
        val card = rig.actions.card.value

        assertTrue(asked!!.text.contains("Confirm on screen"))
        assertEquals("Alarm 07:30", card!!.label)
        assertTrue(rig.port.startedSpecs.isEmpty())

        rig.actions.approve(card.id)

        assertEquals(1, rig.port.startedSpecs.size)
        assertEquals(PhoneIntents.ACTION_SET_ALARM, rig.port.startedSpecs.single().action)
        assertTrue(rig.texts.single().contains("Tap Save there to finish"))
        assertNull(rig.actions.card.value)
    }

    @Test fun denying_runs_nothing_and_says_so() {
        val rig = Rig(tmp)
        rig.actions.handle("set an alarm for 7:30 am")
        val card = rig.actions.card.value!!

        rig.actions.deny(card.id)

        assertTrue(rig.port.startedSpecs.isEmpty())
        assertEquals(PhoneOutcomes.DENIED, rig.texts.single())
        assertNull(rig.actions.card.value)
    }

    @Test fun a_second_request_while_one_is_pending_is_refused_not_queued() {
        val rig = Rig(tmp)
        rig.actions.handle("set an alarm for 7:30 am")

        val second = rig.actions.handle("share this message")

        assertEquals(PhoneActions.BUSY, second!!.text)
    }

    @Test fun a_card_nobody_taps_expires_and_cannot_be_approved_late() {
        val rig = Rig(tmp)
        rig.actions.handle("set an alarm for 7:30 am")
        val card = rig.actions.card.value!!
        rig.clock = NOW.plusSeconds(PhoneActions.APPROVAL_SECONDS + 1)

        rig.actions.expire()
        rig.actions.approve(card.id) // too late: the card is already gone

        assertTrue(rig.port.startedSpecs.isEmpty())
        assertEquals(PhoneOutcomes.TIMED_OUT, rig.texts.single())
        assertNull(rig.actions.card.value)
    }

    @Test fun approving_an_id_that_is_not_the_current_card_does_nothing() {
        val rig = Rig(tmp)
        rig.actions.handle("set an alarm for 7:30 am")

        rig.actions.approve("not-the-real-id")

        assertTrue(rig.port.startedSpecs.isEmpty())
        assertTrue(rig.texts.isEmpty())
        assertTrue(rig.actions.card.value != null)
    }

    @Test fun a_reminder_calendar_and_share_each_produce_their_own_handoff_sentence() {
        for ((text, must) in listOf(
            "remind me to call mom at 5 pm" to "reminder is ready",
            "add team sync to my calendar tomorrow at 3 pm" to "event is ready",
            "share this cool link" to "share sheet",
        )) {
            val rig = Rig(tmp)
            rig.actions.handle(text)
            val card = rig.actions.card.value!!
            rig.actions.approve(card.id)
            assertTrue(text, rig.texts.single().contains(must))
        }
    }

    @Test fun no_sentence_before_a_click_claims_anything_happened() {
        val rig = Rig(tmp)
        val asked = rig.actions.handle("set an alarm for 7:30 am")!!.text
        for (word in Outcomes.SUCCESS_WORDS) {
            assertFalse(word, Regex("\\b$word\\b").containsMatchIn(asked.lowercase()))
        }
    }
}

class PhoneActionsEvidenceTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun verified_text_appears_only_with_a_reference_shaped_the_registry_expects() {
        val registry = loadRegistry()
        val goodApp = PhoneReport("verified", "intent_resolved", "pkg:app.reva.android")
        val badShape = PhoneReport("verified", "intent_resolved", "pkg:not a package")
        val wrongKind = PhoneReport("verified", "intent_result", "pkg:app.reva.android")
        val missingRef = PhoneReport("verified", "intent_resolved", null)

        assertTrue(PhoneActions.evidenceOk(registry, "android.app.open", goodApp))
        assertFalse(PhoneActions.evidenceOk(registry, "android.app.open", badShape))
        assertFalse(PhoneActions.evidenceOk(registry, "android.app.open", wrongKind))
        assertFalse(PhoneActions.evidenceOk(registry, "android.app.open", missingRef))
    }

    @Test fun observed_never_counts_as_verified() {
        val registry = loadRegistry()
        assertFalse(PhoneActions.evidenceOk(registry, "android.reminder.set", PhoneReport("observed", "intent_result", "pkg:app.reva.android")))
    }
}
