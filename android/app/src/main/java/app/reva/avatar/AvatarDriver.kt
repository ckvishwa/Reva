package app.reva.avatar

import app.reva.voice.Level
import app.reva.voice.TalkUi
import app.reva.voice.VoiceState

/** Where avatar messages go: the WebView in the app, a list in tests. */
fun interface AvatarSink {
    fun post(json: String)
}

/**
 * Turns the voice session's true state into messages for the avatar page. It shows only what is really
 * happening (CLAUDE.md safety invariants):
 *  - Listening exactly while the recognizer is open (`micOpen`), never while only waiting for a permission.
 *  - The mouth moves only with loudness measured on audio that was played, only while speaking, and only for
 *    the current epoch.
 *  - Expressions come from the mood engine through the controller; this class never invents one.
 */
class AvatarDriver(private val sink: AvatarSink) {
    private var lastState: String? = null
    private var lastEpoch: Int = -1
    private var lastExpressionSeq = 0

    fun onUi(ui: TalkUi) {
        val state = stateFor(ui)
        if (ui.expressionSeq != lastExpressionSeq) {
            lastExpressionSeq = ui.expressionSeq
            ui.expression?.let { AvatarProtocol.expression(it.name, it.cause, it.actionId)?.let(sink::post) }
        }
        if (state != lastState || ui.epoch != lastEpoch) {
            lastState = state
            lastEpoch = ui.epoch
            AvatarProtocol.state(state, ui.epoch)?.let(sink::post)
        }
    }

    fun onLevel(level: Level) {
        if (lastState != "speaking" || level.epoch != lastEpoch) return
        AvatarProtocol.mouth(level.tMs, level.rms, level.epoch)?.let(sink::post)
    }

    fun onSettings(enabled: Boolean, reducedMotion: Boolean, quality: String) {
        AvatarProtocol.settings(enabled, reducedMotion, quality)?.let(sink::post)
    }

    companion object {
        fun stateFor(ui: TalkUi): String = when {
            ui.failed && ui.state == VoiceState.Idle -> "error"
            ui.micOpen -> "listening"
            ui.state == VoiceState.Speaking -> "speaking"
            ui.state == VoiceState.ApprovalPending -> "approval"
            ui.state in setOf(VoiceState.Endpointing, VoiceState.Transcribing, VoiceState.Reasoning) || ui.thinking -> "thinking"
            else -> "idle"
        }
    }
}
