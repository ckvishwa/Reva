package app.reva.testing

import app.reva.data.AccountBalance
import app.reva.data.Bill
import app.reva.data.BudgetStatus
import app.reva.data.Category
import app.reva.data.CsvMapping
import app.reva.data.FinanceError
import app.reva.data.FinanceRepository
import app.reva.data.ImportReport
import app.reva.data.NetWorthSnapshot
import app.reva.data.NewAccount
import app.reva.data.NewTransaction
import app.reva.data.Outcome
import app.reva.data.TodaySummary
import app.reva.data.Transaction
import kotlinx.coroutines.CompletableDeferred

data class ImportCall(
    val format: String,
    val accountId: String?,
    val mapping: CsvMapping?,
    val dryRun: Boolean,
    val size: Int,
)

/**
 * An in-memory [FinanceRepository] for unit and Compose tests. It is not the Kernel: it only keeps the
 * numbers the screens show consistent (a new transaction moves its account's balance) and records what
 * it was asked to do. Real Kernel behaviour is tested through the Kernel itself (instrumented suite).
 */
class FakeFinanceRepository : FinanceRepository {
    var balances = mutableListOf<AccountBalance>()
    var categories = mutableListOf<Category>()
    var transactions = mutableListOf<Transaction>()
    var budgets = mutableListOf<BudgetStatus>()
    var bills = mutableListOf<Bill>()
    var snapshots = mutableListOf<NetWorthSnapshot>()
    var todaySummary = TodaySummary("2026-10-12", emptyList(), emptyList())
    var importResponder: (Boolean) -> ImportReport = { dry -> ImportReport(0, 0, 0, emptyList(), dry) }

    /** Method name -> error to return instead of doing the work (names are the function names). */
    val failures = mutableMapOf<String, FinanceError>()

    /** When set, every call waits for it before returning, which lets a test prove the caller is not blocked. */
    var gate: CompletableDeferred<Unit>? = null

    val calls = mutableListOf<String>()
    val addedTransactions = mutableListOf<NewTransaction>()
    val addedAccounts = mutableListOf<NewAccount>()
    val imports = mutableListOf<ImportCall>()
    var exportBytes = byteArrayOf(1, 2, 3)

    private suspend fun <T> call(name: String, tag: String = name, work: () -> T): Outcome<T> {
        calls += tag
        failures[name]?.let { return Outcome.Failed(it) }
        val result = work() // answered from the data as it is now, then held back by the gate
        gate?.await()
        return Outcome.Ok(result)
    }

    override suspend fun balances() = call("balances") { balances.toList() }

    override suspend fun categories() = call("categories") { categories.toList() }

    override suspend fun transactions(query: String?, limit: Int) = call("transactions", "transactions:q=${query ?: ""}") {
        val q = query?.trim()?.lowercase()
        transactions.filter { q.isNullOrEmpty() || it.description.lowercase().contains(q) }.take(limit)
    }

    override suspend fun budgetStatus(period: String) = call("budgetStatus", "budgetStatus:$period") { budgets.toList() }

    override suspend fun bills() = call("bills") { bills.toList() }

    override suspend fun netWorthSnapshots() = call("netWorthSnapshots") { snapshots.toList() }

    override suspend fun today() = call("today") { todaySummary }

    override suspend fun addTransaction(request: NewTransaction) = call("addTransaction") {
        addedTransactions += request
        val account = balances.first { it.accountId == request.accountId }
        transactions.add(
            0,
            Transaction(
                "tx-${transactions.size + 1}", request.accountId, request.date, request.amountMinor, account.currency,
                request.description, null, request.notes, "manual", "manual",
            ),
        )
        balances[balances.indexOf(account)] = account.copy(balanceMinor = account.balanceMinor + request.amountMinor)
    }

    override suspend fun addAccount(request: NewAccount) = call("addAccount") {
        addedAccounts += request
        balances += AccountBalance(
            "acct-${balances.size + 1}", request.name, request.kind, request.currency, false, request.openingBalanceMinor,
        )
    }

    override suspend fun takeSnapshot() = call("takeSnapshot") { Unit }

    override suspend fun import(format: String, data: ByteArray, accountId: String?, mapping: CsvMapping?, dryRun: Boolean) =
        call("import", "import:${if (dryRun) "dry" else "real"}") {
            imports += ImportCall(format, accountId, mapping, dryRun, data.size)
            importResponder(dryRun)
        }

    override suspend fun export(format: String) = call("export", "export:$format") { exportBytes }
}

object Samples {
    fun checking(balance: Long = 650_000) = AccountBalance("acct-checking", "Checking", "checking", "USD", false, balance)

    fun card(balance: Long = -22_849) = AccountBalance("acct-card", "Credit card", "credit", "USD", false, balance)

    fun dining() = Category("cat-dining", "Food · Dining", "expense", listOf("lunch"))

    fun groceries() = Category("cat-groceries", "Groceries", "expense", emptyList())

    fun transaction(
        id: String,
        date: String,
        amount: Long,
        description: String,
        account: String = "acct-card",
        category: String? = "cat-dining",
        sourceKind: String = "manual",
    ) = Transaction(id, account, date, amount, "USD", description, category, null, sourceKind, sourceKind)

    fun budget(name: String, budget: Long, spent: Long, over: Boolean = false) = BudgetStatus(
        "bud-$name", "cat-$name", name, "USD", "2026-10", budget, spent, budget - spent,
        if (budget > 0) spent * 10_000 / budget else 0, over,
    )

    fun bill(name: String, due: String, days: Int, kind: String = "bill", overdue: Boolean = false) =
        Bill("bill-$name", name, kind, 4_500, "USD", due, days, overdue)

    fun populated() = FakeFinanceRepository().apply {
        balances = mutableListOf(checking(), card())
        categories = mutableListOf(dining(), groceries())
        transactions = mutableListOf(
            transaction("t1", "2026-10-12", -1_200, "Lunch", sourceKind = "voice"),
            transaction("t2", "2026-10-11", -8_450, "Market", category = "cat-groceries"),
            transaction("t3", "2026-10-01", 300_000, "Paycheck", account = "acct-checking", category = null),
        )
        budgets = mutableListOf(budget("dining", 40_000, 36_500), budget("groceries", 60_000, 8_450))
        bills = mutableListOf(bill("Rent", "2026-10-14", 2), bill("Phone", "2026-10-18", 6))
    }
}
