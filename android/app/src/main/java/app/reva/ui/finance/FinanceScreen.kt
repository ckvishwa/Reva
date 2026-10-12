@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package app.reva.ui.finance

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.MoneyText
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import app.reva.ui.UsageBar
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaText

/**
 * The Finance tab. All data comes from [FinanceViewModel]; this composable only draws it and forwards taps,
 * so nothing here talks to the Kernel or waits on it.
 */
@Composable
fun FinanceScreen(
    vm: FinanceViewModel,
    onAddTransaction: () -> Unit,
    onAddAccount: () -> Unit,
    onImport: () -> Unit,
    onExport: (format: String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val state by vm.state.collectAsState()
    LazyColumn(
        modifier = modifier.fillMaxSize().testTag("finance_list"),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Column {
                CaptionText("Encrypted on this phone · stays on this device until you pair a PC")
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(
                        "Finance",
                        style = MaterialTheme.typography.headlineMedium,
                        color = RevaColors.Text,
                        modifier = Modifier.semantics { heading() },
                    )
                    if (state.isLoading) {
                        CircularProgressIndicator(
                            Modifier.size(20.dp).semantics { contentDescription = "Loading Finance" },
                            color = RevaColors.Accent,
                            strokeWidth = 2.dp,
                        )
                    }
                }
            }
        }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PrimaryButton("Add transaction", onAddTransaction, Modifier.testTag("add_transaction"), enabled = state.hasAccounts)
                SecondaryButton("Add account", onAddAccount, Modifier.testTag("add_account"), enabled = !state.isLocked)
                SecondaryButton("Import", onImport, Modifier.testTag("import"), enabled = state.hasAccounts)
                ExportMenu(enabled = !state.isLocked && !state.isBusy, onExport = onExport)
            }
        }
        item {
            RevaCard(radius = 12.dp, padding = 14.dp, borderColor = RevaColors.Outline) {
                Text(
                    FinanceViewModel.NO_MONEY_MOVEMENT_NOTE,
                    style = MaterialTheme.typography.bodyMedium,
                    color = RevaColors.Secondary,
                    modifier = Modifier.testTag("no_money_note"),
                )
            }
        }
        state.error?.let { message ->
            item {
                RevaCard(radius = 14.dp, borderColor = RevaColors.Error) {
                    ErrorText(message, Modifier.testTag("finance_error"))
                    SecondaryButton("Try again", vm::refresh)
                }
            }
        }
        if (state.showEmptyState) {
            item {
                RevaCard(Modifier.testTag("finance_empty")) {
                    SectionTitle("No accounts yet")
                    MutedText("Add an account to start tracking. You can also import a bank CSV or OFX file, or restore a REVA JSON export.")
                    PrimaryButton("Add account", onAddAccount, Modifier.testTag("empty_add_account"))
                }
            }
        }
        items(state.accounts, key = { it.accountId }) { card ->
            RevaCard(radius = 14.dp, modifier = Modifier.semantics(mergeDescendants = true) { contentDescription = card.a11y }) {
                MutedText(card.title)
                Text(card.balanceText, style = RevaText.Number, color = RevaColors.Text)
                CaptionText(card.caption)
            }
        }
        if (state.hasAccounts) {
            item {
                RevaCard(radius = 14.dp, modifier = Modifier.semantics(mergeDescendants = true) { contentDescription = state.netWorth.a11y }) {
                    MutedText("Net worth snapshot")
                    Text(
                        state.netWorth.valueText,
                        style = if (state.netWorth.hasSnapshot) RevaText.Number else MaterialTheme.typography.titleMedium,
                        color = RevaColors.Text,
                    )
                    CaptionText(state.netWorth.caption)
                }
            }
            item { SecondaryButton("Take net worth snapshot", vm::takeSnapshot, enabled = !state.isBusy) }
        }
        item { BudgetsCard(state, vm::setBudgetPeriod) }
        item { BillsCard(state) }
        item { TransactionsCard(state, vm::onSearchChange) }
        item {
            Column {
                Text(
                    "Finance stays on this phone. There is no internet permission in this build, so nothing can leave it.",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.Muted,
                )
            }
        }
    }
}

@Composable
private fun ExportMenu(enabled: Boolean, onExport: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column {
        SecondaryButton("Export", { open = true }, Modifier.testTag("export"), enabled = enabled)
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text("Transactions (CSV)") },
                onClick = {
                    open = false
                    onExport("csv")
                },
                modifier = Modifier.testTag("export_csv"),
            )
            DropdownMenuItem(
                text = { Text("Everything (JSON backup)") },
                onClick = {
                    open = false
                    onExport("json")
                },
                modifier = Modifier.testTag("export_json"),
            )
        }
    }
}

@Composable
private fun BudgetsCard(state: FinanceUiState, onPeriod: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val thisMonth = state.budgetPeriod == FinanceViewModel.THIS_MONTH
    RevaCard(modifier = Modifier.semantics { contentDescription = "Budgets" }) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                if (thisMonth) "Budgets · this month" else "Budgets · last month",
                style = MaterialTheme.typography.titleMedium,
                color = RevaColors.Text,
                modifier = Modifier.weight(1f).semantics { heading() },
            )
            Column {
                SecondaryButton(if (thisMonth) "This month ▾" else "Last month ▾", { open = true }, Modifier.testTag("budget_period"))
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    DropdownMenuItem(text = { Text("This month") }, onClick = { open = false; onPeriod(FinanceViewModel.THIS_MONTH) })
                    DropdownMenuItem(text = { Text("Last month") }, onClick = { open = false; onPeriod(FinanceViewModel.LAST_MONTH) })
                }
            }
        }
        if (state.budgets.isEmpty()) MutedText("No budgets for this period.")
        state.budgets.forEach { row ->
            Column(
                Modifier.fillMaxWidth().padding(top = 6.dp).semantics(mergeDescendants = true) { contentDescription = row.a11y },
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(row.name, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.weight(1f))
                    MoneyText(row.amountsText)
                }
                UsageBar(row.fraction, row.isNearLimit)
            }
        }
        CaptionText("Bars over 90% turn light orange.")
    }
}

@Composable
private fun BillsCard(state: FinanceUiState) {
    RevaCard(modifier = Modifier.semantics { contentDescription = "Bills and recurring" }) {
        Text("Bills & recurring", style = MaterialTheme.typography.titleMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() })
        if (state.bills.isEmpty()) MutedText("No bills or recurring items yet.")
        state.bills.forEach { bill ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = 36.dp).semantics(mergeDescendants = true) { contentDescription = bill.a11y },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(bill.name, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.weight(1f))
                MoneyText(bill.amountText)
                Text(
                    bill.dueText,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (bill.isSoon) RevaColors.Accent else RevaColors.Muted,
                )
            }
        }
        CaptionText("Reminders are created with your approval and appear in Today.")
    }
}

@Composable
private fun TransactionsCard(state: FinanceUiState, onSearch: (String) -> Unit) {
    RevaCard(modifier = Modifier.semantics { contentDescription = "Transactions" }) {
        Text("Recent transactions", style = MaterialTheme.typography.titleMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() })
        OutlinedTextField(
            value = state.search,
            onValueChange = onSearch,
            placeholder = { Text("Search merchant, category, note", color = RevaColors.Muted) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            shape = androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
            colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                focusedBorderColor = RevaColors.Accent,
                unfocusedBorderColor = RevaColors.Outline,
                focusedContainerColor = RevaColors.Input,
                unfocusedContainerColor = RevaColors.Input,
                cursorColor = RevaColors.Accent,
            ),
            modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag("search").semantics { contentDescription = "Search transactions" },
        )
        if (state.transactions.isEmpty()) MutedText(state.transactionsEmptyText, Modifier.testTag("transactions_empty"))
        state.transactions.forEachIndexed { index, row ->
            if (index > 0) HorizontalDivider(color = RevaColors.Border)
            Column(
                Modifier.fillMaxWidth().padding(vertical = 8.dp).testTag("transaction_row")
                    .semantics(mergeDescendants = true) { contentDescription = row.a11y },
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(row.description, style = MaterialTheme.typography.bodyLarge, color = RevaColors.Text, modifier = Modifier.weight(1f))
                    MoneyText(row.amountText, color = if (row.isIncome) RevaColors.Success else RevaColors.Text)
                }
                CaptionText("${row.dateText} · ${row.categoryText} · ${row.accountText}")
                Text(
                    row.sourceText,
                    style = RevaText.Small,
                    color = if (row.isVoice) RevaColors.Success else RevaColors.Muted,
                )
            }
        }
    }
}
