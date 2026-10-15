package app.reva.avatar

import org.json.JSONObject
import kotlin.math.roundToInt

/**
 * Host-to-page messages (`contracts/avatar-events.schema.json`, version 2.1). Every message the phone sends
 * to the avatar page is built here and nowhere else, so nothing that breaks the schema can be sent: a builder
 * returns null for input that would be invalid. Same rules as the Windows host (`AvatarProtocol.cs`);
 * `avatar/test/fixtures/host-messages.json` holds the exact messages both hosts must produce, and the page's
 * own tests validate every one of them against the schema.
 */
object AvatarProtocol {
    val states = listOf("idle", "listening", "thinking", "speaking", "approval", "error")
    val expressions = listOf("neutral", "happy", "sad", "relaxed", "surprised")
    val causes = listOf("verified_outcome", "greeting", "error", "idle_variation", "mood")
    val qualities = listOf("low", "medium", "high")

    fun state(state: String, turnEpoch: Int): String? {
        if (state !in states || turnEpoch < 0) return null
        return JSONObject().put("type", "avatar.state").put("state", state).put("turn_epoch", turnEpoch).toString()
    }

    fun mouth(tMs: Int, rms: Double, turnEpoch: Int): String? {
        if (tMs < 0 || turnEpoch < 0 || rms.isNaN() || rms.isInfinite()) return null
        val clamped = rms.coerceIn(0.0, 1.0)
        val rounded = (clamped * 10_000).roundToInt() / 10_000.0
        return JSONObject().put("type", "avatar.mouth").put("t_ms", tMs).put("rms", rounded)
            .put("turn_epoch", turnEpoch).toString()
    }

    /** A face. A result face (`verified_outcome`) must name its action; anything else is refused. */
    fun expression(name: String, cause: String, actionId: String? = null): String? {
        if (name !in expressions || cause !in causes) return null
        if (actionId != null && (actionId.length < 8 || actionId.length > 64)) return null
        if (cause == "verified_outcome" && actionId == null) return null
        val message = JSONObject().put("type", "avatar.expression").put("name", name).put("cause", cause)
        if (actionId != null) message.put("action_id", actionId)
        return message.toString()
    }

    fun settings(enabled: Boolean, reducedMotion: Boolean? = null, quality: String? = null): String? {
        if (quality != null && quality !in qualities) return null
        val message = JSONObject().put("type", "avatar.settings").put("enabled", enabled)
        if (reducedMotion != null) message.put("reduced_motion", reducedMotion)
        if (quality != null) message.put("quality", quality)
        return message.toString()
    }
}
