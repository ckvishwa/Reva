package app.reva.voice

import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceSessionTest {
    private fun fixture(): JSONObject =
        JSONObject(File(System.getProperty("reva.fixtures"), "session-transitions.json").readText())

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    @Test fun the_state_names_and_transition_table_equal_the_cores_fixture() {
        val f = fixture()
        assertEquals(f.getJSONArray("states").strings(), VoiceState.entries.map { it.wire })
        val forward = f.getJSONObject("forward")
        for (state in VoiceState.entries) {
            assertEquals(
                "moves out of ${state.wire}",
                forward.getJSONArray(state.wire).strings().sorted(),
                VoiceTransitions.forward.getValue(state).map { it.wire }.sorted(),
            )
        }
        assertEquals(
            f.getJSONArray("interruptible").strings().sorted(),
            VoiceTransitions.interruptible.map { it.wire }.sorted(),
        )
    }

    @Test fun every_pair_of_states_agrees_with_the_core_rule() {
        val f = fixture()
        val forward = f.getJSONObject("forward")
        val anyLive = f.getJSONArray("any_live_may_go").strings().toSet()
        val notLive = f.getJSONArray("not_live").strings().toSet()
        for (from in VoiceState.entries) for (to in VoiceState.entries) {
            val expected = to.wire in forward.getJSONArray(from.wire).strings() ||
                (from.wire !in notLive && to.wire in anyLive)
            assertEquals("${from.wire} -> ${to.wire}", expected, VoiceTransitions.canGo(from, to))
        }
    }

    @Test fun an_illegal_move_is_refused_and_changes_nothing() {
        val session = VoiceSession()
        assertFalse(session.go(VoiceState.Speaking))
        assertEquals(VoiceState.Idle, session.state)
    }

    @Test fun the_normal_turn_walks_the_whole_path() {
        val session = VoiceSession()
        session.beginTurn()
        for (next in listOf(
            VoiceState.AcquiringPermission, VoiceState.Listening, VoiceState.Endpointing,
            VoiceState.Transcribing, VoiceState.Reasoning, VoiceState.Speaking, VoiceState.Idle,
        )) assertTrue(next.wire, session.go(next))
    }

    @Test fun interrupt_bumps_the_epoch_so_the_old_turn_is_stale() {
        val session = VoiceSession()
        val first = session.beginTurn()
        session.go(VoiceState.AcquiringPermission); session.go(VoiceState.Listening)
        session.go(VoiceState.Endpointing); session.go(VoiceState.Transcribing); session.go(VoiceState.Reasoning)
        session.go(VoiceState.Speaking)

        val second = session.interrupt()

        assertEquals(first + 1, second)
        assertEquals(VoiceState.Listening, session.state)
        assertFalse(session.isCurrent(first))
        assertTrue(session.isCurrent(second!!))
    }

    @Test fun interrupt_does_nothing_when_nothing_is_running() {
        val session = VoiceSession()
        assertNull(session.interrupt())
        session.beginTurn(); session.go(VoiceState.AcquiringPermission); session.go(VoiceState.Listening)
        assertNull("listening is not interruptible; there is nothing to cancel", session.interrupt())
        assertEquals(VoiceState.Listening, session.state)
    }

    @Test fun cancel_ends_every_live_state_in_idle_with_a_new_epoch() {
        for (stop in listOf(VoiceState.AcquiringPermission, VoiceState.Listening, VoiceState.Speaking)) {
            val session = VoiceSession()
            val epoch = session.beginTurn()
            session.go(VoiceState.AcquiringPermission)
            if (stop != VoiceState.AcquiringPermission) {
                session.go(VoiceState.Listening); session.go(VoiceState.Endpointing)
                session.go(VoiceState.Transcribing); session.go(VoiceState.Reasoning)
                if (stop == VoiceState.Speaking) session.go(VoiceState.Speaking)
            }
            session.cancel()
            assertEquals(VoiceState.Idle, session.state)
            assertFalse(session.isCurrent(epoch))
        }
    }
}
