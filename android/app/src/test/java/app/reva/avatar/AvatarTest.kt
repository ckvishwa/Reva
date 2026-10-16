package app.reva.avatar

import app.reva.mood.ExpressionEvent
import app.reva.voice.Level
import app.reva.voice.TalkUi
import app.reva.voice.VoiceState
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AvatarProtocolTest {
    private val golden: JSONArray =
        JSONObject(File(System.getProperty("reva.avatarFixtures"), "host-messages.json").readText()).getJSONArray("messages")

    private fun built(): List<String?> = listOf(
        AvatarProtocol.state("idle", 0),
        AvatarProtocol.state("listening", 3),
        AvatarProtocol.state("thinking", 3),
        AvatarProtocol.state("speaking", 3),
        AvatarProtocol.state("approval", 4),
        AvatarProtocol.state("error", 5),
        AvatarProtocol.mouth(0, 0.0, 3),
        AvatarProtocol.mouth(120, 0.42314, 3),
        AvatarProtocol.mouth(5000, 7.0, 3), // louder than 1 is clamped, never refused
        AvatarProtocol.expression("relaxed", "mood"),
        AvatarProtocol.expression("neutral", "mood"),
        AvatarProtocol.expression("happy", "verified_outcome", "action-0001-abcd"),
        AvatarProtocol.settings(true, false, "medium"),
        AvatarProtocol.settings(false),
        AvatarProtocol.settings(true, true, "low"),
    )

    /** JSON equality that does not care about key order or whether 1 was written as 1 or 1.0. */
    private fun same(a: JSONObject, b: JSONObject): Boolean {
        val keys = a.keys().asSequence().toSet()
        if (keys != b.keys().asSequence().toSet()) return false
        return keys.all { k ->
            val x = a.get(k)
            val y = b.get(k)
            if (x is Number && y is Number) x.toDouble() == y.toDouble() else x == y
        }
    }

    @Test fun the_builders_produce_exactly_the_messages_the_page_tests_validate() {
        val messages = built()
        assertEquals(golden.length(), messages.size)
        for (i in messages.indices) {
            val want = golden.getJSONObject(i)
            val got = JSONObject(messages[i] ?: error("builder $i refused a valid message"))
            assertTrue("message $i: want $want got $got", same(want, got))
        }
    }

    @Test fun invalid_input_is_refused_rather_than_sent() {
        assertNull(AvatarProtocol.state("dancing", 1))
        assertNull(AvatarProtocol.state("idle", -1))
        assertNull(AvatarProtocol.mouth(-1, 0.5, 1))
        assertNull(AvatarProtocol.mouth(10, Double.NaN, 1))
        assertNull(AvatarProtocol.mouth(10, Double.POSITIVE_INFINITY, 1))
        assertNull(AvatarProtocol.mouth(10, 0.5, -2))
        assertNull(AvatarProtocol.expression("ecstatic", "mood"))
        assertNull(AvatarProtocol.expression("happy", "because"))
        assertNull("a result face needs its action", AvatarProtocol.expression("happy", "verified_outcome"))
        assertNull(AvatarProtocol.expression("happy", "verified_outcome", "short"))
        assertNull(AvatarProtocol.expression("happy", "mood", "x".repeat(65)))
        assertNull(AvatarProtocol.settings(true, quality = "ultra"))
    }
}

class AvatarReportTest {
    @Test fun only_ready_and_error_are_accepted() {
        assertEquals(AvatarReport.Ready, AvatarReport.parse("{\"type\":\"avatar.ready\"}"))
        assertEquals(AvatarReport.Error("load failed"), AvatarReport.parse("{\"type\":\"avatar.error\",\"detail\":\"load failed\"}"))
        assertEquals(AvatarReport.Error(""), AvatarReport.parse("{\"type\":\"avatar.error\"}"))
    }

    @Test fun anything_else_from_the_page_is_ignored() {
        for (raw in listOf(
            null, "", "not json", "[]", "{}", "{\"type\":\"avatar.state\",\"state\":\"idle\",\"turn_epoch\":1}",
            "{\"type\":\"avatar.ready\",\"extra\":1}", "{\"type\":\"avatar.error\",\"url\":\"https://x\"}",
            "{\"type\":\"open\",\"app\":\"notepad\"}", "x".repeat(2000),
        )) assertNull(raw, AvatarReport.parse(raw))
    }

    @Test fun an_error_detail_is_cut_to_the_bound() {
        val report = AvatarReport.parse("{\"type\":\"avatar.error\",\"detail\":\"" + "d".repeat(500) + "\"}") as AvatarReport.Error
        assertEquals(AvatarReport.MAX_DETAIL, report.detail.length)
    }
}

class AvatarDriverTest {
    private val sent = mutableListOf<JSONObject>()
    private val driver = AvatarDriver { sent += JSONObject(it) }

    private fun ui(
        state: VoiceState = VoiceState.Idle,
        micOpen: Boolean = false,
        epoch: Int = 1,
        thinking: Boolean = false,
        failed: Boolean = false,
        expression: ExpressionEvent? = null,
        seq: Int = 0,
    ) = TalkUi(state = state, micOpen = micOpen, epoch = epoch, thinking = thinking, failed = failed, expression = expression, expressionSeq = seq)

    private fun states() = sent.filter { it.getString("type") == "avatar.state" }.map { it.getString("state") }

    @Test fun listening_is_shown_only_while_the_microphone_is_really_open() {
        driver.onUi(ui(VoiceState.AcquiringPermission, micOpen = false, epoch = 2))
        driver.onUi(ui(VoiceState.Listening, micOpen = true, epoch = 2))
        driver.onUi(ui(VoiceState.Reasoning, micOpen = false, epoch = 2))

        assertEquals(listOf("idle", "listening", "thinking"), states())
    }

    @Test fun nothing_is_sent_twice_for_the_same_state_and_epoch() {
        driver.onUi(ui(VoiceState.Listening, micOpen = true, epoch = 2))
        driver.onUi(ui(VoiceState.Listening, micOpen = true, epoch = 2))

        assertEquals(1, sent.size)
    }

    @Test fun a_new_epoch_is_sent_even_when_the_state_is_the_same() {
        driver.onUi(ui(VoiceState.Listening, micOpen = true, epoch = 2))
        driver.onUi(ui(VoiceState.Listening, micOpen = true, epoch = 3))

        assertEquals(listOf(2, 3), sent.map { it.getInt("turn_epoch") })
    }

    @Test fun the_mouth_moves_only_while_speaking_and_only_for_the_current_epoch() {
        driver.onLevel(Level(1, 0.5, 20)) // nothing shown yet
        driver.onUi(ui(VoiceState.Speaking, epoch = 4))
        driver.onLevel(Level(4, 0.5, 20))
        driver.onLevel(Level(3, 0.9, 40)) // an older sentence still playing out
        driver.onUi(ui(VoiceState.Idle, epoch = 5))
        driver.onLevel(Level(5, 0.7, 60)) // after the speech ended

        val mouth = sent.filter { it.getString("type") == "avatar.mouth" }
        assertEquals(1, mouth.size)
        assertEquals(4, mouth.single().getInt("turn_epoch"))
    }

    @Test fun a_failure_shows_the_error_pose_until_the_next_try() {
        driver.onUi(ui(VoiceState.Idle, epoch = 2, failed = true))
        driver.onUi(ui(VoiceState.AcquiringPermission, epoch = 3, failed = false))

        assertEquals(listOf("error", "idle"), states())
    }

    @Test fun an_expression_is_sent_once_and_exactly_as_the_mood_engine_allowed() {
        val face = ExpressionEvent("relaxed", "mood")
        driver.onUi(ui(VoiceState.Speaking, epoch = 4, expression = face, seq = 1))
        driver.onUi(ui(VoiceState.Speaking, epoch = 4, expression = face, seq = 1))
        driver.onUi(ui(VoiceState.Idle, epoch = 5, expression = face, seq = 1))

        val faces = sent.filter { it.getString("type") == "avatar.expression" }
        assertEquals(1, faces.size)
        assertEquals("relaxed", faces.single().getString("name"))
        assertEquals("mood", faces.single().getString("cause"))
    }

    @Test fun a_result_face_without_its_action_is_dropped_not_sent() {
        driver.onUi(ui(VoiceState.Speaking, epoch = 4, expression = ExpressionEvent("happy", "verified_outcome", null), seq = 1))

        assertTrue(sent.none { it.getString("type") == "avatar.expression" })
    }

    @Test fun state_mapping_covers_every_voice_state() {
        for (state in VoiceState.entries) {
            val shown = AvatarDriver.stateFor(ui(state))
            assertTrue("$state -> $shown", shown in AvatarProtocol.states)
        }
        assertEquals("thinking", AvatarDriver.stateFor(ui(thinking = true)))
        assertEquals("approval", AvatarDriver.stateFor(ui(VoiceState.ApprovalPending)))
        assertEquals("idle", AvatarDriver.stateFor(ui(VoiceState.AcquiringPermission)))
    }
}
