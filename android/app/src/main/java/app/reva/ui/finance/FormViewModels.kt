package app.reva.ui.finance

import androidx.lifecycle.ViewModel
import app.reva.core.Money
import app.reva.data.AccountBalance
import app.reva.data.Category
import app.reva.data.FinanceError
import app.reva.data.FinanceRepository
import app.reva.data.NewAccount
import app.reva.data.NewTransaction
import app.reva.data.Outcome
import java.time.LocalDate
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

data class AccountOption(val id: String, val name: String, val currency: String) {
    val display: String get() = "$name ($currency)"

    companion object {
        fun of(b: AccountBalance) = AccountOption(b.accountId, b.name, b.currency)
    }
}

// ---- Add transaction -------------------------------------------------------------------------

data class AddTransactionState(
    val selectedAccountId: String? = null,
    val isExpense: Boolean = true,
    val amountText: String = "",
    val description: String = "",
    val category: String = "",
    val notes: String = "",
    val date: LocalDate = LocalDate.now(),
    val accountError: String? = null,
    val dateError: String? = null,
    val amountError: String? = null,
    val descriptionError: String? = null,
    val categoryError: String? = null,
    val generalError: String? = null,
    val isBusy: Boolean = false,
)

/**
 * The add-transaction sheet. Nothing is saved until Save is pressed; the preview line says in words what
 * will be recorded, and the sign comes only from the Money out / Money in choice, never from a typing slip.
 */
class AddTransactionViewModel(
    private val repository: FinanceRepository,
    val accounts: List<AccountOption>,
    val categoryNames: List<String>,
    private val today: LocalDate,
) : ViewModel() {

    private val _state = MutableStateFlow(
        AddTransactionState(selectedAccountId = accounts.firstOrNull()?.id, date = today),
    )
    val state: StateFlow<AddTransactionState> = _state.asStateFlow()

    val selectedAccount: AccountOption? get() = accounts.firstOrNull { it.id == _state.value.selectedAccountId }

    fun selectAccount(id: String) = _state.update { it.copy(selectedAccountId = id, accountError = null, amountError = null) }

    fun setExpense(expense: Boolean) = _state.update { it.copy(isExpense = expense) }

    fun setAmount(text: String) = _state.update { it.copy(amountText = text, amountError = null) }

    fun setDescription(text: String) = _state.update { it.copy(description = text, descriptionError = null) }

    fun setCategory(text: String) = _state.update { it.copy(category = text, categoryError = null) }

    fun setNotes(text: String) = _state.update { it.copy(notes = text) }

    fun setDate(date: LocalDate) = _state.update { it.copy(date = date, dateError = null) }

    /** The amount in signed minor units, or null while the amount text is not valid. */
    fun signedAmountMinor(): Long? {
        val account = selectedAccount ?: return null
        val parsed = Money.parse(_state.value.amountText, account.currency) as? Money.Parsed.Ok ?: return null
        val magnitude = kotlin.math.abs(parsed.minor)
        return if (_state.value.isExpense) -magnitude else magnitude
    }

    /** What will be saved, in words, so the person confirms real numbers. */
    fun previewText(): String {
        val minor = signedAmountMinor()
        val account = selectedAccount
        if (minor == null || minor == 0L || account == null) return "Enter an amount to see what will be recorded."
        val verb = if (_state.value.isExpense) "spent from" else "added to"
        val money = Money.format(kotlin.math.abs(minor), account.currency)
        return "Will record $money $verb ${account.name} on ${_state.value.date}."
    }

    /** Checks the form without touching the Kernel. Returns true when it can be saved. */
    fun validate(): Boolean {
        val s = _state.value
        val account = selectedAccount
        val accountError = if (account == null) "Choose an account." else null
        val descriptionError = if (s.description.isBlank()) "Enter a description." else null
        val dateError = when {
            s.date.year < 1900 || s.date.year > 2200 -> "Choose a date between 1900 and 2200."
            s.date.isAfter(today.plusDays(366)) -> "That date is more than a year ahead."
            else -> null
        }
        var amountError: String? = null
        if (account != null) {
            when (val parsed = Money.parse(s.amountText, account.currency)) {
                is Money.Parsed.Error -> amountError = parsed.message
                is Money.Parsed.Ok -> if (parsed.minor == 0L) amountError = "The amount can't be zero."
            }
        }
        _state.update {
            it.copy(accountError = accountError, descriptionError = descriptionError, dateError = dateError, amountError = amountError)
        }
        return accountError == null && descriptionError == null && dateError == null && amountError == null
    }

    /** Validates, then saves. Returns true when the transaction was recorded. */
    suspend fun submit(): Boolean {
        _state.update { it.copy(generalError = null, categoryError = null) }
        if (_state.value.isBusy || !validate()) return false
        val s = _state.value
        _state.update { it.copy(isBusy = true) }
        try {
            val request = NewTransaction(
                accountId = s.selectedAccountId!!,
                date = s.date.toString(),
                amountMinor = signedAmountMinor()!!,
                description = s.description.trim(),
                category = s.category.trim().ifEmpty { null },
                notes = s.notes.trim().ifEmpty { null },
            )
            return when (val result = repository.addTransaction(request)) {
                is Outcome.Ok -> true
                is Outcome.Failed -> {
                    mapError(result.error)
                    false
                }
            }
        } finally {
            _state.update { it.copy(isBusy = false) }
        }
    }

    private fun mapError(error: FinanceError) {
        val message = error.detail ?: error.message
        _state.update {
            when (error.field) {
                "amount_minor" -> it.copy(amountError = message)
                "description" -> it.copy(descriptionError = message)
                "date" -> it.copy(dateError = message)
                "account_id", "currency" -> it.copy(accountError = message)
                "category", "category_id" -> it.copy(categoryError = message)
                else -> it.copy(generalError = error.message)
            }
        }
    }

    companion object {
        fun create(repository: FinanceRepository, accounts: List<AccountBalance>, categories: List<Category>, today: LocalDate) =
            AddTransactionViewModel(
                repository,
                accounts.filter { !it.archived }.map(AccountOption::of),
                categories.map { it.name },
                today,
            )
    }
}

// ---- Add account -----------------------------------------------------------------------------

data class AddAccountState(
    val name: String = "",
    val kind: String = "checking",
    val currency: String = "USD",
    val openingText: String = "",
    val nameError: String? = null,
    val currencyError: String? = null,
    val openingError: String? = null,
    val generalError: String? = null,
    val isBusy: Boolean = false,
) {
    val isLiability: Boolean get() = kind == "credit" || kind == "loan"
    val openingHint: String
        get() = if (isLiability) "Enter what you owe as a positive number; REVA stores it as a negative balance." else "Leave blank for 0."
}

class AddAccountViewModel(private val repository: FinanceRepository) : ViewModel() {
    private val _state = MutableStateFlow(AddAccountState())
    val state: StateFlow<AddAccountState> = _state.asStateFlow()

    fun setName(v: String) = _state.update { it.copy(name = v, nameError = null) }

    fun setKind(v: String) = _state.update { it.copy(kind = v) }

    fun setCurrency(v: String) = _state.update { it.copy(currency = v.uppercase().take(3), currencyError = null) }

    fun setOpening(v: String) = _state.update { it.copy(openingText = v, openingError = null) }

    fun validate(): Boolean {
        val s = _state.value
        val code = s.currency.trim().uppercase()
        val nameError = if (s.name.isBlank()) "Enter a name." else null
        val currencyError = if (Regex("^[A-Z]{3}$").matches(code)) null else "Use a 3-letter currency code such as USD."
        var openingError: String? = null
        if (currencyError == null && s.openingText.isNotBlank()) {
            (Money.parse(s.openingText, code) as? Money.Parsed.Error)?.let { openingError = it.message }
        }
        _state.update { it.copy(nameError = nameError, currencyError = currencyError, openingError = openingError) }
        return nameError == null && currencyError == null && openingError == null
    }

    suspend fun submit(): Boolean {
        _state.update { it.copy(generalError = null) }
        if (_state.value.isBusy || !validate()) return false
        val s = _state.value
        val code = s.currency.trim().uppercase()
        var opening = 0L
        if (s.openingText.isNotBlank()) {
            opening = (Money.parse(s.openingText, code) as Money.Parsed.Ok).minor
            if (s.isLiability) opening = -kotlin.math.abs(opening)
        }
        _state.update { it.copy(isBusy = true) }
        try {
            return when (val result = repository.addAccount(NewAccount(s.name.trim(), s.kind, code, opening))) {
                is Outcome.Ok -> true
                is Outcome.Failed -> {
                    val message = result.error.detail ?: result.error.message
                    _state.update {
                        when {
                            result.error.field == "name" -> it.copy(nameError = message)
                            result.error.field == "currency" -> it.copy(currencyError = message)
                            result.error.field == "opening_balance_minor" -> it.copy(openingError = message)
                            result.error.kind == app.reva.data.ErrorKind.Conflict -> it.copy(nameError = message)
                            else -> it.copy(generalError = result.error.message)
                        }
                    }
                    false
                }
            }
        } finally {
            _state.update { it.copy(isBusy = false) }
        }
    }

    companion object {
        val kinds = listOf("checking", "savings", "credit", "cash", "investment", "loan", "other")
    }
}
