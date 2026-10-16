package app.reva.voice

import app.reva.mood.ExpressionEvent
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakePermissions(var state: MicPermission) : PermissionGate {
    override fun current() = state
}

private class FakeRecognizer(val onRelease: () -> Unit) : Recognizer {
    var listener: RecognizerListener? = null
    var stopped = 0
    var released = 0
    override fun start(listener: RecognizerListener) { this.listener = listener }
    override fun stop() { stopped++ }
    override fun release() { released++; onRelease() }
}

private class FakeService(var allow: Boolean = true) : ServiceLauncher {
    var starts = 0
    var stops = 0
    override fun start(): Boolean { if (allow) starts++; return allow }
    override fun stop() { stops++ }
}

private class FakeReplies : ReplySource {
    var gate: CompletableDeferred<Unit>? = null
    var calls = mutableListOf<String>()
    var answer = "Hello."
    override suspend fun reply(text: String): ReplySource.Reply {
        calls += text
        gate?.await()
        return ReplySource.Reply(answer, "template")
    }
}

private class FakeSpeaker : Speaker {
    var sink: LevelSink? = null
    var prosody: Prosody? = null
    var spoken = mutableListOf<String>()
    var finish: CompletableDeferred<Unit>? = null
    var stops = 0
    var releases = 0
    override suspend fun speak(text: String, epoch: Int, prosody: Prosody, levels: LevelSink) { spoken += text; sink = levels; this.prosody = prosody; finish?.await() }
    override fun stop() { stops++ }
    override fun release() { releases++ }
}

@OptIn(ExperimentalCoroutinesApi::class)
private class Rig(
    scope: TestScope,
    permission: MicPermission = MicPermission.Granted,
    var availability: RecognizerAvailability = RecognizerAvailability.OnDevice,
    mood: VoiceMood = NeutralMood,
) {
    val job = Job()
    val permissions = FakePermissions(permission)
    val service = FakeService()
    val replies = FakeReplies()
    val speaker = FakeSpeaker()
    val recognizers = mutableListOf<FakeRecognizer>()
    var open = 0
    val effects = mutableListOf<TalkEffect>()
    val controller = VoiceController(
        permissions = permissions,
        availability = { availability },
        recognizerFactory = { open++; FakeRecognizer { open-- }.also { recognizers += it } },
        replies = replies,
        speaker = speaker,
        service = service,
        scope = CoroutineScope(job + StandardTestDispatcher(scope.testScheduler)),
        mood = mood,
    )
    val last get() = recognizers.last()
    val ui get() = controller.ui.value

    fun notices() = ui.lines.filter { it.who == Who.Notice }.map { it.text }
    fun said() = ui.lines.filter { it.who == Who.Reva }.map { it.text }

    /** Listening with the microphone open, permission already granted. */
    fun listening() { controller.onMicTapped() }

    fun close() { controller.close(); job.cancel() }
}

@OptIn(ExperimentalCoroutinesApi::class)
class VoiceControllerTest {
    // ---------------------------------------------------------------- permission (AR-AND-001)

    @Test fun nothing_asks_for_the_microphone_until_the_mic_is_tapped() = runTest {
        val rig = Rig(this, MicPermission.NotAsked)
        val collected = mutableListOf<TalkEffect>()
        val collector = CoroutineScope(rig.job + StandardTestDispatcher(testScheduler))
        collector.collectEffects(rig, collected)

        rig.controller.onTextSubmitted("hello")
        rig.controller.onForegrounded()
        advanceUntilIdle()
        assertTrue(collected.isEmpty())
        assertEquals(0, rig.open)

        rig.controller.onMicTapped()
        runCurrent()
        assertEquals(listOf<TalkEffect>(TalkEffect.RequestMicPermission), collected)
        assertEquals(VoiceState.AcquiringPermission, rig.ui.state)
        assertEquals(0, rig.open)
        assertEquals(0, rig.service.starts)
        rig.close()
    }

    @Test fun granting_opens_the_microphone_once_with_the_service_first() = runTest {
        val rig = Rig(this, MicPermission.NotAsked)
        rig.controller.onMicTapped()
        rig.permissions.state = MicPermission.Granted

        rig.controller.onPermissionChanged()

        assertEquals(VoiceState.Listening, rig.ui.state)
        assertTrue(rig.ui.micOpen)
        assertEquals(1, rig.service.starts)
        assertEquals(1, rig.open)
        rig.close()
    }

    @Test fun denying_leaves_text_fully_usable() = runTest {
        val rig = Rig(this, MicPermission.NotAsked)
        rig.controller.onMicTapped()
        rig.permissions.state = MicPermission.Denied

        rig.controller.onPermissionChanged()
        rig.controller.onTextSubmitted("what is my balance")
        advanceUntilIdle()

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertFalse(rig.ui.micOpen)
        assertEquals(0, rig.open)
        assertEquals(0, rig.service.starts)
        assertTrue(rig.notices().single().contains("refused"))
        assertEquals(listOf("what is my balance"), rig.replies.calls)
        assertEquals(listOf("Hello."), rig.said())
        rig.close()
    }

    @Test fun deny_forever_does_not_show_the_dialog_again_and_says_where_to_turn_it_on() = runTest {
        val rig = Rig(this, MicPermission.DeniedForever)
        val collected = mutableListOf<TalkEffect>()
        CoroutineScope(rig.job + StandardTestDispatcher(testScheduler)).collectEffects(rig, collected)

        rig.controller.onMicTapped()
        runCurrent()

        assertTrue(collected.isEmpty())
        assertEquals(MicPermission.DeniedForever, rig.ui.permission)
        assertEquals(VoiceState.Idle, rig.ui.state)
        assertTrue(rig.notices().single().contains("settings"))
        rig.controller.onTextSubmitted("hi")
        advanceUntilIdle()
        assertEquals(1, rig.said().size)
        rig.close()
    }

    @Test fun revoking_mid_session_stops_listening_releases_everything_and_keeps_text() = runTest {
        val rig = Rig(this)
        rig.listening()
        val recognizer = rig.last
        rig.permissions.state = MicPermission.Denied

        rig.controller.onPermissionRevoked()

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(1, recognizer.released)
        assertEquals(0, rig.open)
        assertEquals(rig.service.starts, rig.service.stops)
        assertEquals(MicPermission.Denied, rig.ui.permission)
        assertTrue(rig.notices().single().contains("turned off"))
        recognizer.listener!!.onFinal("too late")
        advanceUntilIdle()
        assertTrue("a result after the revoke must be ignored", rig.replies.calls.isEmpty())
        rig.controller.onTextSubmitted("still works")
        advanceUntilIdle()
        assertEquals(listOf("still works"), rig.replies.calls)
        rig.close()
    }

    @Test fun android_reporting_missing_permission_takes_the_same_path() = runTest {
        val rig = Rig(this)
        rig.listening()
        rig.permissions.state = MicPermission.Denied

        rig.last.listener!!.onError(RecognizerError.PermissionRevoked)

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(0, rig.open)
        assertEquals(MicPermission.Denied, rig.ui.permission)
        rig.close()
    }

    // ---------------------------------------------------------------- on-device only (AR-AND-003)

    @Test fun without_on_device_recognition_voice_is_off_with_a_reason_and_nothing_starts() = runTest {
        for (availability in listOf(RecognizerAvailability.NotInstalled, RecognizerAvailability.UnknownBeforeAndroid13)) {
            val rig = Rig(this, MicPermission.NotAsked, availability)
            val collected = mutableListOf<TalkEffect>()
            CoroutineScope(rig.job + StandardTestDispatcher(testScheduler)).collectEffects(rig, collected)
            assertTrue(rig.ui.voiceOffReason!!.contains("Nothing is sent to a server"))

            rig.controller.onMicTapped()
            runCurrent()

            assertTrue("no permission dialog for a recognizer that cannot be used", collected.isEmpty())
            assertEquals(0, rig.open)
            assertEquals(0, rig.service.starts)
            assertEquals(VoiceState.Idle, rig.ui.state)
            assertEquals(1, rig.notices().size)
            rig.controller.onTextSubmitted("typing is fine")
            advanceUntilIdle()
            assertEquals(1, rig.said().size)
            rig.close()
        }
    }

    @Test fun the_policy_names_a_reason_for_every_unusable_case_and_none_for_on_device() {
        assertNull(RecognizerPolicy.disclosure(RecognizerAvailability.OnDevice))
        assertTrue(RecognizerPolicy.usable(RecognizerAvailability.OnDevice))
        for (a in listOf(RecognizerAvailability.NotInstalled, RecognizerAvailability.UnknownBeforeAndroid13)) {
            assertFalse(RecognizerPolicy.usable(a))
            assertTrue(RecognizerPolicy.disclosure(a)!!.isNotBlank())
        }
    }

    // ---------------------------------------------------------------- a turn

    @Test fun a_spoken_turn_closes_the_microphone_before_the_reply_and_releases_everything_at_the_end() = runTest {
        val rig = Rig(this)
        rig.replies.gate = CompletableDeferred()
        rig.speaker.finish = CompletableDeferred()
        rig.listening()
        rig.last.listener!!.onPartial("hel")
        assertEquals("hel", rig.ui.partial)

        rig.last.listener!!.onFinal("hello there")
        runCurrent()

        assertEquals(VoiceState.Reasoning, rig.ui.state)
        assertFalse("the microphone closes as soon as the utterance is over", rig.ui.micOpen)
        assertEquals(0, rig.open)
        assertEquals(1, rig.service.stops)

        rig.replies.gate!!.complete(Unit)
        runCurrent()
        assertEquals(VoiceState.Speaking, rig.ui.state)
        assertEquals(listOf("Hello."), rig.speaker.spoken)

        rig.speaker.finish!!.complete(Unit)
        runCurrent()
        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(1, rig.speaker.releases.coerceAtLeast(1))
        assertEquals(0, rig.open)
        rig.close()
    }

    @Test fun nothing_heard_returns_to_idle_with_a_notice_and_releases() = runTest {
        val rig = Rig(this)
        rig.listening()

        rig.last.listener!!.onError(RecognizerError.NoSpeech)

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(0, rig.open)
        assertEquals(rig.service.starts, rig.service.stops)
        assertEquals(listOf("I didn't catch that."), rig.notices())
        rig.close()
    }

    @Test fun an_empty_final_result_is_treated_as_nothing_heard() = runTest {
        val rig = Rig(this)
        rig.listening()

        rig.last.listener!!.onFinal("   ")
        advanceUntilIdle()

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertTrue(rig.replies.calls.isEmpty())
        rig.close()
    }

    @Test fun the_tap_while_listening_asks_the_recognizer_to_finish() = runTest {
        val rig = Rig(this)
        rig.listening()

        rig.controller.onMicTapped()

        assertEquals(1, rig.last.stopped)
        assertEquals(VoiceState.Listening, rig.ui.state)
        rig.close()
    }

    @Test fun a_refused_service_means_no_listening() = runTest {
        val rig = Rig(this)
        rig.service.allow = false

        rig.controller.onMicTapped()

        assertEquals(0, rig.open)
        assertEquals(VoiceState.Idle, rig.ui.state)
        assertTrue(rig.notices().single().contains("microphone service"))
        rig.close()
    }

    @Test fun the_recognizer_errors_are_each_handled_and_each_release() = runTest {
        for (error in RecognizerError.entries) {
            val rig = Rig(this)
            rig.listening()
            rig.last.listener!!.onError(error)
            assertEquals(error.name, VoiceState.Idle, rig.ui.state)
            assertEquals(error.name, 0, rig.open)
            rig.close()
        }
    }

    // ---------------------------------------------------------------- interruption and stale events

    @Test fun tapping_while_the_reply_is_spoken_interrupts_and_listens_again() = runTest {
        val rig = Rig(this)
        rig.speaker.finish = CompletableDeferred()
        rig.listening()
        rig.last.listener!!.onFinal("hello")
        runCurrent()
        assertEquals(VoiceState.Speaking, rig.ui.state)

        rig.controller.onMicTapped()

        assertEquals(VoiceState.Listening, rig.ui.state)
        assertTrue(rig.speaker.stops >= 1)
        assertEquals(2, rig.recognizers.size)
        assertTrue(rig.ui.micOpen)
        // The first sentence finishing late must not end the new listening session.
        rig.speaker.finish!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(VoiceState.Listening, rig.ui.state)
        assertTrue(rig.ui.micOpen)
        rig.close()
    }

    @Test fun a_result_from_the_old_recognizer_after_an_interrupt_is_dropped() = runTest {
        val rig = Rig(this)
        rig.speaker.finish = CompletableDeferred()
        rig.listening()
        val old = rig.last
        old.listener!!.onFinal("first")
        runCurrent()
        rig.controller.onMicTapped()

        old.listener!!.onFinal("stale words")
        old.listener!!.onPartial("stale partial")
        old.listener!!.onError(RecognizerError.Failed)
        advanceUntilIdle()

        assertEquals(listOf("first"), rig.replies.calls)
        assertEquals("", rig.ui.partial)
        assertEquals(VoiceState.Listening, rig.ui.state)
        rig.close()
    }

    @Test fun a_reply_that_arrives_after_an_interrupt_is_not_shown_or_spoken() = runTest {
        val rig = Rig(this)
        rig.replies.gate = CompletableDeferred()
        rig.listening()
        rig.last.listener!!.onFinal("slow question")
        runCurrent()
        assertEquals(VoiceState.Reasoning, rig.ui.state)

        rig.controller.onMicTapped() // interrupt while thinking
        rig.replies.gate!!.complete(Unit)
        advanceUntilIdle()

        assertTrue(rig.said().isEmpty())
        assertTrue(rig.speaker.spoken.isEmpty())
        rig.close()
    }

    @Test fun a_newer_typed_turn_replaces_an_older_one_still_waiting() = runTest {
        val rig = Rig(this)
        rig.replies.gate = CompletableDeferred()
        rig.controller.onTextSubmitted("first")
        runCurrent()
        rig.controller.onTextSubmitted("second")
        runCurrent()

        rig.replies.gate!!.complete(Unit)
        advanceUntilIdle()

        assertEquals(1, rig.said().size)
        assertFalse(rig.ui.thinking)
        rig.close()
    }

    @Test fun starting_to_talk_drops_a_typed_reply_that_was_still_coming() = runTest {
        val rig = Rig(this)
        rig.replies.gate = CompletableDeferred()
        rig.controller.onTextSubmitted("typed")
        runCurrent()

        rig.controller.onMicTapped()
        rig.replies.gate!!.complete(Unit)
        advanceUntilIdle()

        assertTrue(rig.said().isEmpty())
        rig.close()
    }

    @Test fun partial_text_is_bounded() = runTest {
        val rig = Rig(this)
        rig.listening()

        rig.last.listener!!.onPartial("x".repeat(5000))

        assertEquals(VoiceController.MAX_TEXT, rig.ui.partial.length)
        rig.close()
    }

    // ---------------------------------------------------------------- speech, mood and the avatar's inputs

    @Test fun loudness_is_passed_on_only_while_speaking_and_only_for_the_current_epoch() = runTest {
        val rig = Rig(this)
        rig.speaker.finish = CompletableDeferred()
        val seen = mutableListOf<Level>()
        val collector = CoroutineScope(rig.job + StandardTestDispatcher(testScheduler))
        collector.launch(start = CoroutineStart.UNDISPATCHED) { rig.controller.levels.collect { seen += it } }
        rig.listening()
        rig.last.listener!!.onFinal("hello")
        runCurrent()
        val epoch = rig.ui.epoch

        rig.speaker.sink!!.onLevel(epoch, 0.4, 20)
        rig.speaker.sink!!.onLevel(epoch - 1, 0.9, 40) // an older sentence
        runCurrent()
        assertEquals(listOf(Level(epoch, 0.4, 20)), seen)

        rig.controller.onStopTapped() // speech ended
        rig.speaker.sink!!.onLevel(epoch, 0.5, 60)
        runCurrent()
        assertEquals("nothing after the speech ended", 1, seen.size)
        rig.close()
    }

    @Test fun the_mood_decides_how_the_reply_sounds_and_which_face_may_show() = runTest {
        val face = ExpressionEvent("relaxed", "mood")
        val rig = Rig(this, mood = VoiceMood { MoodDecision(Prosody(0.9f, -1), face) })
        rig.speaker.finish = CompletableDeferred()
        rig.listening()

        rig.last.listener!!.onFinal("good evening")
        runCurrent()

        assertEquals(Prosody(0.9f, -1), rig.speaker.prosody)
        assertEquals(face, rig.ui.expression)
        assertEquals(1, rig.ui.expressionSeq)
        // The words are the reply source's. The mood never rewrites them.
        assertEquals(listOf("Hello."), rig.speaker.spoken)
        rig.close()
    }

    @Test fun a_typed_reply_is_shown_but_not_spoken() = runTest {
        val rig = Rig(this)

        rig.controller.onTextSubmitted("hello")
        advanceUntilIdle()

        assertTrue(rig.speaker.spoken.isEmpty())
        assertEquals(1, rig.said().size)
        rig.close()
    }

    @Test fun a_failure_is_flagged_for_the_error_pose_and_cleared_by_the_next_try() = runTest {
        val rig = Rig(this)
        rig.service.allow = false
        rig.controller.onMicTapped()
        assertTrue(rig.ui.failed)

        rig.service.allow = true
        rig.controller.onMicTapped()

        assertFalse(rig.ui.failed)
        assertEquals(VoiceState.Listening, rig.ui.state)
        rig.close()
    }

    @Test fun the_epoch_in_the_ui_follows_the_session_so_the_avatar_can_drop_old_messages() = runTest {
        val rig = Rig(this)
        rig.listening()
        val first = rig.ui.epoch

        rig.controller.onStopTapped()
        rig.listening()

        assertTrue(rig.ui.epoch > first)
        rig.close()
    }

    // ---------------------------------------------------------------- foreground and background

    @Test fun leaving_the_screen_while_listening_closes_the_microphone_with_a_notice() = runTest {
        val rig = Rig(this)
        rig.listening()
        val recognizer = rig.last

        rig.controller.onBackgrounded()

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(1, recognizer.released)
        assertEquals(0, rig.open)
        assertEquals(rig.service.starts, rig.service.stops)
        assertTrue(rig.notices().single().contains("left the screen"))
        recognizer.listener!!.onFinal("after background")
        advanceUntilIdle()
        assertTrue(rig.replies.calls.isEmpty())
        rig.close()
    }

    @Test fun leaving_the_screen_while_idle_changes_nothing() = runTest {
        val rig = Rig(this)

        rig.controller.onBackgrounded()

        assertTrue(rig.ui.lines.isEmpty())
        rig.close()
    }

    @Test fun coming_back_reads_the_permission_again_and_a_new_tap_recovers() = runTest {
        val rig = Rig(this)
        rig.listening()
        rig.controller.onBackgrounded()
        rig.permissions.state = MicPermission.Denied

        rig.controller.onForegrounded()
        assertEquals(MicPermission.Denied, rig.ui.permission)

        rig.permissions.state = MicPermission.Granted
        rig.controller.onForegrounded()
        rig.controller.onMicTapped()

        assertEquals(VoiceState.Listening, rig.ui.state)
        assertEquals(2, rig.recognizers.size)
        rig.close()
    }

    @Test fun the_stop_action_ends_the_session_from_anywhere() = runTest {
        val rig = Rig(this)
        rig.speaker.finish = CompletableDeferred()
        rig.listening()
        rig.last.listener!!.onFinal("hello")
        runCurrent()

        rig.controller.onStopTapped()

        assertEquals(VoiceState.Idle, rig.ui.state)
        assertEquals(0, rig.open)
        assertTrue(rig.speaker.stops >= 1)
        rig.close()
    }

    // ---------------------------------------------------------------- release on every path (AR-AND-004)

    @Test fun recognizer_service_and_speaker_are_released_at_the_end_of_every_kind_of_session() = runTest {
        val endings: List<(Rig) -> Unit> = listOf(
            { it.last.listener!!.onFinal("x"); },
            { it.last.listener!!.onError(RecognizerError.NoSpeech) },
            { it.last.listener!!.onError(RecognizerError.Failed) },
            { it.controller.onBackgrounded() },
            { it.controller.onStopTapped() },
            { it.controller.onPermissionRevoked() },
            { it.controller.close() },
        )
        for ((index, ending) in endings.withIndex()) {
            val rig = Rig(this)
            rig.replies.gate = CompletableDeferred()
            rig.listening()
            ending(rig)
            rig.controller.onStopTapped()
            advanceUntilIdle()
            assertEquals("ending $index leaves no recognizer open", 0, rig.open)
            assertEquals("ending $index balances service start and stop", rig.service.starts, rig.service.stops.coerceAtMost(rig.service.starts))
            assertTrue("ending $index releases the speaker", rig.speaker.releases >= 1)
            assertTrue(rig.recognizers.all { it.released >= 1 })
            rig.job.cancel()
        }
    }

    @Test fun many_sessions_in_a_row_leak_nothing() = runTest {
        val rig = Rig(this)
        repeat(25) {
            rig.listening()
            rig.last.listener!!.onFinal("turn $it")
            advanceUntilIdle()
            rig.controller.onStopTapped()
        }
        assertEquals(0, rig.open)
        assertEquals(25, rig.recognizers.size)
        assertTrue(rig.recognizers.all { it.released >= 1 })
        assertTrue("the transcript is bounded", rig.ui.lines.size <= VoiceController.MAX_LINES)
        rig.close()
    }

    @Test fun typed_input_over_the_limit_is_cut_and_blank_input_is_ignored() = runTest {
        val rig = Rig(this)

        rig.controller.onTextSubmitted("   ")
        rig.controller.onTextSubmitted("y".repeat(900))
        advanceUntilIdle()

        assertEquals(1, rig.replies.calls.size)
        assertEquals(VoiceController.MAX_TEXT, rig.replies.calls.single().length)
        rig.close()
    }
}

private fun CoroutineScope.collectEffects(rig: Rig, into: MutableList<TalkEffect>) {
    launch(start = CoroutineStart.UNDISPATCHED) { rig.controller.effects.collect { into += it } }
}
