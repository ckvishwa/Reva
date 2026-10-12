using System.Text.RegularExpressions;
using Reva.Desktop.Finance;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>"Add account": the first thing a fresh install needs before any transaction can be added.</summary>
public sealed class AddAccountViewModel : ObservableObject
{
    public static IReadOnlyList<string> Kinds { get; } =
        new[] { "checking", "savings", "credit", "cash", "investment", "loan", "other" };

    private readonly IFinanceApi _api;
    private string _name = string.Empty;
    private string _kind = "checking";
    private string _currency = "USD";
    private string _openingText = string.Empty;
    private string? _nameError;
    private string? _currencyError;
    private string? _openingError;
    private string? _generalError;
    private bool _isBusy;

    public AddAccountViewModel(IFinanceApi api)
    {
        _api = api;
    }

    public string Name
    {
        get => _name;
        set
        {
            if (SetProperty(ref _name, value))
            {
                NameError = null;
            }
        }
    }

    public string Kind
    {
        get => _kind;
        set
        {
            if (SetProperty(ref _kind, value))
            {
                RaisePropertyChanged(nameof(OpeningHint));
            }
        }
    }

    public string Currency
    {
        get => _currency;
        set
        {
            if (SetProperty(ref _currency, value))
            {
                CurrencyError = null;
            }
        }
    }

    public string OpeningText
    {
        get => _openingText;
        set
        {
            if (SetProperty(ref _openingText, value))
            {
                OpeningError = null;
            }
        }
    }

    public string OpeningHint => IsLiability
        ? "What you owe today, as a positive number. REVA stores it as money owed."
        : "What the account holds today. Leave blank for zero.";

    public bool IsLiability => Kind is "credit" or "loan";

    public string? NameError { get => _nameError; private set => SetProperty(ref _nameError, value); }

    public string? CurrencyError { get => _currencyError; private set => SetProperty(ref _currencyError, value); }

    public string? OpeningError { get => _openingError; private set => SetProperty(ref _openingError, value); }

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

    public bool Validate()
    {
        NameError = string.IsNullOrWhiteSpace(Name) ? "Enter a name." : null;
        var code = Currency.Trim().ToUpperInvariant();
        CurrencyError = Regex.IsMatch(code, "^[A-Z]{3}$") ? null : "Use a 3-letter currency code such as USD.";
        OpeningError = null;
        if (CurrencyError is null && !string.IsNullOrWhiteSpace(OpeningText)
            && !MoneyFormat.TryParse(OpeningText, code, out _, out var error))
        {
            OpeningError = error;
        }

        return NameError is null && CurrencyError is null && OpeningError is null;
    }

    public async Task<bool> SubmitAsync(CancellationToken cancellationToken = default)
    {
        GeneralError = null;
        if (IsBusy || !Validate())
        {
            return false;
        }

        var code = Currency.Trim().ToUpperInvariant();
        long opening = 0;
        if (!string.IsNullOrWhiteSpace(OpeningText))
        {
            MoneyFormat.TryParse(OpeningText, code, out opening, out _);
            opening = IsLiability ? -Math.Abs(opening) : opening;
        }

        IsBusy = true;
        try
        {
            var result = await _api.AddAccountAsync(
                new NewAccountRequest(Name.Trim(), Kind, code, opening), cancellationToken).ConfigureAwait(true);
            if (result.IsSuccess)
            {
                return true;
            }

            var message = result.Error!.Detail ?? result.Error.SafeMessage;
            switch (result.Error.Field)
            {
                case "name":
                    NameError = message;
                    break;
                case "currency":
                    CurrencyError = message;
                    break;
                case "opening_balance_minor":
                    OpeningError = message;
                    break;
                default:
                    // Duplicate names come back as a conflict with no field.
                    if (result.Error.Kind == FinanceErrorKind.Conflict)
                    {
                        NameError = message;
                    }
                    else
                    {
                        GeneralError = result.Error.SafeMessage;
                    }

                    break;
            }

            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }
}
