package app.reva.mood

import app.reva.voice.MoodDecision
import app.reva.voice.Prosody
import app.reva.voice.VoiceMood

/**
 * Feeds the mood engine from what the phone knows in C1: the sentence and the hour. No action has run, so no
 * event is ever raised here, which means [MoodEngine.expressionEvent] can only return a `mood` expression and a
 * result face is impossible by construction (it needs a `verified_outcome` event and its action id).
 */
class EngineMood(
    private val engine: MoodEngine,
    private val hour: () -> Int,
    private val settings: () -> MoodSettings = { MoodSettings() },
) : VoiceMood {
    private var state = MoodState()

    override fun decide(userText: String): MoodDecision {
        val inputs = MoodInputs(hour = hour(), flags = MoodFlags.of(userText), settings = settings())
        val result = engine.next(state, inputs)
        state = result.state
        return MoodDecision(
            Prosody(result.voice.rate.toFloat(), result.voice.pitchSt),
            engine.expressionEvent(result, inputs),
        )
    }
}
