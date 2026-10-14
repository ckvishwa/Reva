namespace Reva.Desktop.Finance;

/// <summary>Everything the Finance and Today screens need from REVA Core. The UI never touches a
/// database: all Finance data comes through Core's /v1/domains/finance/* and /v1/today routes.
/// Every method is asynchronous so the UI thread never blocks on I/O (AR-WIN-003).</summary>
public interface IFinanceApi
{
    Task<FinanceResult<IReadOnlyList<AccountBalance>>> GetBalancesAsync(CancellationToken cancellationToken = default);

    Task<FinanceResult<IReadOnlyList<FinanceCategory>>> GetCategoriesAsync(CancellationToken cancellationToken = default);

    /// <summary>Newest first. <paramref name="search"/> matches description, merchant and notes.</summary>
    Task<FinanceResult<IReadOnlyList<FinanceTransaction>>> GetTransactionsAsync(
        string? search, int limit, CancellationToken cancellationToken = default);

    /// <summary><paramref name="month"/> is <c>this_month</c> or <c>last_month</c>.</summary>
    Task<FinanceResult<IReadOnlyList<BudgetStatus>>> GetBudgetStatusAsync(
        string month, CancellationToken cancellationToken = default);

    Task<FinanceResult<IReadOnlyList<FinanceBill>>> GetBillsAsync(CancellationToken cancellationToken = default);

    Task<FinanceResult<IReadOnlyList<NetWorthSnapshot>>> GetNetWorthSnapshotsAsync(
        CancellationToken cancellationToken = default);

    Task<FinanceResult<CommitResponse>> TakeNetWorthSnapshotAsync(CancellationToken cancellationToken = default);

    Task<FinanceResult<IReadOnlyList<FinanceConflict>>> GetConflictsAsync(CancellationToken cancellationToken = default);

    /// <summary>Keep this PC's value (<paramref name="keepLocal"/>) or the phone's.</summary>
    Task<FinanceResult<CommitResponse>> ResolveConflictAsync(
        long conflictId, bool keepLocal, CancellationToken cancellationToken = default);

    Task<FinanceResult<PrivacySettings>> GetPrivacyAsync(CancellationToken cancellationToken = default);

    Task<FinanceResult<PrivacySettings>> SetPrivacyAsync(
        bool? sync, bool? hostedModelAccess, CancellationToken cancellationToken = default);

    Task<FinanceResult<CommitResponse>> AddAccountAsync(
        NewAccountRequest request, CancellationToken cancellationToken = default);

    Task<FinanceResult<CommitResponse>> AddTransactionAsync(
        NewTransactionRequest request, CancellationToken cancellationToken = default);

    /// <summary>Import a CSV/OFX/JSON file. With <paramref name="dryRun"/> nothing is committed and
    /// the report says what would happen to every row.</summary>
    Task<FinanceResult<ImportReport>> ImportAsync(
        string format, byte[] data, string? accountId, CsvMapping? mapping, bool dryRun,
        CancellationToken cancellationToken = default);

    /// <summary><paramref name="format"/> is <c>csv</c> or <c>json</c>.</summary>
    Task<FinanceResult<byte[]>> ExportAsync(string format, CancellationToken cancellationToken = default);

    Task<FinanceResult<TodaySummary>> GetTodayAsync(CancellationToken cancellationToken = default);
}
