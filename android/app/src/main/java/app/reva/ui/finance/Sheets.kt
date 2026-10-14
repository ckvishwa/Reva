@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class, androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package app.reva.ui.finance

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import app.reva.ui.theme.RevaColors
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import kotlinx.coroutines.launch

@Composable
private fun fieldColors() = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
    focusedBorderColor = RevaColors.Accent,
    unfocusedBorderColor = RevaColors.Outline,
    focusedContainerColor = RevaColors.Input,
    unfocusedContainerColor = RevaColors.Input,
    errorBorderColor = RevaColors.Error,
    errorContainerColor = RevaColors.Input,
    focusedLabelColor = RevaColors.Accent,
    unfocusedLabelColor = RevaColors.Muted,
    cursorColor = RevaColors.Accent,
)

@Composable
internal fun LabeledField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    error: String?,
    tag: String,
    modifier: Modifier = Modifier,
    keyboardType: KeyboardType = KeyboardType.Text,
    placeholder: String? = null,
    singleLine: Boolean = true,
) {
    Column(modifier) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            label = { Text(label) },
            placeholder = placeholder?.let { { Text(it, color = RevaColors.Muted) } },
            isError = error != null,
            singleLine = singleLine,
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = keyboardType),
            shape = androidx.compose.foundation.shape.RoundedCornerShape(8.dp),
            colors = fieldColors(),
            modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag(tag),
        )
        if (error != null) ErrorText(error, Modifier.padding(start = 4.dp, top = 2.dp))
    }
}

/** A drop-down choice. Shows the current choice on a button; tapping opens a menu. */
@Composable
internal fun <T> ChoiceField(
    label: String,
    selectedText: String,
    options: List<T>,
    optionText: (T) -> String,
    onSelect: (T) -> Unit,
    tag: String,
    modifier: Modifier = Modifier,
    error: String? = null,
) {
    var open by remember { mutableStateOf(false) }
    Column(modifier) {
        CaptionText(label)
        SecondaryButton(
            text = "$selectedText  ▾",
            onClick = { open = true },
            modifier = Modifier.fillMaxWidth().testTag(tag).semantics { contentDescription = "$label: $selectedText" },
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(optionText(option)) },
                    onClick = {
                        open = false
                        onSelect(option)
                    },
                    modifier = Modifier.testTag("$tag:${optionText(option)}"),
                )
            }
        }
        if (error != null) ErrorText(error)
    }
}

@Composable
internal fun DateField(date: LocalDate, onDate: (LocalDate) -> Unit, error: String?, modifier: Modifier = Modifier) {
    var open by remember { mutableStateOf(false) }
    Column(modifier) {
        CaptionText("Date")
        SecondaryButton(
            text = date.toString(),
            onClick = { open = true },
            modifier = Modifier.fillMaxWidth().testTag("tx_date").semantics { contentDescription = "Date: $date" },
        )
        if (error != null) ErrorText(error)
    }
    if (open) {
        val state = rememberDatePickerState(initialSelectedDateMillis = date.atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli())
        DatePickerDialog(
            onDismissRequest = { open = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { onDate(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()) }
                    open = false
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { open = false }) { Text("Cancel") } },
        ) { DatePicker(state = state) }
    }
}

/**
 * The add-transaction form. A plain composable (no sheet around it) so it can be tested on its own.
 * [onSaved] runs after the Kernel accepted the transaction.
 */
@Composable
fun AddTransactionForm(vm: AddTransactionViewModel, onSaved: () -> Unit, onCancel: () -> Unit) {
    val state by vm.state.collectAsState()
    val scope = rememberCoroutineScope()
    val account = vm.selectedAccount
    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SectionTitle("Add transaction")
        if (!vm.accounts.isEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                KindOption("Money out", state.isExpense, "tx_expense") { vm.setExpense(true) }
                KindOption("Money in", !state.isExpense, "tx_income") { vm.setExpense(false) }
            }
        }
        LabeledField(
            "Amount", state.amountText, vm::setAmount, state.amountError, "tx_amount",
            keyboardType = KeyboardType.Decimal, placeholder = "12.50",
        )
        LabeledField("Description", state.description, vm::setDescription, state.descriptionError, "tx_description", placeholder = "Lunch with Sam")
        if (vm.accounts.isNotEmpty()) {
            ChoiceField(
                "Account", account?.display ?: "Choose", vm.accounts, { it.display }, { vm.selectAccount(it.id) }, "tx_account",
                error = state.accountError,
            )
        } else {
            ErrorText(state.accountError ?: "Add an account first.")
        }
        DateField(state.date, vm::setDate, state.dateError)
        LabeledField("Category (optional)", state.category, vm::setCategory, state.categoryError, "tx_category")
        val suggestions = vm.categoryNames.filter { it.contains(state.category.trim(), ignoreCase = true) && !it.equals(state.category.trim(), true) }.take(6)
        if (suggestions.isNotEmpty() && state.category.isNotBlank()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                suggestions.forEach { name ->
                    FilterChip(
                        selected = false,
                        onClick = { vm.setCategory(name) },
                        label = { Text(name) },
                        colors = FilterChipDefaults.filterChipColors(labelColor = RevaColors.Secondary),
                    )
                }
            }
        }
        LabeledField("Notes (optional)", state.notes, vm::setNotes, null, "tx_notes")
        Text(vm.previewText(), style = MaterialTheme.typography.bodyMedium, color = RevaColors.Muted, modifier = Modifier.testTag("tx_preview"))
        state.generalError?.let { ErrorText(it, Modifier.testTag("tx_error")) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            SecondaryButton("Cancel", onCancel, Modifier.weight(1f).testTag("tx_cancel"))
            PrimaryButton(
                "Save",
                { scope.launch { if (vm.submit()) onSaved() } },
                Modifier.weight(1f).testTag("tx_save"),
                enabled = !state.isBusy,
            )
        }
    }
}

@Composable
private fun KindOption(label: String, selected: Boolean, tag: String, onClick: () -> Unit) {
    // The whole row (radio and label) is the target, and it is one radio button to a screen reader.
    Row(
        Modifier
            .heightIn(min = 48.dp)
            .selectable(selected = selected, onClick = onClick, role = Role.RadioButton)
            .padding(end = 12.dp)
            .testTag(tag),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(
            selected = selected,
            onClick = null,
            colors = androidx.compose.material3.RadioButtonDefaults.colors(selectedColor = RevaColors.Accent, unselectedColor = RevaColors.Muted),
        )
        Text(label, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.padding(start = 4.dp))
    }
}

@Composable
fun AddAccountForm(vm: AddAccountViewModel, onSaved: () -> Unit, onCancel: () -> Unit) {
    val state by vm.state.collectAsState()
    val scope = rememberCoroutineScope()
    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SectionTitle("Add account")
        LabeledField("Name", state.name, vm::setName, state.nameError, "acct_name", placeholder = "Checking")
        ChoiceField("Type", state.kind, AddAccountViewModel.kinds, { it }, vm::setKind, "acct_kind")
        LabeledField("Currency", state.currency, vm::setCurrency, state.currencyError, "acct_currency")
        LabeledField("Opening balance", state.openingText, vm::setOpening, state.openingError, "acct_opening", keyboardType = KeyboardType.Decimal, placeholder = "0.00")
        CaptionText(state.openingHint)
        state.generalError?.let { ErrorText(it) }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            SecondaryButton("Cancel", onCancel, Modifier.weight(1f))
            PrimaryButton("Add", { scope.launch { if (vm.submit()) onSaved() } }, Modifier.weight(1f).testTag("acct_save"), enabled = !state.isBusy)
        }
    }
}

/** Bottom sheet wrapper used by the app; the forms inside are tested directly. */
@Composable
fun FormSheet(onDismiss: () -> Unit, content: @Composable () -> Unit) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = RevaColors.Surface,
        contentColor = RevaColors.Text,
        modifier = Modifier.imePadding(),
    ) {
        Column(Modifier.navigationBarsPadding()) { content() }
    }
}

// ---- Import ------------------------------------------------------------------------------------

/**
 * Import: choose a file, match CSV columns, "Check file" shows the dry-run row report, and only the Import
 * button (enabled after a successful check of exactly these choices) saves rows.
 */
@Composable
fun ImportForm(vm: ImportViewModel, onChooseFile: () -> Unit, onClose: () -> Unit) {
    val state by vm.state.collectAsState()
    val scope = rememberCoroutineScope()
    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        SectionTitle("Import")
        MutedText("Pick a bank CSV, an OFX/QFX file, or a REVA JSON export. REVA checks every row first and shows you the result. Nothing is saved until you confirm.")
        SecondaryButton(if (state.hasFile) "Choose a different file" else "Choose file…", onChooseFile, Modifier.fillMaxWidth().testTag("import_choose"))
        if (state.fileName.isNotEmpty()) Text(state.fileName, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.testTag("import_file"))

        if (state.needsAccount && vm.accounts.isNotEmpty()) {
            val selected = vm.accounts.firstOrNull { it.id == state.selectedAccountId }
            ChoiceField("Import into account", selected?.display ?: "Choose", vm.accounts, { it.display }, { vm.selectAccount(it.id) }, "import_account")
        }

        if (state.isCsv) {
            SectionTitle("Match the columns")
            val columns = listOf(NONE) + state.headers
            ColumnPicker("Date column", state.dateColumn, columns, vm::setDateColumn, "import_date_col")
            ColumnPicker("Description column", state.descriptionColumn, columns, vm::setDescriptionColumn, "import_desc_col")
            ColumnPicker("Amount column (one column with + and -)", state.amountColumn, columns, vm::setAmountColumn, "import_amount_col")
            ColumnPicker("Debit column (money out)", state.debitColumn, columns, vm::setDebitColumn, "import_debit_col")
            ColumnPicker("Credit column (money in)", state.creditColumn, columns, vm::setCreditColumn, "import_credit_col")
            ColumnPicker("Category column", state.categoryColumn, columns, vm::setCategoryColumn, "import_cat_col")
            ChoiceField("Date format", state.dateFormat, vm.dateFormats, { it }, vm::setDateFormat, "import_date_format")
            if (state.dateFormatIsAmbiguous) {
                ErrorText("This file's dates could be day-first or month-first. Check the format above against a row before importing.")
            }
            Row(
                Modifier.fillMaxWidth().heightIn(min = 48.dp).semantics { role = Role.Switch },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("Flip the sign (my bank shows spending as positive)", style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text, modifier = Modifier.weight(1f))
                androidx.compose.material3.Switch(
                    checked = state.invertSign,
                    onCheckedChange = vm::setInvertSign,
                    colors = androidx.compose.material3.SwitchDefaults.colors(checkedTrackColor = RevaColors.Accent, checkedThumbColor = RevaColors.Ground),
                    modifier = Modifier.testTag("import_invert"),
                )
            }
        }

        PrimaryButton("Check file", { scope.launch { vm.check() } }, Modifier.fillMaxWidth().testTag("import_check"), enabled = state.canCheck)
        state.error?.let { ErrorText(it, Modifier.testTag("import_error")) }

        if (state.hasReport) {
            Text(
                state.summaryText,
                style = MaterialTheme.typography.titleMedium,
                color = RevaColors.Text,
                modifier = Modifier.testTag("import_summary"),
            )
            state.reportRows.forEach { row ->
                Column(
                    Modifier.fillMaxWidth().semantics(mergeDescendants = true) { contentDescription = row.a11y }.padding(vertical = 4.dp),
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Row ${row.rowText}", style = MaterialTheme.typography.bodySmall, color = RevaColors.Muted)
                        Text(
                            row.statusText,
                            style = MaterialTheme.typography.bodySmall,
                            color = when (row.status) {
                                "accepted" -> RevaColors.Success
                                "rejected" -> RevaColors.Error
                                else -> RevaColors.Muted
                            },
                        )
                    }
                    Text(row.summary.trim(), style = MaterialTheme.typography.bodyMedium, color = RevaColors.Text)
                    if (row.detail.isNotEmpty()) CaptionText(row.detail)
                }
            }
        }
        state.resultText?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Success, modifier = Modifier.testTag("import_result"))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            SecondaryButton(if (state.resultText != null) "Done" else "Close", onClose, Modifier.weight(1f).testTag("import_close"))
            PrimaryButton(
                state.confirmText,
                { scope.launch { vm.confirm() } },
                Modifier.weight(1f).testTag("import_confirm"),
                enabled = state.canConfirm,
            )
        }
    }
}

private const val NONE = "(none)"

@Composable
private fun ColumnPicker(label: String, current: String?, columns: List<String>, set: (String?) -> Unit, tag: String) {
    ChoiceField(label, current ?: NONE, columns, { it }, { set(if (it == NONE) null else it) }, tag)
}
