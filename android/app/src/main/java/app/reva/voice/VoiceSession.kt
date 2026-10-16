package app.reva.voice

/**
 * Session states and the legal transitions between them. The table is the same one the PC Core uses
 * (`reva_core/session/state.py`, ARD-300 section 3); `tests/fixtures/session-transitions.json` is checked
 * against both so they cannot drift apart.
 *
 *     Idle -> AcquiringPermission -> Listening -> Endpointing -> Transcribing -> Reasoning
 *          -> [ApprovalPending -> Executing] -> Speaking -> Listening | Idle
 *
 * Any live state may also go to Cancelling (then Idle), RecoverableError or FatalError. A barge-in is not
 * a transition in this table: it bumps the turn epoch and re-enters Listening ([VoiceSession.interrupt]).
 */
enum class VoiceState(val wire: String) {
    Idle("idle"),
    AcquiringPermission("acquiring_permission"),
    Listening("listening"),
    Endpointing("endpointing"),
    Transcribing("transcribing"),
    Reasoning("reasoning"),
    ApprovalPending("approval_pending"),
    Executing("executing"),
    Speaking("speaking"),
    Cancelling("cancelling"),
    RecoverableError("recoverable_error"),
    FatalError("fatal_error"),
}

object VoiceTransitions {
    private val s = VoiceState.entries.associateBy { it.wire }

    private fun set(vararg wire: String) = wire.map { s.getValue(it) }.toSet()

    val forward: Map<VoiceState, Set<VoiceState>> = mapOf(
        VoiceState.Idle to set("acquiring_permission"),
        VoiceState.AcquiringPermission to set("listening"),
        VoiceState.Listening to set("endpointing"),
        VoiceState.Endpointing to set("transcribing", "listening"),
        VoiceState.Transcribing to set("reasoning", "listening"),
        VoiceState.Reasoning to set("approval_pending", "executing", "speaking"),
        VoiceState.ApprovalPending to set("executing", "speaking"),
        VoiceState.Executing to set("speaking"),
        VoiceState.Speaking to set("listening", "idle"),
        VoiceState.Cancelling to set("idle"),
        VoiceState.RecoverableError to set("idle", "listening"),
        VoiceState.FatalError to emptySet(),
    )

    private val anyLiveMayGo = setOf(VoiceState.Cancelling, VoiceState.RecoverableError, VoiceState.FatalError)
    private val notLive = setOf(VoiceState.Idle, VoiceState.FatalError)

    /** States in which a barge-in has something to cancel. */
    val interruptible = setOf(
        VoiceState.Transcribing,
        VoiceState.Reasoning,
        VoiceState.ApprovalPending,
        VoiceState.Executing,
        VoiceState.Speaking,
    )

    fun canGo(from: VoiceState, to: VoiceState): Boolean =
        to in forward.getValue(from) || (from !in notLive && to in anyLiveMayGo)
}

/**
 * One voice session's state and turn epoch. Every result that arrives later (a transcript, a reply, a
 * finished sentence) carries the epoch it started under; [isCurrent] says whether it still counts. After
 * [interrupt] or [cancel] the old epoch is stale and its results are dropped, so a late recognizer callback
 * can never move the session or speak over the owner.
 */
class VoiceSession {
    var state: VoiceState = VoiceState.Idle
        private set
    var epoch: Int = 0
        private set

    /** Moves to [to] when the table allows it; returns false and changes nothing otherwise. */
    fun go(to: VoiceState): Boolean {
        if (!VoiceTransitions.canGo(state, to)) return false
        state = to
        return true
    }

    fun isCurrent(epoch: Int): Boolean = epoch == this.epoch

    /** Barge-in: a new epoch, back to Listening. Returns the new epoch, or null when nothing was interruptible. */
    fun interrupt(): Int? {
        if (state !in VoiceTransitions.interruptible) return null
        epoch += 1
        state = VoiceState.Listening
        return epoch
    }

    /** End the session from any live state: a new epoch and Idle, through Cancelling like the Core. */
    fun cancel() {
        if (state == VoiceState.Idle || state == VoiceState.FatalError) return
        epoch += 1
        state = VoiceState.Cancelling
        state = VoiceState.Idle
    }

    /** A new turn begins (a tap): a fresh epoch so nothing from the last one can land in it. */
    fun beginTurn(): Int {
        epoch += 1
        return epoch
    }
}
