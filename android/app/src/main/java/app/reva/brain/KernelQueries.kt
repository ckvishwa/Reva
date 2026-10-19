package app.reva.brain

import app.reva.core.Money
import app.reva.data.FinanceRepository
import app.reva.data.Outcome
import java.time.LocalDate
import kotlinx.coroutines.CancellationException

/** Read-only local answers use the Android Finance repository, which queries the Rust Kernel on IO. */
class KernelQueries(private val finance: FinanceRepository, private val today: () -> LocalDate = { LocalDate.now() }) {
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
        "finance.summary" -> {
            val period = when (args["period"]) {
                "week" -> "last_7_days"
                "month" -> "this_month"
                "year" -> "this_year"
                else -> return BrainResult.Failure("I need a week, month or year to summarize.")
            }
            when (val result = try {
                finance.periodAnalysis(period, today().toString())
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                return BrainResult.Failure(LOCAL_UNAVAILABLE)
            }) {
                is Outcome.Failed -> BrainResult.Failure(result.error.message)
                is Outcome.Ok -> {
                    val data = result.value
                    if (data.sourceIds.isEmpty()) BrainResult.Answer("No transactions are recorded for that period.", "kernel")
                    else {
                        val totals = data.cashflow.joinToString(" ") {
                            "${it.currency}: ${Money.format(it.expenseMinor, it.currency)} spent, ${Money.format(it.incomeMinor, it.currency)} received."
                        }
                        val categories = data.spending.take(5).joinToString(", ") {
                            "${it.category} ${Money.format(it.spentMinor, it.currency)}"
                        }
                        val categoryText = if (categories.isEmpty()) "" else " Categories: $categories."
                        BrainResult.Answer("$totals$categoryText ${data.sourceIds.distinct().size} source records.", "kernel")
                    }
                }
            }
        }
        else -> null
    }
}
