using System.Collections.ObjectModel;
using Reva.Desktop.Finance;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Backs the Finance page. All data comes through <see cref="IFinanceApi"/> (REVA Core); this class
/// has no database access and no WinUI types. Every call is awaited, so the UI thread never blocks
/// (AR-WIN-003). A newer refresh or search supersedes an older one, so a slow response can never
/// overwrite fresher data.
/// </summary>
public sealed class FinanceViewModel : ObservableObject
{
    public const string ThisMonth = "this_month";
    public const string LastMonth = "last_month";
    public const int TransactionLimit = 100;

    /// <summary>The fixed note under the page title. It is a statement about what REVA does not do,
    /// not a setting.</summary>
    public const string NoMoneyMovementNote =
        "REVA records and analyses money. It can't pay, transfer, buy or log in to a bank — those actions don't exist.";

    public const string HeaderCaption = "Encrypted on this PC · stays on this device until you pair a phone";

    private readonly IFinanceApi _api;
    private readonly Func<DateOnly> _today;
    private int _refreshGeneration;
    private int _searchGeneration;
    private int _privacyGeneration;
    private bool _suppressPrivacyWrite;

    private bool _isLoading;
    private bool _isLocked;
    private bool _hasLoaded;
    private string? _errorMessage;
    private string _searchText = string.Empty;
    private string _budgetPeriod = ThisMonth;
    private ConflictBannerViewModel? _conflict;
    private NetWorthCardViewModel _netWorth;
    private bool _syncEnabled = true;
    private bool _hostedModelEnabled;
    private string? _privacyMessage;
    private bool _isBusy;
    private IReadOnlyList<AccountBalance> _balances = Array.Empty<AccountBalance>();
    private IReadOnlyList<FinanceCategory> _categories = Array.Empty<FinanceCategory>();

    public FinanceViewModel(IFinanceApi api, Func<DateOnly>? today = null)
    {
        _api = api;
        _today = today ?? (() => DateOnly.FromDateTime(DateTime.Now));
        _netWorth = new NetWorthCardViewModel(null, _today());
    }

    public ObservableCollection<AccountCardViewModel> Accounts { get; } = new();

    public ObservableCollection<BudgetRowViewModel> Budgets { get; } = new();

    public ObservableCollection<BillRowViewModel> Bills { get; } = new();

    public ObservableCollection<TransactionRowViewModel> Transactions { get; } = new();

    public IReadOnlyList<string> BudgetPeriods { get; } = new[] { "This month", "Last month" };

    public bool IsLoading
    {
        get => _isLoading;
        private set => SetProperty(ref _isLoading, value);
    }

    /// <summary>True once the first refresh has finished, whether or not it succeeded.</summary>
    public bool HasLoaded
    {
        get => _hasLoaded;
        private set
        {
            if (SetProperty(ref _hasLoaded, value))
            {
                RaisePropertyChanged(nameof(ShowEmptyState));
            }
        }
    }

    /// <summary>The Finance file is locked (no key), or Core cannot serve Finance.</summary>
    public bool IsLocked
    {
        get => _isLocked;
        private set => SetProperty(ref _isLocked, value);
    }

    /// <summary>Safe, display-ready text for the last failure; null when everything loaded.</summary>
    public string? ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (SetProperty(ref _errorMessage, value))
            {
                RaisePropertyChanged(nameof(HasError));
            }
        }
    }

    public bool HasError => !string.IsNullOrEmpty(ErrorMessage);

    /// <summary>No accounts yet and nothing is wrong: the page offers "Add account".</summary>
    public bool ShowEmptyState => HasLoaded && !HasError && Accounts.Count == 0;

    public bool HasAccounts => Accounts.Count > 0;

    public bool IsBusy
    {
        get => _isBusy;
        private set => SetProperty(ref _isBusy, value);
    }

    public string SearchText
    {
        get => _searchText;
        set => SetProperty(ref _searchText, value);
    }

    public string BudgetPeriod
    {
        get => _budgetPeriod;
        private set => SetProperty(ref _budgetPeriod, value);
    }

    public NetWorthCardViewModel NetWorth
    {
        get => _netWorth;
        private set => SetProperty(ref _netWorth, value);
    }

    public ConflictBannerViewModel? Conflict
    {
        get => _conflict;
        private set
        {
            if (SetProperty(ref _conflict, value))
            {
                RaisePropertyChanged(nameof(HasConflict));
            }
        }
    }

    public bool HasConflict => Conflict is not null;

    /// <summary>"Sync Finance to paired phone". Changing it saves through Core; if saving fails the
    /// switch goes back and <see cref="PrivacyMessage"/> says why.</summary>
    public bool SyncEnabled
    {
        get => _syncEnabled;
        set => SetPrivacySwitch(ref _syncEnabled, value, sync: true);
    }

    /// <summary>"Let a cloud model see Finance data". Off by default (ARD-700 section 4).</summary>
    public bool HostedModelEnabled
    {
        get => _hostedModelEnabled;
        set => SetPrivacySwitch(ref _hostedModelEnabled, value, sync: false);
    }

    public string? PrivacyMessage
    {
        get => _privacyMessage;
        private set => SetProperty(ref _privacyMessage, value);
    }

    /// <summary>Completes when the last privacy change has been saved (or reverted). For tests and shutdown.</summary>
    public Task PendingPrivacyChange { get; private set; } = Task.CompletedTask;

    public bool HasTransactions => Transactions.Count > 0;

    public string TransactionsEmptyText => string.IsNullOrWhiteSpace(SearchText)
        ? "No transactions yet."
        : "No transactions match that search.";

    // ------------------------------------------------------------------------------------------

    /// <summary>Loads everything on the page. Safe to call again; the newest call wins.</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        var generation = Interlocked.Increment(ref _refreshGeneration);
        IsLoading = true;
        try
        {
            var balances = _api.GetBalancesAsync(cancellationToken);
            var categories = _api.GetCategoriesAsync(cancellationToken);
            var transactions = _api.GetTransactionsAsync(SearchText, TransactionLimit, cancellationToken);
            var budgets = _api.GetBudgetStatusAsync(BudgetPeriod, cancellationToken);
            var bills = _api.GetBillsAsync(cancellationToken);
            var snapshots = _api.GetNetWorthSnapshotsAsync(cancellationToken);
            var conflicts = _api.GetConflictsAsync(cancellationToken);
            var privacy = _api.GetPrivacyAsync(cancellationToken);
            await Task.WhenAll(balances, categories, transactions, budgets, bills, snapshots, conflicts, privacy)
                .ConfigureAwait(true);
            if (generation != Volatile.Read(ref _refreshGeneration))
            {
                return;
            }

            var firstError = new FinanceError?[]
            {
                balances.Result.Error, categories.Result.Error, transactions.Result.Error, budgets.Result.Error,
                bills.Result.Error, snapshots.Result.Error, conflicts.Result.Error, privacy.Result.Error,
            }.FirstOrDefault(e => e is not null);

            var today = _today();
            if (balances.Result.IsSuccess)
            {
                _balances = balances.Result.Value!;
                Replace(Accounts, _balances.Where(b => !b.Archived).Select(b => new AccountCardViewModel(b)));
                RaisePropertyChanged(nameof(HasAccounts));
            }

            if (categories.Result.IsSuccess)
            {
                _categories = categories.Result.Value!;
            }

            if (transactions.Result.IsSuccess)
            {
                ApplyTransactions(transactions.Result.Value!, today);
            }

            if (budgets.Result.IsSuccess)
            {
                Replace(Budgets, budgets.Result.Value!.Select(b => new BudgetRowViewModel(b)));
            }

            if (bills.Result.IsSuccess)
            {
                Replace(Bills, bills.Result.Value!.Select(b => new BillRowViewModel(b, today)));
            }

            if (snapshots.Result.IsSuccess)
            {
                var latest = snapshots.Result.Value!.OrderBy(s => s.AsOf, StringComparer.Ordinal).LastOrDefault();
                NetWorth = new NetWorthCardViewModel(latest, today);
            }

            if (conflicts.Result.IsSuccess)
            {
                var first = conflicts.Result.Value!.FirstOrDefault();
                Conflict = first is null ? null : new ConflictBannerViewModel(first);
            }

            if (privacy.Result.IsSuccess)
            {
                ApplyPrivacy(privacy.Result.Value!);
            }

            IsLocked = firstError?.Kind is FinanceErrorKind.Locked;
            ErrorMessage = firstError?.SafeMessage;
            HasLoaded = true;
            RaisePropertyChanged(nameof(ShowEmptyState));
        }
        finally
        {
            if (generation == Volatile.Read(ref _refreshGeneration))
            {
                IsLoading = false;
            }
        }
    }

    /// <summary>Re-runs the transaction search with <see cref="SearchText"/>.</summary>
    public async Task SearchAsync(CancellationToken cancellationToken = default)
    {
        var generation = Interlocked.Increment(ref _searchGeneration);
        var result = await _api.GetTransactionsAsync(SearchText, TransactionLimit, cancellationToken).ConfigureAwait(true);
        if (generation != Volatile.Read(ref _searchGeneration))
        {
            return;
        }

        if (result.IsSuccess)
        {
            ApplyTransactions(result.Value!, _today());
            ErrorMessage = null;
        }
        else
        {
            ErrorMessage = result.Error!.SafeMessage;
        }
    }

    public async Task SetBudgetPeriodAsync(string period, CancellationToken cancellationToken = default)
    {
        if (period is not (ThisMonth or LastMonth))
        {
            return;
        }

        BudgetPeriod = period;
        var result = await _api.GetBudgetStatusAsync(period, cancellationToken).ConfigureAwait(true);
        if (period != BudgetPeriod)
        {
            return;
        }

        if (result.IsSuccess)
        {
            Replace(Budgets, result.Value!.Select(b => new BudgetRowViewModel(b)));
        }
        else
        {
            ErrorMessage = result.Error!.SafeMessage;
        }
    }

    public async Task TakeSnapshotAsync(CancellationToken cancellationToken = default)
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var made = await _api.TakeNetWorthSnapshotAsync(cancellationToken).ConfigureAwait(true);
            if (!made.IsSuccess)
            {
                ErrorMessage = made.Error!.SafeMessage;
                return;
            }

            var snapshots = await _api.GetNetWorthSnapshotsAsync(cancellationToken).ConfigureAwait(true);
            if (snapshots.IsSuccess)
            {
                NetWorth = new NetWorthCardViewModel(
                    snapshots.Value!.OrderBy(s => s.AsOf, StringComparer.Ordinal).LastOrDefault(), _today());
            }
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Keep this PC's amount (<paramref name="keepLocal"/>) or the phone's.</summary>
    public async Task ResolveConflictAsync(bool keepLocal, CancellationToken cancellationToken = default)
    {
        var conflict = Conflict;
        if (conflict is null || IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _api.ResolveConflictAsync(conflict.Id, keepLocal, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                return;
            }
        }
        finally
        {
            IsBusy = false;
        }

        await RefreshAsync(cancellationToken).ConfigureAwait(true);
    }

    public async Task<FinanceResult<byte[]>> ExportAsync(string format, CancellationToken cancellationToken = default)
    {
        IsBusy = true;
        try
        {
            return await _api.ExportAsync(format, cancellationToken).ConfigureAwait(true);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public AddTransactionViewModel NewAddTransaction() =>
        new(_api, _balances.Where(b => !b.Archived).ToList(), _categories, _today());

    public AddAccountViewModel NewAddAccount() => new(_api);

    public ImportViewModel NewImport() => new(_api, _balances.Where(b => !b.Archived).ToList());

    // ------------------------------------------------------------------------------------------

    private void ApplyTransactions(IReadOnlyList<FinanceTransaction> items, DateOnly today)
    {
        var accountNames = _balances.ToDictionary(b => b.AccountId, b => b.Name);
        var categoryNames = _categories.ToDictionary(c => c.Id, c => c.Name);
        Replace(
            Transactions,
            items.Select(t => new TransactionRowViewModel(
                t,
                accountNames.GetValueOrDefault(t.AccountId, "Account"),
                t.CategoryId is not null ? categoryNames.GetValueOrDefault(t.CategoryId, "Category") : "Uncategorized",
                today)));
        RaisePropertyChanged(nameof(HasTransactions));
        RaisePropertyChanged(nameof(TransactionsEmptyText));
    }

    private void ApplyPrivacy(PrivacySettings privacy)
    {
        _suppressPrivacyWrite = true;
        try
        {
            if (SetProperty(ref _syncEnabled, privacy.Sync, nameof(SyncEnabled)))
            {
                // property change already raised
            }

            SetProperty(ref _hostedModelEnabled, privacy.HostedModelAccess, nameof(HostedModelEnabled));
        }
        finally
        {
            _suppressPrivacyWrite = false;
        }
    }

    private bool SetPrivacySwitch(ref bool field, bool value, bool sync, [System.Runtime.CompilerServices.CallerMemberName] string? name = null)
    {
        if (field == value)
        {
            return false;
        }

        var previous = field;
        field = value;
        RaisePropertyChanged(name);
        if (_suppressPrivacyWrite)
        {
            return true;
        }

        PendingPrivacyChange = SavePrivacyAsync(sync, value, previous);
        return true;
    }

    private async Task SavePrivacyAsync(bool sync, bool value, bool previous)
    {
        var generation = Interlocked.Increment(ref _privacyGeneration);
        PrivacyMessage = null;
        var result = await (sync ? _api.SetPrivacyAsync(value, null) : _api.SetPrivacyAsync(null, value)).ConfigureAwait(true);
        if (generation != Volatile.Read(ref _privacyGeneration))
        {
            return;
        }

        if (result.IsSuccess)
        {
            ApplyPrivacy(result.Value!);
            return;
        }

        _suppressPrivacyWrite = true;
        try
        {
            if (sync)
            {
                SetProperty(ref _syncEnabled, previous, nameof(SyncEnabled));
            }
            else
            {
                SetProperty(ref _hostedModelEnabled, previous, nameof(HostedModelEnabled));
            }
        }
        finally
        {
            _suppressPrivacyWrite = false;
        }

        PrivacyMessage = "Couldn't save that privacy choice. It is unchanged.";
    }

    private static void Replace<T>(ObservableCollection<T> target, IEnumerable<T> items)
    {
        target.Clear();
        foreach (var item in items)
        {
            target.Add(item);
        }
    }
}
