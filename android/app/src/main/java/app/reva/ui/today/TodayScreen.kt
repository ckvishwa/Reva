package app.reva.ui.today

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.RevaCard
import app.reva.ui.UsageBar
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaText

/** Today: budget left this month and the bills due in the next 7 days. */
@Composable
fun TodayScreen(vm: TodayViewModel, modifier: Modifier = Modifier, syncStatus: String? = null) {
    val state by vm.state.collectAsState()
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Today", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() })
        }
        syncStatus?.let { text -> item { CaptionText(text, Modifier.testTag("sync_status")) } }
        item {
            RevaCard(radius = 14.dp, modifier = Modifier.testTag("today_card").semantics(mergeDescendants = true) { contentDescription = state.accessibleSummary }) {
                CaptionText("Today · Finance")
                Text(state.budgetLeftText, style = RevaText.Number, color = RevaColors.Text, modifier = Modifier.testTag("today_budget_left"))
                if (state.budgetOfText.isNotEmpty()) CaptionText(state.budgetOfText)
                if (state.hasBudget) UsageBar(state.budgetFraction, state.budgetNearLimit)
                if (state.otherCurrenciesText.isNotEmpty()) CaptionText(state.otherCurrenciesText)
                if (state.billsText.isNotEmpty()) {
                    Text(state.billsText, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.testTag("today_bills"))
                }
                state.error?.let { ErrorText(it) }
            }
        }
        item {
            RevaCard(radius = 14.dp, modifier = Modifier.testTag("daily_finance_card")) {
                CaptionText("Daily Finance · exact records")
                if (state.dailyRows.isEmpty() && state.dailyError == null) CaptionText("No transactions recorded today")
                state.dailyRows.forEach { row ->
                    Text("${row.currency} · In ${row.incomeText} · Out ${row.expenseText} · Net ${row.netText}",
                        style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text)
                }
                if (state.topSpendingText.isNotEmpty()) CaptionText("Top category · ${state.topSpendingText}")
                if (state.dailyError == null) CaptionText("${state.dailySourceCount} source records")
                state.dailyError?.let { ErrorText(it) }
            }
        }
    }
}
