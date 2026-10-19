package app.reva.ui.finance

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import app.reva.data.Bill
import app.reva.data.BudgetStatus
import app.reva.data.Category
import app.reva.data.EntryResult
import app.reva.data.FinanceEntry
import app.reva.data.FinanceRepository
import app.reva.data.Outcome
import app.reva.core.Money
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.RevaCard
import java.time.LocalDate
import java.time.YearMonth
import kotlinx.coroutines.launch

/** Human-confirmed Finance writes. The Rust Kernel validates again and is the source of totals. */
@Composable
fun FinanceManageForm(repository: FinanceRepository, modifier: Modifier = Modifier) {
    var categories by remember { mutableStateOf<List<Category>>(emptyList()) }
    var budgets by remember { mutableStateOf<List<BudgetStatus>>(emptyList()) }
    var bills by remember { mutableStateOf<List<Bill>>(emptyList()) }
    var pendingPaid by remember { mutableStateOf<Bill?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var categoryName by rememberSaveable { mutableStateOf("") }
    var categoryId by rememberSaveable { mutableStateOf("") }
    var budgetCurrency by rememberSaveable { mutableStateOf("USD") }
    var budgetAmount by rememberSaveable { mutableStateOf("") }
    var budgetMonth by rememberSaveable { mutableStateOf(YearMonth.now().toString()) }
    var billName by rememberSaveable { mutableStateOf("") }
    var billAmount by rememberSaveable { mutableStateOf("") }
    var billCurrency by rememberSaveable { mutableStateOf("USD") }
    var billDue by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var recurrence by rememberSaveable { mutableStateOf("monthly") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(repository, refresh) {
        when (val result = repository.categories()) {
            is Outcome.Ok -> categories = result.value.filter { it.kind == "expense" }
            is Outcome.Failed -> error = result.error.message
        }
        when (val result = repository.budgetStatus("this_month")) {
            is Outcome.Ok -> budgets = result.value
            is Outcome.Failed -> error = result.error.message
        }
        when (val result = repository.bills()) {
            is Outcome.Ok -> bills = result.value
            is Outcome.Failed -> error = result.error.message
        }
    }

    fun save(work: suspend () -> Outcome<Unit>, onSaved: () -> Unit = {}) {
        scope.launch {
            when (val result = work()) {
                is Outcome.Ok -> { error = null; onSaved(); refresh++ }
                is Outcome.Failed -> error = result.error.message
            }
        }
    }

    LazyColumn(modifier.testTag("finance_manage"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Manage Finance") }
        item { CaptionText("All amounts are exact in their own currency. Recording a bill as paid does not send a payment.") }
        if (error != null) item { ErrorText(error!!) }
        item {
            RevaCard {
                CaptionText("Expense category")
                OutlinedTextField(categoryName, { categoryName = it }, label = { Text("New category name") }, modifier = Modifier.testTag("finance_category_name"))
                Button(onClick = {
                    if (categoryName.isBlank()) error = "Enter a category name."
                    else save({ repository.addCategory(categoryName.trim()) }) { categoryName = "" }
                }, modifier = Modifier.testTag("finance_category_save")) { Text("Add category") }
            }
        }
        item {
            RevaCard {
                CaptionText("Monthly budget")
                if (categories.isEmpty()) CaptionText("Add an expense category first")
                categories.forEach { category ->
                    Button(onClick = { categoryId = category.id }, modifier = Modifier.testTag("finance_budget_category_${category.id}")) {
                        Text(if (category.id == categoryId) "✓ ${category.name}" else category.name)
                    }
                }
                OutlinedTextField(budgetCurrency, { budgetCurrency = it }, label = { Text("Currency code") })
                OutlinedTextField(budgetAmount, { budgetAmount = it }, label = { Text("Budget amount") }, modifier = Modifier.testTag("finance_budget_amount"))
                OutlinedTextField(budgetMonth, { budgetMonth = it }, label = { Text("Start month YYYY-MM") })
                Button(onClick = {
                    when (val parsed = FinanceEntry.budget(categoryId, budgetCurrency, budgetAmount, budgetMonth, categories)) {
                        is EntryResult.Invalid -> error = parsed.message
                        is EntryResult.Ok -> save({ repository.setBudget(parsed.value) }) { budgetAmount = "" }
                    }
                }, modifier = Modifier.testTag("finance_budget_save")) { Text("Set budget") }
                budgets.forEach { budget -> CaptionText("${budget.category ?: "Budget"} · ${Money.format(budget.spentMinor, budget.currency)} of ${Money.format(budget.budgetMinor, budget.currency)} used") }
            }
        }
        item {
            RevaCard {
                CaptionText("Bill or recurring payment reminder")
                OutlinedTextField(billName, { billName = it }, label = { Text("Bill name") }, modifier = Modifier.testTag("finance_bill_name"))
                OutlinedTextField(billAmount, { billAmount = it }, label = { Text("Amount due") }, modifier = Modifier.testTag("finance_bill_amount"))
                OutlinedTextField(billCurrency, { billCurrency = it }, label = { Text("Currency code") })
                OutlinedTextField(billDue, { billDue = it }, label = { Text("Due date YYYY-MM-DD") })
                listOf("once", "weekly", "biweekly", "monthly", "quarterly", "yearly").forEach { option ->
                    Button(onClick = { recurrence = option }) { Text(if (recurrence == option) "✓ $option" else option) }
                }
                Button(onClick = {
                    when (val parsed = FinanceEntry.bill(billName, billAmount, billCurrency, billDue, recurrence)) {
                        is EntryResult.Invalid -> error = parsed.message
                        is EntryResult.Ok -> save({ repository.addBill(parsed.value) }) { billName = ""; billAmount = "" }
                    }
                }, modifier = Modifier.testTag("finance_bill_save")) { Text("Save bill") }
                bills.forEach { bill ->
                    Text("${bill.name} · ${Money.format(bill.amountMinor, bill.currency)} · due ${bill.dueDate}")
                    Button(onClick = { pendingPaid = bill },
                        modifier = Modifier.testTag("finance_bill_paid_${bill.id}")) { Text("Record as paid (no payment sent)") }
                }
            }
        }
    }
    pendingPaid?.let { bill ->
        AlertDialog(
            onDismissRequest = { pendingPaid = null },
            title = { Text("Record ${bill.name} as paid?") },
            text = { Text("This only updates your REVA record. It does not send money or contact a bank.") },
            confirmButton = { TextButton(onClick = {
                pendingPaid = null
                save({ repository.markBillPaid(bill.id, LocalDate.now().toString()) })
            }) { Text("Confirm record as paid") } },
            dismissButton = { TextButton(onClick = { pendingPaid = null }) { Text("Cancel") } },
        )
    }
}
