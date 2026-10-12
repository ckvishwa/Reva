package app.reva.ui.finance

import androidx.lifecycle.ViewModel
import app.reva.core.CsvProbe
import app.reva.core.CsvSniffer
import app.reva.core.Money
import app.reva.data.AccountBalance
import app.reva.data.CsvMapping
import app.reva.data.FinanceRepository
import app.reva.data.ImportReport
import app.reva.data.ImportRow
import app.reva.data.Outcome
import java.util.Locale
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class ImportRowUi(val rowText: String, val status: String, val statusText: String, val summary: String, val detail: String, val a11y: String)

data class ImportUiState(
    val fileName: String = "",
    val format: String = "",
    val hasFile: Boolean = false,
    val headers: List<String> = emptyList(),
    val selectedAccountId: String? = null,
    val dateColumn: String? = null,
    val descriptionColumn: String? = null,
    val amountColumn: String? = null,
    val debitColumn: String? = null,
    val creditColumn: String? = null,
    val categoryColumn: String? = null,
    val dateFormat: String = "%Y-%m-%d",
    val dateFormatIsAmbiguous: Boolean = false,
    val decimalSeparator: String = ".",
    val invertSign: Boolean = false,
    val error: String? = null,
    val resultText: String? = null,
    val isBusy: Boolean = false,
    val report: ImportReport? = null,
    val reportRows: List<ImportRowUi> = emptyList(),
) {
    val isCsv: Boolean get() = format == "csv"
    val needsAccount: Boolean get() = format == "csv" || format == "ofx"
    val hasReport: Boolean get() = report != null
    val canCheck: Boolean get() = hasFile && !isBusy && resultText == null
    val canConfirm: Boolean get() = report?.let { it.dryRun && it.accepted > 0 } == true && !isBusy && resultText == null
    val summaryText: String
        get() = report?.let {
            "${it.accepted} will import · ${it.duplicates} already there · ${it.rejected} rejected. Nothing has been saved yet."
        } ?: "Check the file first. Nothing is saved until you confirm."
    val confirmText: String get() = report?.takeIf { it.accepted > 0 }?.let { "Import ${it.accepted} rows" } ?: "Import"
}

/**
 * The Import flow. Nothing is saved until the person has seen the dry-run row report and pressed Import.
 * Changing any choice after the check discards the report, so the confirmation always applies to exactly
 * what was checked.
 */
class ImportViewModel(
    private val repository: FinanceRepository,
    val accounts: List<AccountOption>,
) : ViewModel() {

    private val _state = MutableStateFlow(ImportUiState(selectedAccountId = accounts.firstOrNull()?.id))
    val state: StateFlow<ImportUiState> = _state.asStateFlow()

    private var data: ByteArray? = null
    private var probe: CsvProbe? = null

    val dateFormats: List<String> get() = CsvSniffer.kernelDateFormats

    /** Core refuses bigger imports (8 MiB); say so before reading the file at all. */
    fun rejectTooLarge(fileName: String) = reject(
        fileName, "That file is larger than 8 MB, which is more than REVA imports in one go. Split it and import the parts.",
    )

    fun rejectUnreadable(fileName: String) = reject(fileName, "REVA could not read that file.")

    private fun reject(fileName: String, message: String) {
        data = null
        probe = null
        _state.update { ImportUiState(fileName = fileName, selectedAccountId = it.selectedAccountId, error = message) }
    }

    fun loadFile(fileName: String, bytes: ByteArray) {
        data = bytes
        probe = null
        val extension = fileName.substringAfterLast('.', "").lowercase(Locale.ROOT)
        val format = when (extension) {
            "csv", "tsv", "txt" -> "csv"
            "ofx", "qfx" -> "ofx"
            "json" -> "json"
            else -> ""
        }
        val base = ImportUiState(
            fileName = fileName,
            format = format,
            hasFile = true,
            selectedAccountId = _state.value.selectedAccountId,
        )
        if (format.isEmpty()) {
            _state.value = base.copy(error = "REVA imports CSV, OFX/QFX and its own JSON export. That file type isn't one of them.")
            return
        }
        if (format != "csv") {
            _state.value = base
            return
        }
        val p = CsvSniffer.probe(bytes)
        if (p == null) {
            _state.value = base.copy(error = "That file doesn't look like a CSV with a header row.")
            return
        }
        probe = p
        val g = CsvSniffer.guess(p)
        _state.value = base.copy(
            headers = p.headers,
            dateColumn = g.date,
            descriptionColumn = g.description,
            amountColumn = g.amount,
            debitColumn = g.debit,
            creditColumn = g.credit,
            categoryColumn = g.category,
            dateFormat = g.dateFormat,
            dateFormatIsAmbiguous = g.dateFormatIsAmbiguous,
            decimalSeparator = g.decimalSeparator,
        )
    }

    // Every input change throws the report away.
    private fun changed(transform: (ImportUiState) -> ImportUiState) = _state.update {
        transform(it).copy(report = null, reportRows = emptyList(), error = null)
    }

    fun selectAccount(id: String) = changed { it.copy(selectedAccountId = id) }

    fun setDateColumn(v: String?) = changed { it.copy(dateColumn = v) }

    fun setDescriptionColumn(v: String?) = changed { it.copy(descriptionColumn = v) }

    fun setAmountColumn(v: String?) = changed { it.copy(amountColumn = v) }

    fun setDebitColumn(v: String?) = changed { it.copy(debitColumn = v) }

    fun setCreditColumn(v: String?) = changed { it.copy(creditColumn = v) }

    fun setCategoryColumn(v: String?) = changed { it.copy(categoryColumn = v) }

    fun setDateFormat(v: String) = changed { it.copy(dateFormat = v, dateFormatIsAmbiguous = false) }

    fun setDecimalSeparator(v: String) = changed { it.copy(decimalSeparator = v) }

    fun setInvertSign(v: Boolean) = changed { it.copy(invertSign = v) }

    /** Dry run: asks the Kernel what would happen to every row and saves nothing. */
    suspend fun check(): Boolean {
        val s = _state.value
        if (!s.hasFile || s.isBusy) return false
        validateInputs(s)?.let { problem ->
            _state.update { it.copy(error = problem) }
            return false
        }
        _state.update { it.copy(isBusy = true, error = null) }
        try {
            return when (val result = run(s, dryRun = true)) {
                is Outcome.Failed -> {
                    _state.update { it.copy(report = null, reportRows = emptyList(), error = describe(result)) }
                    false
                }
                is Outcome.Ok -> {
                    val currency = accounts.firstOrNull { it.id == s.selectedAccountId }?.currency ?: "USD"
                    _state.update {
                        it.copy(report = result.value, reportRows = result.value.rows.sortedBy { r -> r.row }.map { r -> rowUi(r, currency) })
                    }
                    true
                }
            }
        } finally {
            _state.update { it.copy(isBusy = false) }
        }
    }

    /** The real import. Only possible after [check] showed the report. */
    suspend fun confirm(): Boolean {
        val s = _state.value
        if (!s.canConfirm) return false
        _state.update { it.copy(isBusy = true, error = null) }
        try {
            return when (val result = run(s, dryRun = false)) {
                is Outcome.Failed -> {
                    _state.update { it.copy(error = describe(result)) }
                    false
                }
                is Outcome.Ok -> {
                    val done = result.value
                    _state.update {
                        it.copy(resultText = "Imported ${done.accepted} rows. ${done.duplicates} were already there, ${done.rejected} were rejected.")
                    }
                    true
                }
            }
        } finally {
            _state.update { it.copy(isBusy = false) }
        }
    }

    private fun describe(failed: Outcome.Failed): String =
        failed.error.detail?.let { "${failed.error.message} ($it)" } ?: failed.error.message

    private suspend fun run(s: ImportUiState, dryRun: Boolean): Outcome<ImportReport> = repository.import(
        s.format, data!!, if (s.needsAccount) s.selectedAccountId else null, if (s.isCsv) buildMapping(s) else null, dryRun,
    )

    private fun buildMapping(s: ImportUiState) = CsvMapping(
        s.dateColumn!!, s.dateFormat, s.descriptionColumn!!, s.amountColumn, s.debitColumn, s.creditColumn, s.categoryColumn,
        probe?.delimiter ?: ",", s.decimalSeparator, s.invertSign,
    )

    private fun validateInputs(s: ImportUiState): String? {
        if (s.needsAccount && s.selectedAccountId == null) return "Choose the account these transactions belong to."
        if (!s.isCsv) return null
        if (s.dateColumn.isNullOrEmpty()) return "Choose which column holds the date."
        if (s.descriptionColumn.isNullOrEmpty()) return "Choose which column holds the description."
        val hasAmount = !s.amountColumn.isNullOrEmpty()
        val hasSplit = !s.debitColumn.isNullOrEmpty() || !s.creditColumn.isNullOrEmpty()
        if (hasAmount == hasSplit) {
            return if (hasAmount) "Use either one Amount column or Debit/Credit columns, not both."
            else "Choose the Amount column, or the Debit and Credit columns."
        }
        return null
    }

    private fun rowUi(row: ImportRow, currency: String): ImportRowUi {
        val rowText = row.row.toString()
        val statusText = when (row.status) {
            "accepted" -> "will import"
            "duplicate" -> "already there"
            "rejected" -> "rejected"
            else -> row.status
        }
        val summary = if (row.status == "rejected") {
            row.raw ?: ""
        } else {
            "${row.date}  ${row.description}  ${row.amountMinor?.let { Money.format(it, currency, showPlus = true) } ?: ""}"
        }
        val detail = row.reason ?: row.warning ?: ""
        return ImportRowUi(rowText, row.status, statusText, summary, detail, "Row $rowText, $statusText. ${summary.trim()}. $detail".trim())
    }

    companion object {
        const val MAX_FILE_BYTES = 8L * 1024 * 1024

        fun create(repository: FinanceRepository, accounts: List<AccountBalance>) =
            ImportViewModel(repository, accounts.filter { !it.archived }.map(AccountOption::of))
    }
}
