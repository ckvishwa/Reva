package app.reva.data

import kotlinx.coroutines.flow.StateFlow

enum class ErrorKind { Locked, KeyLost, Corrupt, Validation, Conflict, NotFound, Deleted, Internal }

/** Why a Finance call failed, in words that are safe to show: never SQL, paths or key material. */
data class FinanceError(val kind: ErrorKind, val message: String, val field: String? = null, val detail: String? = null)

sealed interface Outcome<out T> {
    data class Ok<T>(val value: T) : Outcome<T>
    data class Failed(val error: FinanceError) : Outcome<Nothing>
}

val <T> Outcome<T>.valueOrNull: T? get() = (this as? Outcome.Ok)?.value

/**
 * Everything the screens need from the Finance Kernel. Calls are suspend functions: the real
 * implementation runs them on Dispatchers.IO, so no screen ever waits on the Kernel on the main thread
 * (AR-DOM-015). Tests use a fake.
 */
interface FinanceRepository {
    /**
     * Counts committed changes: every local write and every sync batch that applied events. A screen that
     * is already open collects this and reloads when it moves, so it never waits for a tab switch (SYNC-1e).
     * It holds no data.
     */
    val changes: StateFlow<Long>

    /** The sync client calls this after a batch applied events from the PC. */
    fun markChanged()

    suspend fun balances(): Outcome<List<AccountBalance>>

    suspend fun categories(): Outcome<List<Category>>

    suspend fun transactions(query: String?, limit: Int): Outcome<List<Transaction>>

    /** [period] is "this_month" or "last_month". */
    suspend fun budgetStatus(period: String): Outcome<List<BudgetStatus>>

    suspend fun bills(): Outcome<List<Bill>>

    suspend fun netWorthSnapshots(): Outcome<List<NetWorthSnapshot>>

    /** Kernel yearly totals of active recurring bills, subscriptions and income, per currency, as of [asOf]. */
    suspend fun recurringSummary(asOf: String): Outcome<List<RecurringSummary>> =
        Outcome.Failed(FinanceError(ErrorKind.Validation, "Recurring summary is unavailable."))

    /** Kernel net worth from live balances as of [asOf], plus every snapshot with its change. */
    suspend fun netWorthReport(asOf: String): Outcome<NetWorthReport> =
        Outcome.Failed(FinanceError(ErrorKind.Validation, "Net worth report is unavailable."))

    suspend fun today(): Outcome<TodaySummary>

    /** Exact day totals and their contributing transaction IDs, computed by the local Kernel. */
    suspend fun dailyAnalysis(asOf: String): Outcome<FinanceDailyAnalysis>

    /** Exact Kernel totals for a reviewed period, with contributing transaction IDs. */
    suspend fun periodAnalysis(period: String, asOf: String): Outcome<FinancePeriodAnalysis>

    /** Amounts this phone and the PC disagree about, not yet resolved. */
    suspend fun conflicts(): Outcome<List<Conflict>>

    /** Settles a conflict by writing a new event with the chosen amount; every paired device then agrees. */
    suspend fun resolveConflict(id: Long, keepMine: Boolean): Outcome<Unit>

    suspend fun addTransaction(request: NewTransaction): Outcome<Unit>

    suspend fun addAccount(request: NewAccount): Outcome<Unit>

    suspend fun addCategory(name: String): Outcome<Unit>

    suspend fun setBudget(request: NewBudget): Outcome<Unit>

    suspend fun addBill(request: NewBill): Outcome<Unit>

    /** Records a user-reported payment; it does not transfer money or write a bank transaction. */
    suspend fun markBillPaid(id: String, paidDate: String): Outcome<Unit>

    suspend fun takeSnapshot(): Outcome<Unit>

    suspend fun import(
        format: String,
        data: ByteArray,
        accountId: String?,
        mapping: CsvMapping?,
        dryRun: Boolean,
    ): Outcome<ImportReport>

    /** [format] is "csv" or "json". */
    suspend fun export(format: String): Outcome<ByteArray>
}

/** Shown when a Finance file or its key cannot be opened. */
object ErrorText {
    const val LOCKED = "Finance is locked: this phone has no key that opens the Finance data."
    const val KEY_LOST =
        "The Finance key on this phone no longer opens the data (the lock screen or security settings may have changed). " +
            "Nothing was deleted."
    const val CORRUPT = "The Finance file is damaged. REVA did not change it."
    const val INTERNAL = "REVA hit an internal error. Nothing was changed."
}
