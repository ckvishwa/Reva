package app.reva.brain

import app.reva.data.ErrorKind
import app.reva.data.FinanceError
import app.reva.data.FinanceRepository
import app.reva.data.Outcome
import app.reva.data.TodayBudgetLeft
import app.reva.data.TodaySummary
import app.reva.language.PolicyReplies
import app.reva.policy.loadRegistry
import app.reva.testing.FakeFinanceRepository
import java.time.Instant
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalBrainTest {
    @Test fun today_is_read_from_the_local_kernel_repository_without_a_pc_or_provider() = runBlocking {
        val repo = FakeFinanceRepository().apply {
            todaySummary = TodaySummary(
                "2026-10-16",
                listOf(TodayBudgetLeft("USD", 20_000, 7_500, 12_500)),
                emptyList(),
            )
        }
        val replies = PolicyReplies(
            loadRegistry(), clock = { Instant.parse("2026-10-16T12:00:00Z") },
            local = KernelQueries(repo), fallback = LocalBrain(PlannerRegistry.offlineOnly()),
        )

        val answer = replies.reply("what's on today")

        assertTrue(answer.text.contains("$125.00"))
        assertEquals(listOf("today"), repo.calls)
    }

    @Test fun a_locked_kernel_returns_a_failure_instead_of_a_guessed_answer() = runBlocking {
        val repo = FakeFinanceRepository().apply {
            failures["today"] = FinanceError(ErrorKind.Locked, "Finance is locked on this phone.")
        }
        val result = KernelQueries(repo).answer("today.get", emptyMap())

        assertEquals(BrainResult.Failure("Finance is locked on this phone."), result)
    }

    @Test fun forbidden_action_never_reaches_a_local_query_or_provider() = runBlocking {
        val repo = FakeFinanceRepository()
        var providerCalls = 0
        val brain = LocalBrain(PlannerRegistry(mapOf("offline-lite" to PlannerClient {
            providerCalls++
            BrainResult.Answer("unsafe", "offline-lite")
        })))
        val replies = PolicyReplies(loadRegistry(), local = KernelQueries(repo), fallback = brain)

        val answer = replies.reply("pay my rent")

        assertFalse(answer.text.contains("unsafe"))
        assertTrue(repo.calls.isEmpty())
        assertEquals(0, providerCalls)
    }

    @Test fun unexpected_kernel_failure_does_not_expose_sensitive_error_details() = runBlocking {
        val broken = object : FinanceRepository by FakeFinanceRepository() {
            override suspend fun today(): Outcome<TodaySummary> = error("secret key and file path")
        }

        val result = KernelQueries(broken).answer("today.get", emptyMap())

        assertEquals(BrainResult.Failure(KernelQueries.LOCAL_UNAVAILABLE), result)
    }

    @Test fun the_offline_provider_does_not_invent_an_open_answer() = runBlocking {
        val result = LocalBrain(PlannerRegistry.offlineOnly()).reply("Tell me about Jupiter")

        assertEquals(LocalBrain.ADVANCED_UNAVAILABLE, result.text)
    }

    @Test fun timeout_does_not_fall_back_to_an_unapproved_provider() = runBlocking {
        val hung = PlannerClient { CompletableDeferred<BrainResult>().await() }
        val brain = LocalBrain(PlannerRegistry(mapOf("hosted" to hung)), provider = { "hosted" }, timeoutMillis = 10)

        val result = brain.reply("open question")

        assertEquals(LocalBrain.TIMED_OUT, result.text)
    }

    @Test fun cancellation_rejects_a_late_planner_answer() = runBlocking {
        val gate = CompletableDeferred<BrainResult>()
        val brain = LocalBrain(PlannerRegistry(mapOf("hosted" to PlannerClient { gate.await() })), provider = { "hosted" })
        val turn = async(start = CoroutineStart.UNDISPATCHED) { brain.reply("question") }
        brain.cancel()
        gate.complete(BrainResult.Answer("A stale answer", "hosted"))

        assertFalse(turn.await().text.contains("stale"))
    }

    @Test fun missing_provider_is_unknown_and_never_routes_elsewhere() = runBlocking {
        val result = LocalBrain(PlannerRegistry.offlineOnly(), provider = { "hosted" }).reply("question")

        assertTrue(result.text.contains("unavailable"))
    }

    @Test fun planner_exception_is_a_typed_failure_without_exposing_its_message() = runBlocking {
        val brain = LocalBrain(PlannerRegistry(mapOf("bad" to PlannerClient {
            error("secret transcript and token")
        })), provider = { "bad" })

        val result = brain.reply("question")

        assertEquals(LocalBrain.PROVIDER_FAILED, result.text)
        assertFalse(result.text.contains("secret"))
    }
}
