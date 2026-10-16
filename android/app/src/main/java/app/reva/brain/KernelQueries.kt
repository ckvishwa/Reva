package app.reva.brain

import app.reva.core.Money
import app.reva.data.FinanceRepository
import app.reva.data.Outcome
import kotlinx.coroutines.CancellationException

/** Read-only local answers use the Android Finance repository, which queries the Rust Kernel on IO. */
class KernelQueries(private val finance: FinanceRepository) {
    companion object {
        const val LOCAL_UNAVAILABLE = "Local Finance data is unavailable right now. I don't know the answer."
    }

    suspend fun answer(capability: String, args: Map<String, Any?>): BrainResult? = when (capability) {
        "today.get" -> when (val result = try {
            finance.today()
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            return BrainResult.Failure(LOCAL_UNAVAILABLE)
        }) {
            is Outcome.Failed -> BrainResult.Failure(result.error.message)
            is Outcome.Ok -> {
                val summary = result.value
                val budgets = if (summary.budgetLeft.isEmpty()) "No budgets are set."
                    else summary.budgetLeft.joinToString(" ") {
                        "${Money.format(it.remainingMinor, it.currency)} of ${Money.format(it.budgetMinor, it.currency)} left in the budget."
                    }
                val bills = if (summary.billsDue.isEmpty()) "No bills are due soon."
                    else "Bills due soon: " + summary.billsDue.joinToString { it.name }
                BrainResult.Answer("$budgets $bills", "kernel")
            }
        }
        "finance.summary" -> BrainResult.Unknown(
            "A full spending summary for ${args["period"]} is unavailable on this phone. I can show today's budget and bills.",
        )
        else -> null
    }
}
