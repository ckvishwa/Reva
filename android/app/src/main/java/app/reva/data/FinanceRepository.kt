package app.reva.data

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
    suspend fun balances(): Outcome<List<AccountBalance>>

    suspend fun categories(): Outcome<List<Category>>

    suspend fun transactions(query: String?, limit: Int): Outcome<List<Transaction>>

    /** [period] is "this_month" or "last_month". */
    suspend fun budgetStatus(period: String): Outcome<List<BudgetStatus>>

    suspend fun bills(): Outcome<List<Bill>>

    suspend fun netWorthSnapshots(): Outcome<List<NetWorthSnapshot>>

    suspend fun today(): Outcome<TodaySummary>

    suspend fun addTransaction(request: NewTransaction): Outcome<Unit>

    suspend fun addAccount(request: NewAccount): Outcome<Unit>

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
