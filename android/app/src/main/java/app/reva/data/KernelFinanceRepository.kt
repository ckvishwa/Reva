package app.reva.data

import java.time.LocalDate
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext
import org.json.JSONObject
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.KeyProviderException
import uniffi.reva_kernel.today as kernelToday

/**
 * The real [FinanceRepository]: every call goes to the Rust Domain Kernel through its UniFFI binding, on
 * [dispatcher] (Dispatchers.IO in the app), never on the main thread. The handle is opened on first use,
 * which is also when a fresh install creates its key and data file.
 */
class KernelFinanceRepository(
    private val openHandle: () -> DomainHandle,
    private val clock: () -> LocalDate = { LocalDate.now() },
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO,
) : FinanceRepository {

    private val handleLock = Any()
    private var handle: DomainHandle? = null
    private val counter = MutableStateFlow(0L)

    override val changes: StateFlow<Long> = counter.asStateFlow()

    override fun markChanged() = counter.update { it + 1 }

    private fun handle(): DomainHandle = synchronized(handleLock) { handle ?: openHandle().also { handle = it } }

    private suspend fun <T> run(block: (DomainHandle) -> T): Outcome<T> = withContext(dispatcher) {
        try {
            Outcome.Ok(block(handle()))
        } catch (e: DomainException) {
            Outcome.Failed(translate(e))
        } catch (e: KeyProviderException) {
            Outcome.Failed(FinanceError(ErrorKind.KeyLost, ErrorText.KEY_LOST, detail = e.message))
        }
    }

    /** A command that committed: tell open screens. A failed or refused command changes nothing. */
    private suspend fun <T> write(block: (DomainHandle) -> T): Outcome<T> =
        run(block).also { if (it is Outcome.Ok) markChanged() }

    private fun asOf(): String = clock().toString()

    private fun query(h: DomainHandle, name: String, params: JSONObject = JSONObject()): String =
        h.query(name, params.toString()).rowsJson

    override suspend fun balances() = run { Json.accountBalances(query(it, "account_balances", JSONObject().put("as_of", asOf()))) }

    override suspend fun categories() = run { Json.categories(query(it, "list_categories")) }

    override suspend fun transactions(query: String?, limit: Int) = run {
        val params = JSONObject().put("limit", limit)
        if (!query.isNullOrBlank()) params.put("q", query.trim())
        Json.transactions(query(it, "list_transactions", params))
    }

    override suspend fun budgetStatus(period: String) = run {
        Json.budgetStatus(query(it, "budget_status", JSONObject().put("month", period).put("as_of", asOf())))
    }

    override suspend fun bills() = run {
        Json.bills(query(it, "upcoming_bills", JSONObject().put("days", 366).put("as_of", asOf())))
    }

    override suspend fun netWorthSnapshots() = run { Json.snapshots(query(it, "list_networth_snapshots")) }

    override suspend fun today() = run { Json.today(kernelToday(listOf(it), asOf())) }

    override suspend fun conflicts() = run { Json.conflicts(query(it, "conflicts")) }

    override suspend fun resolveConflict(id: Long, keepMine: Boolean) = write {
        it.command("conflict.resolve", JSONObject().put("conflict_id", id).put("keep", if (keepMine) "local" else "remote").toString())
        Unit
    }

    /** The open Finance handle, for the sync engine (same file, same lock). Call off the main thread. */
    fun kernelHandle(): DomainHandle = handle()

    override suspend fun addTransaction(request: NewTransaction) = write {
        val body = JSONObject()
            .put("account_id", request.accountId)
            .put("date", request.date)
            .put("amount_minor", request.amountMinor)
            .put("description", request.description)
            .put("source", "manual")
        request.category?.let { body.put("category", it) }
        request.notes?.let { body.put("notes", it) }
        it.command("transaction.create", body.toString())
        Unit
    }

    override suspend fun addAccount(request: NewAccount) = write {
        val body = JSONObject()
            .put("name", request.name)
            .put("kind", request.kind)
            .put("currency", request.currency)
            .put("opening_balance_minor", request.openingBalanceMinor)
        it.command("account.create", body.toString())
        Unit
    }

    override suspend fun takeSnapshot() = write {
        it.command("networth_snapshot.create", JSONObject().put("as_of", asOf()).toString())
        Unit
    }

    override suspend fun import(
        format: String,
        data: ByteArray,
        accountId: String?,
        mapping: CsvMapping?,
        dryRun: Boolean,
    ) = run {
        val options = JSONObject().put("dry_run", dryRun)
        accountId?.let { options.put("account_id", it) }
        if (mapping != null) {
            val map = JSONObject()
                .put("date", mapping.date)
                .put("date_format", mapping.dateFormat)
                .put("description", mapping.description)
                .put("delimiter", mapping.delimiter)
                .put("decimal_separator", mapping.decimalSeparator)
                .put("invert_sign", mapping.invertSign)
            mapping.amount?.let { v -> map.put("amount", v) }
            mapping.debit?.let { v -> map.put("debit", v) }
            mapping.credit?.let { v -> map.put("credit", v) }
            mapping.category?.let { v -> map.put("category", v) }
            options.put("mapping", map)
        }
        val report = it.importData(format, data, options.toString())
        ImportReport(
            accepted = report.accepted.toLong(),
            duplicates = report.duplicates.toLong(),
            rejected = report.rejected.size.toLong(),
            rows = Json.importRows(report.rowsJson),
            dryRun = report.dryRun,
        )
    }.also { if (!dryRun && it is Outcome.Ok && it.value.accepted > 0) markChanged() }

    override suspend fun export(format: String) = run { it.export(format) }

    companion object {
        fun translate(e: DomainException): FinanceError = when (e) {
            is DomainException.Locked -> FinanceError(ErrorKind.Locked, ErrorText.LOCKED)
            is DomainException.WrongKey -> FinanceError(ErrorKind.KeyLost, ErrorText.KEY_LOST)
            is DomainException.Corrupt -> FinanceError(ErrorKind.Corrupt, ErrorText.CORRUPT)
            is DomainException.Validation -> FinanceError(ErrorKind.Validation, "${e.field}: ${e.reason}", e.field, e.reason)
            is DomainException.Conflict -> FinanceError(ErrorKind.Conflict, e.message ?: "That conflicts with existing data.")
            is DomainException.NotFound -> FinanceError(ErrorKind.NotFound, "That record no longer exists.")
            is DomainException.Deleted -> FinanceError(ErrorKind.Deleted, "That record was deleted.")
            else -> FinanceError(ErrorKind.Internal, ErrorText.INTERNAL)
        }
    }
}
