using System.Collections.ObjectModel;
using Reva.Desktop.Finance;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public sealed class ImportRowViewModel
{
    public ImportRowViewModel(ImportRow row, string currency)
    {
        RowText = row.Row.ToString(System.Globalization.CultureInfo.InvariantCulture);
        StatusText = row.Status switch
        {
            "accepted" => "will import",
            "duplicate" => "already there",
            "rejected" => "rejected",
            _ => row.Status,
        };
        Status = row.Status;
        Summary = row.Status == "rejected"
            ? (row.Raw ?? string.Empty)
            : $"{row.Date}  {row.Description}  {(row.AmountMinor is { } m ? MoneyFormat.Format(m, currency, showPlus: true) : string.Empty)}";
        Detail = row.Reason ?? row.Warning ?? string.Empty;
        AccessibleName = $"Row {RowText}, {StatusText}. {Summary.Trim()}. {Detail}".Trim();
    }

    public string RowText { get; }

    public string Status { get; }

    public string StatusText { get; }

    public string Summary { get; }

    public string Detail { get; }

    public string AccessibleName { get; }
}

/// <summary>
/// The Import flow. Nothing is saved until the person has seen the dry-run row report and pressed
/// Import. Changing any choice after the check discards the report, so the confirmation always
/// applies to exactly what was checked.
/// </summary>
public sealed class ImportViewModel : ObservableObject
{
    private readonly IFinanceApi _api;
    private byte[]? _data;
    private string _fileName = string.Empty;
    private string _format = string.Empty;
    private AccountOption? _selectedAccount;
    private CsvProbe? _probe;
    private string? _dateColumn;
    private string? _descriptionColumn;
    private string? _amountColumn;
    private string? _debitColumn;
    private string? _creditColumn;
    private string? _categoryColumn;
    private string _dateFormat = "%Y-%m-%d";
    private string _decimalSeparator = ".";
    private bool _invertSign;
    private bool _dateFormatIsAmbiguous;
    private ImportReport? _report;
    private string? _error;
    private string? _resultText;
    private bool _isBusy;

    public ImportViewModel(IFinanceApi api, IReadOnlyList<AccountBalance> accounts)
    {
        _api = api;
        Accounts = accounts.Select(a => new AccountOption(a.AccountId, a.Name, a.Currency)).ToList();
        _selectedAccount = Accounts.FirstOrDefault();
    }

    public IReadOnlyList<AccountOption> Accounts { get; }

    public IReadOnlyList<string> DateFormats { get; } = CsvSniffer.KernelDateFormats;

    public ObservableCollection<string> Headers { get; } = new();

    public ObservableCollection<ImportRowViewModel> ReportRows { get; } = new();

    public string FileName { get => _fileName; private set => SetProperty(ref _fileName, value); }

    /// <summary><c>csv</c>, <c>ofx</c> or <c>json</c>; empty until a file is loaded.</summary>
    public string Format
    {
        get => _format;
        private set
        {
            if (SetProperty(ref _format, value))
            {
                RaisePropertyChanged(nameof(IsCsv));
                RaisePropertyChanged(nameof(NeedsAccount));
                RaisePropertyChanged(nameof(HasFile));
            }
        }
    }

    public bool HasFile => _data is not null;

    public bool IsCsv => Format == "csv";

    public bool NeedsAccount => Format is "csv" or "ofx";

    public AccountOption? SelectedAccount
    {
        get => _selectedAccount;
        set => ChangeInput(ref _selectedAccount, value);
    }

    public string? DateColumn { get => _dateColumn; set => ChangeInput(ref _dateColumn, value); }

    public string? DescriptionColumn { get => _descriptionColumn; set => ChangeInput(ref _descriptionColumn, value); }

    public string? AmountColumn { get => _amountColumn; set => ChangeInput(ref _amountColumn, value); }

    public string? DebitColumn { get => _debitColumn; set => ChangeInput(ref _debitColumn, value); }

    public string? CreditColumn { get => _creditColumn; set => ChangeInput(ref _creditColumn, value); }

    public string? CategoryColumn { get => _categoryColumn; set => ChangeInput(ref _categoryColumn, value); }

    public string DateFormat { get => _dateFormat; set => ChangeInput(ref _dateFormat, value); }

    public string DecimalSeparator { get => _decimalSeparator; set => ChangeInput(ref _decimalSeparator, value); }

    public bool InvertSign { get => _invertSign; set => ChangeInput(ref _invertSign, value); }

    public bool DateFormatIsAmbiguous
    {
        get => _dateFormatIsAmbiguous;
        private set => SetProperty(ref _dateFormatIsAmbiguous, value);
    }

    public string? Error { get => _error; private set => SetProperty(ref _error, value); }

    /// <summary>Shown after a real import has finished.</summary>
    public string? ResultText { get => _resultText; private set => SetProperty(ref _resultText, value); }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanCheck));
                RaisePropertyChanged(nameof(CanConfirm));
            }
        }
    }

    public ImportReport? Report
    {
        get => _report;
        private set
        {
            if (SetProperty(ref _report, value))
            {
                RaisePropertyChanged(nameof(HasReport));
                RaisePropertyChanged(nameof(CanConfirm));
                RaisePropertyChanged(nameof(SummaryText));
                RaisePropertyChanged(nameof(ConfirmText));
            }
        }
    }

    public bool HasReport => Report is not null;

    public bool CanCheck => HasFile && !IsBusy && ResultText is null;

    /// <summary>The Import button is enabled only after a successful dry run of exactly these choices
    /// that would import at least one row.</summary>
    public bool CanConfirm => Report is { DryRun: true, Accepted: > 0 } && !IsBusy && ResultText is null;

    public string SummaryText => Report is null
        ? "Check the file first. Nothing is saved until you confirm."
        : $"{Report.Accepted} will import · {Report.Duplicates} already there · {Report.Rejected.Count} rejected. Nothing has been saved yet.";

    public string ConfirmText => Report is { Accepted: > 0 } r ? $"Import {r.Accepted} rows" : "Import";

    /// <summary>Loads a file's bytes and, for CSV, proposes a column mapping.</summary>
    /// <summary>Core refuses bigger imports (8 MiB); say so before reading the file at all.</summary>
    public const long MaxFileBytes = 8 * 1024 * 1024;

    public void RejectTooLarge(string fileName) => Reject(
        fileName, "That file is larger than 8 MB, which is more than REVA imports in one go. Split it and import the parts.");

    public void RejectUnreadable(string fileName) => Reject(fileName, "REVA could not read that file.");

    private void Reject(string fileName, string message)
    {
        _data = null;
        FileName = fileName;
        Format = string.Empty;
        Report = null;
        ResultText = null;
        ReportRows.Clear();
        Headers.Clear();
        RaisePropertyChanged(nameof(HasFile));
        RaisePropertyChanged(nameof(CanCheck));
        Error = message;
    }

    public void LoadFile(string fileName, byte[] data)
    {
        _data = data;
        FileName = fileName;
        Report = null;
        ResultText = null;
        Error = null;
        ReportRows.Clear();
        Headers.Clear();
        var extension = Path.GetExtension(fileName).ToLowerInvariant();
        Format = extension switch
        {
            ".csv" or ".tsv" or ".txt" => "csv",
            ".ofx" or ".qfx" => "ofx",
            ".json" => "json",
            _ => string.Empty,
        };
        RaisePropertyChanged(nameof(HasFile));
        RaisePropertyChanged(nameof(CanCheck));
        if (Format.Length == 0)
        {
            Error = "REVA imports CSV, OFX/QFX and its own JSON export. That file type isn't one of them.";
            return;
        }

        if (Format != "csv")
        {
            return;
        }

        _probe = CsvSniffer.Probe(data);
        if (_probe is null)
        {
            Error = "That file doesn't look like a CSV with a header row.";
            return;
        }

        foreach (var header in _probe.Headers)
        {
            Headers.Add(header);
        }

        var guess = CsvSniffer.Guess(_probe);
        SetGuess(guess);
    }

    /// <summary>Dry run: asks Core what would happen to every row and saves nothing.</summary>
    public async Task<bool> CheckAsync(CancellationToken cancellationToken = default)
    {
        if (!HasFile || IsBusy)
        {
            return false;
        }

        var problem = ValidateInputs();
        if (problem is not null)
        {
            Error = problem;
            return false;
        }

        IsBusy = true;
        Error = null;
        try
        {
            var result = await RunAsync(dryRun: true, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                Report = null;
                ReportRows.Clear();
                Error = result.Error!.Detail is { } detail ? $"{result.Error.SafeMessage} ({detail})" : result.Error.SafeMessage;
                return false;
            }

            var currency = SelectedAccount?.Currency ?? "USD";
            ReportRows.Clear();
            foreach (var row in result.Value!.Rows.OrderBy(r => r.Row))
            {
                ReportRows.Add(new ImportRowViewModel(row, currency));
            }

            Report = result.Value;
            return true;
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>The real import. Only possible after <see cref="CheckAsync"/> showed the report.</summary>
    public async Task<bool> ConfirmAsync(CancellationToken cancellationToken = default)
    {
        if (!CanConfirm)
        {
            return false;
        }

        IsBusy = true;
        Error = null;
        try
        {
            var result = await RunAsync(dryRun: false, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                Error = result.Error!.Detail is { } detail ? $"{result.Error.SafeMessage} ({detail})" : result.Error.SafeMessage;
                return false;
            }

            var done = result.Value!;
            ResultText = $"Imported {done.Accepted} rows. {done.Duplicates} were already there, {done.Rejected.Count} were rejected.";
            return true;
        }
        finally
        {
            IsBusy = false;
            RaisePropertyChanged(nameof(CanCheck));
            RaisePropertyChanged(nameof(CanConfirm));
        }
    }

    // ------------------------------------------------------------------------------------------

    private Task<FinanceResult<ImportReport>> RunAsync(bool dryRun, CancellationToken cancellationToken) =>
        _api.ImportAsync(Format, _data!, NeedsAccount ? SelectedAccount?.Id : null, IsCsv ? BuildMapping() : null, dryRun, cancellationToken);

    private CsvMapping BuildMapping() => new(
        DateColumn!,
        DateFormat,
        DescriptionColumn!,
        AmountColumn,
        DebitColumn,
        CreditColumn,
        CategoryColumn,
        _probe?.Delimiter ?? ",",
        DecimalSeparator,
        InvertSign);

    private string? ValidateInputs()
    {
        if (NeedsAccount && SelectedAccount is null)
        {
            return "Choose the account these transactions belong to.";
        }

        if (!IsCsv)
        {
            return null;
        }

        if (string.IsNullOrEmpty(DateColumn))
        {
            return "Choose which column holds the date.";
        }

        if (string.IsNullOrEmpty(DescriptionColumn))
        {
            return "Choose which column holds the description.";
        }

        var hasAmount = !string.IsNullOrEmpty(AmountColumn);
        var hasSplit = !string.IsNullOrEmpty(DebitColumn) || !string.IsNullOrEmpty(CreditColumn);
        if (hasAmount == hasSplit)
        {
            return hasAmount
                ? "Use either one Amount column or Debit/Credit columns, not both."
                : "Choose the Amount column, or the Debit and Credit columns.";
        }

        return null;
    }

    private void SetGuess(CsvGuess guess)
    {
        _dateColumn = guess.Date;
        _descriptionColumn = guess.Description;
        _amountColumn = guess.Amount;
        _debitColumn = guess.Debit;
        _creditColumn = guess.Credit;
        _categoryColumn = guess.Category;
        _dateFormat = guess.DateFormat;
        _decimalSeparator = guess.DecimalSeparator;
        DateFormatIsAmbiguous = guess.DateFormatIsAmbiguous;
        foreach (var name in new[]
        {
            nameof(DateColumn), nameof(DescriptionColumn), nameof(AmountColumn), nameof(DebitColumn),
            nameof(CreditColumn), nameof(CategoryColumn), nameof(DateFormat), nameof(DecimalSeparator),
        })
        {
            RaisePropertyChanged(name);
        }
    }

    private void ChangeInput<T>(ref T field, T value, [System.Runtime.CompilerServices.CallerMemberName] string? name = null)
    {
        if (SetProperty(ref field, value, name))
        {
            // Any change after a check makes that report stale: the person must check again.
            if (Report is not null)
            {
                Report = null;
                ReportRows.Clear();
            }

            Error = null;
        }
    }
}
