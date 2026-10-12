using System.Globalization;
using Reva.Desktop.Finance;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public sealed record AccountOption(string Id, string Name, string Currency)
{
    public string Display => $"{Name} ({Currency})";
}

/// <summary>
/// The "Add transaction" flow. The person types a positive amount and picks Expense or Income, so
/// the sign is never a typing accident. The preview line shows exactly what will be saved; nothing
/// is sent until <see cref="SubmitAsync"/>, and nothing moves money anywhere.
/// </summary>
public sealed class AddTransactionViewModel : ObservableObject
{
    private readonly IFinanceApi _api;
    private readonly DateOnly _today;
    private AccountOption? _selectedAccount;
    private DateTimeOffset _date;
    private bool _isExpense = true;
    private string _amountText = string.Empty;
    private string _description = string.Empty;
    private string _category = string.Empty;
    private string _notes = string.Empty;
    private string? _accountError;
    private string? _dateError;
    private string? _amountError;
    private string? _descriptionError;
    private string? _categoryError;
    private string? _generalError;
    private bool _isBusy;

    public AddTransactionViewModel(
        IFinanceApi api,
        IReadOnlyList<AccountBalance> accounts,
        IReadOnlyList<FinanceCategory> categories,
        DateOnly today)
    {
        _api = api;
        _today = today;
        Accounts = accounts.Select(a => new AccountOption(a.AccountId, a.Name, a.Currency)).ToList();
        CategoryNames = categories.OrderBy(c => c.Name, StringComparer.OrdinalIgnoreCase).Select(c => c.Name).ToList();
        _selectedAccount = Accounts.FirstOrDefault();
        _date = new DateTimeOffset(today.ToDateTime(TimeOnly.MinValue));
    }

    public IReadOnlyList<AccountOption> Accounts { get; }

    public IReadOnlyList<string> CategoryNames { get; }

    public AccountOption? SelectedAccount
    {
        get => _selectedAccount;
        set
        {
            if (SetProperty(ref _selectedAccount, value))
            {
                AccountError = null;
                RaisePreview();
            }
        }
    }

    public DateTimeOffset Date
    {
        get => _date;
        set
        {
            if (SetProperty(ref _date, value))
            {
                DateError = null;
                RaisePreview();
            }
        }
    }

    public bool IsExpense
    {
        get => _isExpense;
        set
        {
            if (SetProperty(ref _isExpense, value))
            {
                RaisePropertyChanged(nameof(IsIncome));
                RaisePreview();
            }
        }
    }

    public bool IsIncome
    {
        get => !_isExpense;
        set => IsExpense = !value;
    }

    public string AmountText
    {
        get => _amountText;
        set
        {
            if (SetProperty(ref _amountText, value))
            {
                AmountError = null;
                RaisePreview();
            }
        }
    }

    public string Description
    {
        get => _description;
        set
        {
            if (SetProperty(ref _description, value))
            {
                DescriptionError = null;
            }
        }
    }

    /// <summary>A category name or alias (for example "lunch" if it is an alias of Food · Dining).</summary>
    public string Category
    {
        get => _category;
        set
        {
            if (SetProperty(ref _category, value))
            {
                CategoryError = null;
            }
        }
    }

    public string Notes
    {
        get => _notes;
        set => SetProperty(ref _notes, value);
    }

    public string? AccountError { get => _accountError; private set => SetProperty(ref _accountError, value); }

    public string? DateError { get => _dateError; private set => SetProperty(ref _dateError, value); }

    public string? AmountError { get => _amountError; private set => SetProperty(ref _amountError, value); }

    public string? DescriptionError { get => _descriptionError; private set => SetProperty(ref _descriptionError, value); }

    public string? CategoryError { get => _categoryError; private set => SetProperty(ref _categoryError, value); }

    public string? GeneralError { get => _generalError; private set => SetProperty(ref _generalError, value); }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanSubmit));
            }
        }
    }

    public bool CanSubmit => !IsBusy;

    public bool HasAccounts => Accounts.Count > 0;

    /// <summary>The amount in signed minor units, or null while the amount text is not valid.</summary>
    public long? SignedAmountMinor
    {
        get
        {
            if (SelectedAccount is null || !MoneyFormat.TryParse(AmountText, SelectedAccount.Currency, out var minor, out _))
            {
                return null;
            }

            var magnitude = Math.Abs(minor);
            return IsExpense ? -magnitude : magnitude;
        }
    }

    /// <summary>What will be saved, in words, so the person confirms real numbers.</summary>
    public string PreviewText
    {
        get
        {
            var minor = SignedAmountMinor;
            if (minor is null or 0 || SelectedAccount is null)
            {
                return "Enter an amount to see what will be recorded.";
            }

            var verb = IsExpense ? "spent from" : "added to";
            var money = MoneyFormat.Format(Math.Abs(minor.Value), SelectedAccount.Currency);
            return $"Will record {money} {verb} {SelectedAccount.Name} on {Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)}.";
        }
    }

    /// <summary>Checks the form without calling Core. Returns true when it can be submitted.</summary>
    public bool Validate()
    {
        AccountError = SelectedAccount is null ? "Choose an account." : null;
        DateError = null;
        AmountError = null;
        DescriptionError = string.IsNullOrWhiteSpace(Description) ? "Enter a description." : null;

        var date = DateOnly.FromDateTime(Date.Date);
        if (date.Year is < 1900 or > 2200)
        {
            DateError = "Choose a date between 1900 and 2200.";
        }
        else if (date > _today.AddDays(366))
        {
            DateError = "That date is more than a year ahead.";
        }

        if (SelectedAccount is not null)
        {
            if (!MoneyFormat.TryParse(AmountText, SelectedAccount.Currency, out var minor, out var error))
            {
                AmountError = error;
            }
            else if (minor == 0)
            {
                AmountError = "The amount can't be zero.";
            }
        }

        return AccountError is null && DateError is null && AmountError is null && DescriptionError is null;
    }

    /// <summary>Validates, then saves through Core. Returns true when the transaction was recorded.</summary>
    public async Task<bool> SubmitAsync(CancellationToken cancellationToken = default)
    {
        GeneralError = null;
        CategoryError = null;
        if (IsBusy || !Validate())
        {
            return false;
        }

        IsBusy = true;
        try
        {
            var result = await _api.AddTransactionAsync(
                new NewTransactionRequest(
                    SelectedAccount!.Id,
                    Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                    SignedAmountMinor!.Value,
                    Description.Trim(),
                    string.IsNullOrWhiteSpace(Category) ? null : Category.Trim(),
                    string.IsNullOrWhiteSpace(Notes) ? null : Notes.Trim()),
                cancellationToken).ConfigureAwait(true);
            if (result.IsSuccess)
            {
                return true;
            }

            MapError(result.Error!);
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void MapError(FinanceError error)
    {
        var message = error.Detail ?? error.SafeMessage;
        switch (error.Field)
        {
            case "amount_minor":
                AmountError = message;
                break;
            case "description":
                DescriptionError = message;
                break;
            case "date":
                DateError = message;
                break;
            case "account_id":
            case "currency":
                AccountError = message;
                break;
            case "category":
            case "category_id":
                CategoryError = message;
                break;
            default:
                GeneralError = error.SafeMessage;
                break;
        }
    }

    private void RaisePreview() => RaisePropertyChanged(nameof(PreviewText));
}
