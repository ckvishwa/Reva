package app.reva.data

import org.json.JSONArray
import org.json.JSONObject

/** Kernel `recurring_summary` for one currency: exact yearly totals in minor units, never mixed across currencies. */
data class RecurringSummary(
    val currency: String,
    val yearlyOutgoingMinor: Long,
    val yearlyIncomeMinor: Long,
    val yearlyNetMinor: Long,
    val dueSoonOutgoingMinor: Long,
    val dueSoonIncomeMinor: Long,
    val dueUntil: String,
    val itemCount: Int,
)

/** One saved snapshot with each currency's net worth and its change since the previous snapshot (null for the first). */
data class NetWorthPoint(val asOf: String, val byCurrency: Map<String, Pair<Long, Long?>>)

/** Kernel `networth_report`: live net worth from current balances plus snapshot history. */
data class NetWorthReport(val asOf: String, val current: Map<String, NetWorthEntry>, val history: List<NetWorthPoint>)

object FinanceReportsJson {
    fun recurring(rowsJson: String): List<RecurringSummary> {
        val rows = JSONArray(rowsJson)
        return (0 until rows.length()).map { i ->
            val row = rows.getJSONObject(i)
            RecurringSummary(
                row.getString("currency"), row.getLong("yearly_outgoing_minor"), row.getLong("yearly_income_minor"),
                row.getLong("yearly_net_minor"), row.getLong("due_soon_outgoing_minor"), row.getLong("due_soon_income_minor"),
                row.getString("due_until"), row.getJSONArray("items").length(),
            )
        }
    }

    fun netWorth(rowsJson: String): NetWorthReport {
        val row = JSONArray(rowsJson).getJSONObject(0)
        val current = row.getJSONObject("current").let { by ->
            by.keys().asSequence().associateWith { code ->
                val e = by.getJSONObject(code)
                NetWorthEntry(e.getLong("assets_minor"), e.getLong("liabilities_minor"), e.getLong("net_minor"))
            }
        }
        val history = row.getJSONArray("history").let { list ->
            (0 until list.length()).map { i ->
                val point = list.getJSONObject(i)
                val by: JSONObject = point.getJSONObject("by_currency")
                NetWorthPoint(
                    point.getString("as_of"),
                    by.keys().asSequence().associateWith { code ->
                        val e = by.getJSONObject(code)
                        e.getLong("net_minor") to (if (e.isNull("change_minor")) null else e.getLong("change_minor"))
                    },
                )
            }
        }
        return NetWorthReport(row.getString("as_of"), current, history)
    }
}
