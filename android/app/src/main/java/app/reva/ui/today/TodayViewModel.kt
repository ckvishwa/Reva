package app.reva.ui.today

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.reva.core.Display
import app.reva.core.Money
import app.reva.data.FinanceRepository
import app.reva.data.FinanceDailyAnalysis
import app.reva.data.Outcome
import java.time.LocalDate
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.dropWhile
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DailyFinanceRow(val currency: String, val incomeText: String, val expenseText: String, val netText: String)

data class TodayUiState(
    val isLoading: Boolean = false,
    val error: String? = null,
    val hasBudget: Boolean = false,
    val budgetLeftText: String = "—",
    val budgetOfText: String = "",
    val budgetFraction: Float = 0f,
    val budgetNearLimit: Boolean = false,
    val otherCurrenciesText: String = "",
    val billsText: String = "",
    val dailyRows: List<DailyFinanceRow> = emptyList(),
    val topSpendingText: String = "",
    val dailySourceCount: Int = 0,
    val dailyError: String? = null,
) {
    val accessibleSummary: String
        get() = error ?: buildString {
            append(if (hasBudget) "Budget left this month: $budgetLeftText $budgetOfText. " else "$budgetLeftText. ")
            append(billsText)
            if (dailyRows.isNotEmpty()) append(". Daily finance: " + dailyRows.joinToString("; ") { "${it.currency} income ${it.incomeText}, expenses ${it.expenseText}, net ${it.netText}" })
            if (dailyError != null) append(". Daily finance unavailable: $dailyError")
        }.trim()
}

/** Today: budget left this month and bills due in the next 7 days, both from the Kernel's read-only summary. */
class TodayViewModel(
    private val repository: FinanceRepository,
    private val changeDebounceMillis: Long = 300,
    private val today: () -> LocalDate = { LocalDate.now() },
) : ViewModel() {

    private val _state = MutableStateFlow(TodayUiState())
    val state: StateFlow<TodayUiState> = _state.asStateFlow()
    private var generation = 0
    private var loadedOnce = false

    init {
        // A local commit or a sync batch moved the counter: reload the numbers on screen (SYNC-1e).
        val seen = repository.changes.value // a change after this point must not be missed, even before collecting starts
        viewModelScope.launch {
            @OptIn(FlowPreview::class)
            repository.changes.dropWhile { it == seen }.debounce(changeDebounceMillis).collect {
                if (loadedOnce) refreshNow(showLoading = false)
            }
        }
    }

    fun refresh() {
        viewModelScope.launch { refreshNow() }
    }

    suspend fun refreshNow(showLoading: Boolean = true) {
        val mine = ++generation
        _state.update { it.copy(isLoading = showLoading) }
        val result = repository.today()
        if (mine != generation) return
        loadedOnce = true
        when (result) {
            is Outcome.Failed -> _state.value = TodayUiState(error = result.error.message, budgetLeftText = "—")
            is Outcome.Ok -> {
                apply(result.value)
                val daily = repository.dailyAnalysis(today().toString())
                if (mine != generation) return
                _state.update { current -> when (daily) {
                    is Outcome.Failed -> current.copy(dailyError = daily.error.message)
                    is Outcome.Ok -> current.withDaily(daily.value)
                } }
            }
        }
    }

    private fun TodayUiState.withDaily(analysis: FinanceDailyAnalysis): TodayUiState = copy(
        dailyRows = analysis.cashflow.sortedBy { it.currency }.map {
            DailyFinanceRow(it.currency, Money.format(it.incomeMinor, it.currency), Money.format(it.expenseMinor, it.currency), Money.format(it.netMinor, it.currency))
        },
        topSpendingText = analysis.spending.groupBy { it.currency }.toSortedMap().values.mapNotNull { group ->
            group.maxByOrNull { it.spentMinor }?.let { "${it.category} ${Money.format(it.spentMinor, it.currency)}" }
        }.joinToString(" · "),
        dailySourceCount = analysis.sourceIds.distinct().size,
    )

    private fun apply(summary: app.reva.data.TodaySummary) {
        val now = today()
        val budgets = summary.budgetLeft
        var state = TodayUiState()
        if (budgets.isEmpty()) {
            state = state.copy(budgetLeftText = "No budgets set")
        } else {
            val main = budgets.maxByOrNull { it.budgetMinor }!!
            val usedBp = if (main.budgetMinor > 0) (main.spentMinor * 10_000L / main.budgetMinor) else 0L
            state = state.copy(
                hasBudget = true,
                budgetLeftText = Money.format(main.remainingMinor, main.currency),
                budgetOfText = "of ${Money.format(main.budgetMinor, main.currency)}",
                budgetFraction = Display.barFraction(usedBp),
                budgetNearLimit = Display.isNearLimit(usedBp),
                otherCurrenciesText = budgets.filter { it !== main }.joinToString(" · ") {
                    "${Money.format(it.remainingMinor, it.currency)} left of ${Money.format(it.budgetMinor, it.currency)}"
                },
            )
        }
        val bills = summary.billsDue.filter { it.kind != "income" }
        state = state.copy(
            billsText = if (bills.isEmpty()) "No bills in the next 7 days"
            else "Bills in 7 days · " + bills.joinToString(" · ") { "${it.name} ${Display.shortDate(it.dueDate, now)}" },
        )
        _state.value = state
    }
}
