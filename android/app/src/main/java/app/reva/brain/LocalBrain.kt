package app.reva.brain

import app.reva.voice.ReplySource
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout

/** A planner's words are never evidence that an action succeeded. */
sealed interface BrainResult {
    val text: String

    data class Answer(override val text: String, val provider: String) : BrainResult
    data class Failure(override val text: String) : BrainResult
    data class Unknown(override val text: String) : BrainResult
}

fun interface PlannerClient {
    suspend fun answer(text: String): BrainResult
}

/** Only explicitly registered providers can receive a turn. A missing selection fails closed. */
class PlannerRegistry(private val clients: Map<String, PlannerClient>) {
    fun get(id: String): PlannerClient? = clients[id]

    companion object {
        fun offlineOnly(): PlannerRegistry = PlannerRegistry(mapOf("offline-lite" to PlannerClient {
            BrainResult.Unknown(LocalBrain.ADVANCED_UNAVAILABLE)
        }))
    }
}

/** Open-question orchestration. The voice controller owns the outer session and turn epoch; this inner epoch
 * rejects a planner result after a mode change or explicit cancellation. No provider is tried as a fallback. */
class LocalBrain(
    private val registry: PlannerRegistry,
    private val provider: () -> String = { "offline-lite" },
    private val timeoutMillis: Long = 8_000,
) : ReplySource {
    private val epoch = AtomicInteger()

    fun cancel() { epoch.incrementAndGet() }

    override suspend fun reply(text: String): ReplySource.Reply {
        val mine = epoch.incrementAndGet()
        val client = registry.get(provider())
            ?: return ReplySource.Reply(PROVIDER_UNAVAILABLE, "template")
        val result = try {
            withTimeout(timeoutMillis) { client.answer(text) }
        } catch (_: TimeoutCancellationException) {
            BrainResult.Unknown(TIMED_OUT)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            BrainResult.Failure(PROVIDER_FAILED)
        }
        if (epoch.get() != mine) return ReplySource.Reply(STALE_RESULT, "template")
        return ReplySource.Reply(result.text, if (result is BrainResult.Answer) result.provider else "template")
    }

    companion object {
        const val ADVANCED_UNAVAILABLE = "Advanced reasoning is unavailable offline. I can still answer supported local questions."
        const val PROVIDER_UNAVAILABLE = "The selected reasoning provider is unavailable. Nothing was sent."
        const val TIMED_OUT = "The reasoning provider timed out. I don't know the answer."
        const val PROVIDER_FAILED = "The reasoning provider failed. I don't know the answer."
        const val STALE_RESULT = "That answer was cancelled."
    }
}
