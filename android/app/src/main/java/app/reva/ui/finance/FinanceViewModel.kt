package app.reva.ui.finance

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.reva.core.Display
import app.reva.core.Money
import app.reva.data.AccountBalance
import app.reva.data.Bill
import app.reva.data.BudgetStatus
import app.reva.data.Category
import app.reva.data.Conflict
import app.reva.data.ErrorKind
import app.reva.data.FinanceRepository
import app.reva.data.NetWorthSnapshot
import app.reva.data.Outcome
import app.reva.data.Transaction
import java.time.LocalDate
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.dropWhile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

// ---- what the screens show -------------------------------------------------------------------

data class AccountCard(val accountId: String, val title: String, val balanceText: String, val caption: String, val a11y: String)

data class NetWorthCard(val hasSnapshot: Boolean, val valueText: String, val caption: String, val a11y: String)

data class BudgetRow(
    val name: String,
    val amountsText: String,
    val fraction: Float,
    val isNearLimit: Boolean,
    val isOver: Boolean,
    val a11y: String,
)

data class BillRow(val name: String, val amountText: String, val dueText: String, val isSoon: Boolean, val a11y: String)

data class TransactionRow(
    val id: String,
    val dateText: String,
    val description: String,
    val categoryText: String,
    val accountText: String,
    val amountText: String,
    val isIncome: Boolean,
    val sourceText: String,
    val isVoice: Boolean,
    val a11y: String,
)

/** One amount the phone and the PC disagree about, with both values ready to show. */
data class ConflictRow(val id: Long, val title: String, val mineText: String, val pcText: String, val a11y: String)

data class FinanceUiState(
    val conflicts: List<ConflictRow> = emptyList(),
    val isLoading: Boolean = false,
    val hasLoaded: Boolean = false,
    val isLocked: Boolean = false,
    val error: String? = null,
    val accounts: List<AccountCard> = emptyList(),
    val netWorth: NetWorthCard = NetWorthCard(false, "No snapshot yet", "Take one to record today's net worth", "Net worth snapshot, none yet"),
    val budgets: List<BudgetRow> = emptyList(),
    val budgetPeriod: String = FinanceViewModel.THIS_MONTH,
    val bills: List<BillRow> = emptyList(),
    val transactions: List<TransactionRow> = emptyList(),
    val search: String = "",
    val isBusy: Boolean = false,
) {
    val hasAccounts: Boolean get() = accounts.isNotEmpty()
    val showEmptyState: Boolean get() = hasLoaded && error == null && accounts.isEmpty()
    val transactionsEmptyText: String
        get() = if (search.isBlank()) "No transactions yet." else "No transactions match that search."
}

/**
 * The Finance tab. Every load goes through [FinanceRepository] (suspend, off the main thread). A newer
 * refresh or search supersedes an older one, so a slow earlier answer can never overwrite a later one.
 */
class FinanceViewModel(
    private val repository: FinanceRepository,
    private val today: () -> LocalDate = { LocalDate.now() },
    private val searchDebounceMillis: Long = 300,
    private val changeDebounceMillis: Long = 300,
) : ViewModel() {

    private val _state = MutableStateFlow(FinanceUiState())
    val state: StateFlow<FinanceUiState> = _state.asStateFlow()

    private var balances: List<AccountBalance> = emptyList()
    private var categories: List<Category> = emptyList()
    private var refreshGeneration = 0
    private var searchGeneration = 0
    private var searchJob: Job? = null

    init {
        // Something committed (a local write, or a sync batch from the PC): reload what is on screen
        // without waiting for a tab switch. Bursts become one reload. Nothing loads before the first load.
        val seen = repository.changes.value // a change after this point must not be missed, even before collecting starts
        viewModelScope.launch {
            @OptIn(FlowPreview::class)
            repository.changes.dropWhile { it == seen }.debounce(changeDebounceMillis).collect {
                if (_state.value.hasLoaded) refreshNow(showLoading = false)
            }
        }
    }

    val accountsForForms: List<AccountBalance> get() = balances.filter { !it.archived }
    val categoriesForForms: List<Category> get() = categories

    fun refresh() {
        viewModelScope.launch { refreshNow() }
    }

    /** [showLoading] is false for a reload that a sync or commit caused, so the spinner does not flash. */
    suspend fun refreshNow(showLoading: Boolean = true) {
        val generation = ++refreshGeneration
        _state.update { it.copy(isLoading = showLoading) }
        val search = _state.value.search.takeIf { it.isNotBlank() }
        val period = _state.value.budgetPeriod

        val balancesResult = repository.balances()
        val categoriesResult = repository.categories()
        val transactionsResult = repository.transactions(search, TRANSACTION_LIMIT)
        val budgetsResult = repository.budgetStatus(period)
        val billsResult = repository.bills()
        val snapshotsResult = repository.netWorthSnapshots()
        val conflictsResult = repository.conflicts()
        if (generation != refreshGeneration) return // a newer refresh is already running

        val failure = listOf(balancesResult, categoriesResult, transactionsResult, budgetsResult, billsResult, snapshotsResult, conflictsResult)
            .filterIsInstance<Outcome.Failed>().firstOrNull()?.error
        if (failure != null) {
            _state.update {
                it.copy(
                    isLoading = false,
                    hasLoaded = true,
                    isLocked = failure.kind == ErrorKind.Locked || failure.kind == ErrorKind.KeyLost,
                    error = failure.message,
                )
            }
            return
        }

        balances = (balancesResult as Outcome.Ok).value
        categories = (categoriesResult as Outcome.Ok).value
        val now = today()
        _state.update {
            it.copy(
                isLoading = false,
                hasLoaded = true,
                isLocked = false,
                error = null,
                accounts = balances.filter { b -> !b.archived }.map(::accountCard),
                netWorth = netWorthCard((snapshotsResult as Outcome.Ok).value.sortedBy { s -> s.asOf }.lastOrNull(), now),
                budgets = (budgetsResult as Outcome.Ok).value.map(::budgetRow),
                bills = (billsResult as Outcome.Ok).value.map { b -> billRow(b, now) },
                transactions = (transactionsResult as Outcome.Ok).value.map { t -> transactionRow(t, now) },
                conflicts = (conflictsResult as Outcome.Ok).value.map(::conflictRow),
            )
        }
    }

    fun onSearchChange(text: String) {
        _state.update { it.copy(search = text) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(searchDebounceMillis)
            searchNow()
        }
    }

    suspend fun searchNow() {
        val generation = ++searchGeneration
        val query = _state.value.search.takeIf { it.isNotBlank() }
        val result = repository.transactions(query, TRANSACTION_LIMIT)
        if (generation != searchGeneration) return
        when (result) {
            is Outcome.Ok -> {
                val now = today()
                _state.update { it.copy(transactions = result.value.map { t -> transactionRow(t, now) }) }
            }
            is Outcome.Failed -> _state.update { it.copy(error = result.error.message) }
        }
    }

    fun setBudgetPeriod(period: String) {
        if (period != THIS_MONTH && period != LAST_MONTH) return
        _state.update { it.copy(budgetPeriod = period) }
        viewModelScope.launch {
            val result = repository.budgetStatus(period)
            if (period != _state.value.budgetPeriod) return@launch
            when (result) {
                is Outcome.Ok -> _state.update { it.copy(budgets = result.value.map(::budgetRow)) }
                is Outcome.Failed -> _state.update { it.copy(error = result.error.message) }
            }
        }
    }

    fun takeSnapshot() {
        viewModelScope.launch {
            _state.update { it.copy(isBusy = true) }
            when (val result = repository.takeSnapshot()) {
                is Outcome.Ok -> refreshNow()
                is Outcome.Failed -> _state.update { it.copy(error = result.error.message) }
            }
            _state.update { it.copy(isBusy = false) }
        }
    }

    suspend fun export(format: String): Outcome<ByteArray> {
        _state.update { it.copy(isBusy = true) }
        try {
            return repository.export(format)
        } finally {
            _state.update { it.copy(isBusy = false) }
        }
    }

    /** Settle a disagreement: keep this phone's amount or the PC's. Both devices converge on the choice. */
    fun resolveConflict(id: Long, keepMine: Boolean) {
        viewModelScope.launch {
            _state.update { it.copy(isBusy = true) }
            when (val result = repository.resolveConflict(id, keepMine)) {
                is Outcome.Ok -> refreshNow()
                is Outcome.Failed -> _state.update { it.copy(error = result.error.message) }
            }
            _state.update { it.copy(isBusy = false) }
        }
    }

    fun clearError() = _state.update { it.copy(error = null) }

    // ---- row building (pure) -------------------------------------------------------------------

    private fun accountCard(b: AccountBalance): AccountCard {
        val balanceText = Money.format(b.balanceMinor, b.currency)
        val kind = Display.accountKindLabel(b.kind)
        return AccountCard(b.accountId, b.name, balanceText, "$kind · ${b.currency}", "${b.name}, $kind, balance $balanceText")
    }

    private fun conflictRow(c: Conflict): ConflictRow {
        val mine = Money.format(c.localMinor, c.currency)
        val pc = Money.format(c.remoteMinor, c.currency)
        return ConflictRow(c.id, c.label, mine, pc, "${c.label}: this phone says $mine, your PC says $pc")
    }

    private fun budgetRow(s: BudgetStatus): BudgetRow {
        val name = s.category ?: "Budget"
        val amounts = "${Money.format(s.spentMinor, s.currency)} / ${Money.format(s.budgetMinor, s.currency)}"
        val percent = Display.percent(s.usedBasisPoints)
        val a11y = if (s.overBudget) {
            "$name: $amounts, over budget by ${Money.format(-s.remainingMinor, s.currency)}"
        } else {
            "$name: $amounts, $percent percent used"
        }
        return BudgetRow(name, amounts, Display.barFraction(s.usedBasisPoints), Display.isNearLimit(s.usedBasisPoints), s.overBudget, a11y)
    }

    private fun billRow(b: Bill, now: LocalDate): BillRow {
        val amount = Money.format(b.amountMinor, b.currency)
        val due = Display.dueText(b, now)
        return BillRow(b.name, amount, due, (b.daysUntil ?: Int.MAX_VALUE) <= 7, "${b.name}, $amount, $due")
    }

    private fun transactionRow(t: Transaction, now: LocalDate): TransactionRow {
        val date = Display.relativeDate(t.date, now)
        val category = categories.firstOrNull { it.id == t.categoryId }?.name ?: "Uncategorized"
        val account = balances.firstOrNull { it.accountId == t.accountId }?.name ?: "Unknown account"
        val amount = Money.format(t.amountMinor, t.currency, showPlus = true)
        val source = Display.sourceText(t.sourceKind)
        return TransactionRow(
            t.id, date, t.description, category, account, amount, t.amountMinor > 0, source, t.sourceKind == "voice",
            "$date, ${t.description}, $category, $account, $amount, source $source",
        )
    }

    private fun netWorthCard(snapshot: NetWorthSnapshot?, now: LocalDate): NetWorthCard {
        if (snapshot == null || snapshot.byCurrency.isEmpty()) {
            return NetWorthCard(false, "No snapshot yet", "Take one to record today's net worth", "Net worth snapshot, none yet")
        }
        val value = snapshot.byCurrency.toSortedMap().entries.joinToString(" · ") { (code, e) -> Money.format(e.netMinor, code) }
        val caption = "Taken ${Display.shortDate(snapshot.asOf, now)}"
        return NetWorthCard(true, value, caption, "Net worth snapshot, $value, $caption")
    }

    companion object {
        const val THIS_MONTH = "this_month"
        const val LAST_MONTH = "last_month"
        const val TRANSACTION_LIMIT = 100
        const val NO_MONEY_MOVEMENT_NOTE =
            "REVA records and analyses money. It can't pay, transfer, buy or log in to a bank — those actions don't exist."
    }
}
