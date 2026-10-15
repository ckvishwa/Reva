package app.reva.voice

/**
 * The reply source until the phone can answer on its own (standalone/offline-lite) or through the paired PC.
 * It says so plainly. It never produces an answer to a question and never claims an action happened.
 */
class UnavailableReplies : ReplySource {
    override suspend fun reply(text: String): ReplySource.Reply =
        ReplySource.Reply(UNAVAILABLE, source = "template")

    companion object {
        const val UNAVAILABLE =
            "I heard you, but I can't answer on the phone yet. Answering arrives with the next update."
    }
}
