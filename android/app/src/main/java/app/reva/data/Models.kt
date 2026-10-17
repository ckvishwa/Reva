package app.reva.data

import org.json.JSONArray
import org.json.JSONObject

// Plain data holders for what the Finance Kernel returns. Field names are the Kernel's JSON keys, the same
// ones the Windows app reads from Core, so both apps show the same numbers.

data class AccountBalance(
    val accountId: String,
    val name: String,
    val kind: String,
    val currency: String,
    val archived: Boolean,
    val balanceMinor: Long,
)

data class Category(val id: String, val name: String, val kind: String, val aliases: List<String>)

data class Transaction(
    val id: String,
    val accountId: String,
    val date: String,
    val amountMinor: Long,
    val currency: String,
    val description: String,
    val categoryId: String?,
    val notes: String?,
    val source: String?,
    val sourceKind: String?,
)

data class BudgetStatus(
    val budgetId: String,
    val categoryId: String,
    val category: String?,
    val currency: String,
    val month: String,
    val budgetMinor: Long,
    val spentMinor: Long,
    val remainingMinor: Long,
    val usedBasisPoints: Long,
    val overBudget: Boolean,
)

data class Bill(
    val id: String,
    val name: String,
    val kind: String,
    val amountMinor: Long,
    val currency: String,
    val dueDate: String,
    val daysUntil: Int?,
    val overdue: Boolean?,
)

data class NetWorthEntry(val assetsMinor: Long, val liabilitiesMinor: Long, val netMinor: Long)

data class NetWorthSnapshot(val id: String, val asOf: String, val byCurrency: Map<String, NetWorthEntry>)

data class TodayBudgetLeft(val currency: String, val budgetMinor: Long, val spentMinor: Long, val remainingMinor: Long)

data class TodaySummary(val asOf: String, val budgetLeft: List<TodayBudgetLeft>, val billsDue: List<Bill>)

/** Exact minor-unit totals from the Kernel. A currency is never converted or combined with another. */
data class DailyCashflow(val currency: String, val incomeMinor: Long, val expenseMinor: Long, val netMinor: Long)

data class DailySpendCategory(
    val categoryId: String?, val category: String, val currency: String,
    val spentMinor: Long, val transactions: Long,
)

data class FinanceDailyAnalysis(
    val asOf: String,
    val cashflow: List<DailyCashflow>,
    val spending: List<DailySpendCategory>,
    val sourceIds: List<String>,
)

data class ImportRow(
    val row: Long,
    val status: String,
    val reason: String?,
    val date: String?,
    val amountMinor: Long?,
    val description: String?,
    val warning: String?,
    val raw: String?,
)

data class ImportReport(
    val accepted: Long,
    val duplicates: Long,
    val rejected: Long,
    val rows: List<ImportRow>,
    val dryRun: Boolean,
)

data class NewTransaction(
    val accountId: String,
    val date: String,
    val amountMinor: Long,
    val description: String,
    val category: String?,
    val notes: String?,
)

data class NewAccount(val name: String, val kind: String, val currency: String, val openingBalanceMinor: Long)

data class CsvMapping(
    val date: String,
    val dateFormat: String,
    val description: String,
    val amount: String?,
    val debit: String?,
    val credit: String?,
    val category: String?,
    val delimiter: String,
    val decimalSeparator: String,
    val invertSign: Boolean,
)

// ---- JSON parsing -------------------------------------------------------------------------------

private fun JSONObject.optStringOrNull(key: String): String? = if (isNull(key)) null else getString(key)

private fun JSONObject.optLongOrNull(key: String): Long? = if (isNull(key)) null else getLong(key)

private fun JSONObject.optIntOrNull(key: String): Int? = if (isNull(key)) null else getInt(key)

private fun JSONObject.optBoolOrNull(key: String): Boolean? = if (isNull(key)) null else getBoolean(key)

private inline fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> =
    (0 until length()).map { transform(getJSONObject(it)) }

/** A Finance amount the phone and the PC disagree about. Values are minor units; "local" is this phone's. */
data class Conflict(
    val id: Long,
    val label: String,
    val field: String,
    val currency: String,
    val localMinor: Long,
    val remoteMinor: Long,
)

object Json {
    fun dailyCashflow(rowsJson: String): List<DailyCashflow> = JSONArray(rowsJson).mapObjects {
        DailyCashflow(it.getString("currency"), it.getLong("income_minor"), it.getLong("expense_minor"), it.getLong("net_minor"))
    }

    fun dailySpending(rowsJson: String): List<DailySpendCategory> = JSONArray(rowsJson).mapObjects {
        DailySpendCategory(it.optStringOrNull("category_id"), it.getString("category"), it.getString("currency"),
            it.getLong("spent_minor"), it.getLong("transactions"))
    }

    fun conflicts(rowsJson: String): List<Conflict> = JSONArray(rowsJson).mapObjects {
        Conflict(
            it.getLong("id"),
            if (it.isNull("label")) "A record" else it.getString("label").ifBlank { "A record" },
            it.getString("field"),
            if (it.isNull("currency")) "USD" else it.getString("currency"),
            it.getString("local_value").toLong(),
            it.getString("remote_value").toLong(),
        )
    }

    fun accountBalances(rowsJson: String): List<AccountBalance> = JSONArray(rowsJson).mapObjects {
        AccountBalance(
            it.getString("account_id"), it.getString("name"), it.getString("kind"), it.getString("currency"),
            it.optBoolean("archived", false), it.getLong("balance_minor"),
        )
    }

    fun categories(rowsJson: String): List<Category> = JSONArray(rowsJson).mapObjects {
        Category(
            it.getString("id"), it.getString("name"), it.optString("kind", "expense"),
            it.optJSONArray("aliases")?.let { a -> (0 until a.length()).map(a::getString) } ?: emptyList(),
        )
    }

    fun transactions(rowsJson: String): List<Transaction> = JSONArray(rowsJson).mapObjects {
        Transaction(
            it.getString("id"), it.getString("account_id"), it.getString("date"), it.getLong("amount_minor"),
            it.getString("currency"), it.getString("description"), it.optStringOrNull("category_id"),
            it.optStringOrNull("notes"), it.optStringOrNull("source"), it.optStringOrNull("source_kind"),
        )
    }

    fun budgetStatus(rowsJson: String): List<BudgetStatus> = JSONArray(rowsJson).mapObjects {
        BudgetStatus(
            it.getString("budget_id"), it.getString("category_id"), it.optStringOrNull("category"), it.getString("currency"),
            it.getString("month"), it.getLong("budget_minor"), it.getLong("spent_minor"), it.getLong("remaining_minor"),
            it.getLong("used_basis_points"), it.getBoolean("over_budget"),
        )
    }

    fun bills(rowsJson: String): List<Bill> = JSONArray(rowsJson).mapObjects { bill(it) }

    private fun bill(it: JSONObject) = Bill(
        it.getString("id"), it.getString("name"), it.optString("kind", "bill"), it.getLong("amount_minor"),
        it.getString("currency"), it.getString("due_date"), it.optIntOrNull("days_until"), it.optBoolOrNull("overdue"),
    )

    fun snapshots(rowsJson: String): List<NetWorthSnapshot> = JSONArray(rowsJson).mapObjects {
        val byCurrency = it.getJSONObject("by_currency")
        NetWorthSnapshot(
            it.getString("id"), it.getString("as_of"),
            byCurrency.keys().asSequence().associateWith { code ->
                val entry = byCurrency.getJSONObject(code)
                NetWorthEntry(entry.getLong("assets_minor"), entry.getLong("liabilities_minor"), entry.getLong("net_minor"))
            },
        )
    }

    fun today(json: String): TodaySummary {
        val root = JSONObject(json)
        val finance = root.optJSONObject("domains")?.optJSONObject("finance")
        val left = finance?.optJSONArray("budget_left_this_month")?.mapObjects {
            TodayBudgetLeft(it.getString("currency"), it.getLong("budget_minor"), it.getLong("spent_minor"), it.getLong("remaining_minor"))
        } ?: emptyList()
        val bills = finance?.optJSONArray("bills_due_7_days")?.mapObjects { bill(it) } ?: emptyList()
        return TodaySummary(root.getString("as_of"), left, bills)
    }

    fun importRows(rowsJson: String): List<ImportRow> = JSONArray(rowsJson).mapObjects {
        ImportRow(
            it.getLong("row"), it.getString("status"), it.optStringOrNull("reason"), it.optStringOrNull("date"),
            it.optLongOrNull("amount_minor"), it.optStringOrNull("description"), it.optStringOrNull("warning"),
            it.optStringOrNull("raw"),
        )
    }
}
