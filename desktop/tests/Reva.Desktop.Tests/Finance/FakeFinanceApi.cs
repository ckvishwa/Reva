using Reva.Desktop.Finance;

namespace Reva.Desktop.Tests.Finance;

/// <summary>An in-memory <see cref="IFinanceApi"/> for view-model tests. Records every call; a call
/// fails with <see cref="Failures"/>[name] when set, and <see cref="Gate"/> holds every call open
/// until released (to prove the view models await instead of blocking).</summary>
internal sealed class FakeFinanceApi : IFinanceApi
{
    public List<AccountBalance> Balances { get; set; } = new();

    public List<FinanceCategory> Categories { get; set; } = new();

    public List<FinanceTransaction> Transactions { get; set; } = new();

    public List<BudgetStatus> Budgets { get; set; } = new();

    public List<FinanceBill> Bills { get; set; } = new();

    public List<NetWorthSnapshot> Snapshots { get; set; } = new();

    public List<FinanceConflict> Conflicts { get; set; } = new();

    public PrivacySettings Privacy { get; set; } = new(true, false);

    public TodaySummary Today { get; set; } = new("2026-10-12", new TodayDomains(new TodayFinance(
        new List<TodayBudgetLeft>(), new List<FinanceBill>())));

    public Dictionary<string, FinanceError> Failures { get; } = new();

    public TaskCompletionSource? Gate { get; set; }

    public List<string> Calls { get; } = new();

    public List<NewTransactionRequest> AddedTransactions { get; } = new();

    public List<NewAccountRequest> AddedAccounts { get; } = new();

    public List<(string Format, bool DryRun, string? AccountId, CsvMapping? Mapping)> Imports { get; } = new();

    public Func<bool, ImportReport> ImportResponder { get; set; } = dryRun => new ImportReport(
        0, 0, Array.Empty<ImportRejected>(), Array.Empty<ImportRow>(), dryRun, "BATCH");

    public Func<string, FinanceResult<byte[]>> ExportResponder { get; set; } =
        _ => FinanceResult<byte[]>.Success(new byte[] { 1, 2, 3 });

    public List<(bool? Sync, bool? Hosted)> PrivacyWrites { get; } = new();

    public List<(long Id, bool KeepLocal)> Resolutions { get; } = new();

    private async Task<FinanceResult<T>> Run<T>(string name, Func<T> value, CancellationToken ct)
    {
        Calls.Add(name);
        if (Gate is not null)
        {
            await Gate.Task.WaitAsync(ct);
        }

        return Failures.TryGetValue(name.Split(':')[0], out var error)
            ? FinanceResult<T>.Failure(error)
            : FinanceResult<T>.Success(value());
    }

    public Task<FinanceResult<IReadOnlyList<AccountBalance>>> GetBalancesAsync(CancellationToken ct = default) =>
        Run<IReadOnlyList<AccountBalance>>("GetBalances", () => Balances.ToList(), ct);

    public Task<FinanceResult<IReadOnlyList<FinanceCategory>>> GetCategoriesAsync(CancellationToken ct = default) =>
        Run<IReadOnlyList<FinanceCategory>>("GetCategories", () => Categories.ToList(), ct);

    public Task<FinanceResult<IReadOnlyList<FinanceTransaction>>> GetTransactionsAsync(
        string? search, int limit, CancellationToken ct = default) =>
        Run<IReadOnlyList<FinanceTransaction>>(
            $"GetTransactions:q={search}",
            () => Transactions
                .Where(t => string.IsNullOrWhiteSpace(search)
                    || t.Description.Contains(search, StringComparison.OrdinalIgnoreCase))
                .Take(limit).ToList(),
            ct);

    public Task<FinanceResult<IReadOnlyList<BudgetStatus>>> GetBudgetStatusAsync(string month, CancellationToken ct = default) =>
        Run<IReadOnlyList<BudgetStatus>>($"GetBudgetStatus:{month}", () => Budgets.ToList(), ct);

    public Task<FinanceResult<IReadOnlyList<FinanceBill>>> GetBillsAsync(CancellationToken ct = default) =>
        Run<IReadOnlyList<FinanceBill>>("GetBills", () => Bills.ToList(), ct);

    public Task<FinanceResult<IReadOnlyList<NetWorthSnapshot>>> GetNetWorthSnapshotsAsync(CancellationToken ct = default) =>
        Run<IReadOnlyList<NetWorthSnapshot>>("GetNetWorthSnapshots", () => Snapshots.ToList(), ct);

    public Task<FinanceResult<CommitResponse>> TakeNetWorthSnapshotAsync(CancellationToken ct = default) =>
        Run("TakeNetWorthSnapshot", () => new CommitResponse("E", "nw-new-0001", 1), ct);

    public Task<FinanceResult<IReadOnlyList<FinanceConflict>>> GetConflictsAsync(CancellationToken ct = default) =>
        Run<IReadOnlyList<FinanceConflict>>("GetConflicts", () => Conflicts.ToList(), ct);

    public Task<FinanceResult<CommitResponse>> ResolveConflictAsync(long conflictId, bool keepLocal, CancellationToken ct = default)
    {
        Resolutions.Add((conflictId, keepLocal));
        return Run(
            "ResolveConflict",
            () =>
            {
                Conflicts.RemoveAll(c => c.Id == conflictId);
                return new CommitResponse("E", "x", 2);
            },
            ct);
    }

    public Task<FinanceResult<PrivacySettings>> GetPrivacyAsync(CancellationToken ct = default) =>
        Run("GetPrivacy", () => Privacy, ct);

    public Task<FinanceResult<PrivacySettings>> SetPrivacyAsync(bool? sync, bool? hostedModelAccess, CancellationToken ct = default)
    {
        PrivacyWrites.Add((sync, hostedModelAccess));
        return Run(
            "SetPrivacy",
            () =>
            {
                Privacy = new PrivacySettings(sync ?? Privacy.Sync, hostedModelAccess ?? Privacy.HostedModelAccess);
                return Privacy;
            },
            ct);
    }

    public Task<FinanceResult<CommitResponse>> AddAccountAsync(NewAccountRequest request, CancellationToken ct = default)
    {
        AddedAccounts.Add(request);
        return Run("AddAccount", () => new CommitResponse("E", "acct-new-0001", 1), ct);
    }

    public Task<FinanceResult<CommitResponse>> AddTransactionAsync(NewTransactionRequest request, CancellationToken ct = default)
    {
        AddedTransactions.Add(request);
        return Run("AddTransaction", () => new CommitResponse("E", "tx-new-00001", 1), ct);
    }

    public Task<FinanceResult<ImportReport>> ImportAsync(
        string format, byte[] data, string? accountId, CsvMapping? mapping, bool dryRun, CancellationToken ct = default)
    {
        Imports.Add((format, dryRun, accountId, mapping));
        return Run($"Import:dry={dryRun}", () => ImportResponder(dryRun), ct);
    }

    public Task<FinanceResult<byte[]>> ExportAsync(string format, CancellationToken ct = default) =>
        Run($"Export:{format}", () => ExportResponder(format).Value!, ct);

    public Task<FinanceResult<TodaySummary>> GetTodayAsync(CancellationToken ct = default) =>
        Run("GetToday", () => Today, ct);
}
