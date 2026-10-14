using System.Text.Json.Serialization;

namespace Reva.Desktop.Finance;

// Mirrors the JSON of REVA Core's /v1/domains/finance/* and /v1/today (reva_core/domains/routes.py).
// Field names are Core's snake_case. Money is always an integer count of minor units plus a currency code.

public sealed record FinanceAccount(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("opening_balance_minor")] long OpeningBalanceMinor,
    [property: JsonPropertyName("archived")] bool Archived);

public sealed record AccountBalance(
    [property: JsonPropertyName("account_id")] string AccountId,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("archived")] bool Archived,
    [property: JsonPropertyName("balance_minor")] long BalanceMinor);

public sealed record FinanceCategory(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("aliases")] IReadOnlyList<string>? Aliases);

public sealed record FinanceTransaction(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("account_id")] string AccountId,
    [property: JsonPropertyName("date")] string Date,
    [property: JsonPropertyName("amount_minor")] long AmountMinor,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("merchant")] string? Merchant,
    [property: JsonPropertyName("category_id")] string? CategoryId,
    [property: JsonPropertyName("notes")] string? Notes,
    [property: JsonPropertyName("source")] string? Source,
    [property: JsonPropertyName("source_kind")] string? SourceKind);

public sealed record BudgetStatus(
    [property: JsonPropertyName("budget_id")] string BudgetId,
    [property: JsonPropertyName("category_id")] string CategoryId,
    [property: JsonPropertyName("category")] string? Category,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("month")] string Month,
    [property: JsonPropertyName("budget_minor")] long BudgetMinor,
    [property: JsonPropertyName("spent_minor")] long SpentMinor,
    [property: JsonPropertyName("remaining_minor")] long RemainingMinor,
    [property: JsonPropertyName("used_basis_points")] long UsedBasisPoints,
    [property: JsonPropertyName("over_budget")] bool OverBudget,
    [property: JsonPropertyName("days_left")] int DaysLeft);

public sealed record FinanceBill(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("kind")] string Kind,
    [property: JsonPropertyName("amount_minor")] long AmountMinor,
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("recurrence")] string Recurrence,
    [property: JsonPropertyName("due_date")] string DueDate,
    [property: JsonPropertyName("active")] bool Active,
    [property: JsonPropertyName("days_until")] int? DaysUntil,
    [property: JsonPropertyName("overdue")] bool? Overdue);

public sealed record NetWorthEntry(
    [property: JsonPropertyName("assets_minor")] long AssetsMinor,
    [property: JsonPropertyName("liabilities_minor")] long LiabilitiesMinor,
    [property: JsonPropertyName("net_minor")] long NetMinor);

public sealed record NetWorthSnapshot(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("as_of")] string AsOf,
    [property: JsonPropertyName("by_currency")] IReadOnlyDictionary<string, NetWorthEntry> ByCurrency);

public sealed record FinanceConflict(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("aggregate_type")] string AggregateType,
    [property: JsonPropertyName("aggregate_id")] string AggregateId,
    [property: JsonPropertyName("field")] string Field,
    [property: JsonPropertyName("local_value")] string LocalValue,
    [property: JsonPropertyName("remote_value")] string RemoteValue,
    [property: JsonPropertyName("label")] string? Label,
    [property: JsonPropertyName("currency")] string? Currency);

public sealed record PrivacySettings(
    [property: JsonPropertyName("sync")] bool Sync,
    [property: JsonPropertyName("hosted_model_access")] bool HostedModelAccess);

public sealed record CommitResponse(
    [property: JsonPropertyName("event_id")] string EventId,
    [property: JsonPropertyName("aggregate_id")] string AggregateId,
    [property: JsonPropertyName("version")] long Version);

public sealed record ImportRow(
    [property: JsonPropertyName("row")] long Row,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("reason")] string? Reason,
    [property: JsonPropertyName("date")] string? Date,
    [property: JsonPropertyName("amount_minor")] long? AmountMinor,
    [property: JsonPropertyName("description")] string? Description,
    [property: JsonPropertyName("warning")] string? Warning,
    [property: JsonPropertyName("raw")] string? Raw);

public sealed record ImportRejected(
    [property: JsonPropertyName("row")] long Row,
    [property: JsonPropertyName("reason")] string Reason,
    [property: JsonPropertyName("raw")] string? Raw);

public sealed record ImportReport(
    [property: JsonPropertyName("accepted")] long Accepted,
    [property: JsonPropertyName("duplicates")] long Duplicates,
    [property: JsonPropertyName("rejected")] IReadOnlyList<ImportRejected> Rejected,
    [property: JsonPropertyName("rows")] IReadOnlyList<ImportRow> Rows,
    [property: JsonPropertyName("dry_run")] bool DryRun,
    [property: JsonPropertyName("batch_id")] string BatchId);

public sealed record TodayBudgetLeft(
    [property: JsonPropertyName("currency")] string Currency,
    [property: JsonPropertyName("budget_minor")] long BudgetMinor,
    [property: JsonPropertyName("spent_minor")] long SpentMinor,
    [property: JsonPropertyName("remaining_minor")] long RemainingMinor);

public sealed record TodayFinance(
    [property: JsonPropertyName("budget_left_this_month")] IReadOnlyList<TodayBudgetLeft> BudgetLeft,
    [property: JsonPropertyName("bills_due_7_days")] IReadOnlyList<FinanceBill> BillsDue);

public sealed record TodayDomains([property: JsonPropertyName("finance")] TodayFinance? Finance);

public sealed record TodaySummary(
    [property: JsonPropertyName("as_of")] string AsOf,
    [property: JsonPropertyName("domains")] TodayDomains Domains);

public sealed record FinanceListResponse<T>(
    [property: JsonPropertyName("items")] IReadOnlyList<T> Items);

public sealed record FinanceItemResponse<T>(
    [property: JsonPropertyName("item")] T Item);

public sealed record FinanceReportResponse<T>(
    [property: JsonPropertyName("rows")] IReadOnlyList<T> Rows);

public sealed record PrivacyResponse(
    [property: JsonPropertyName("privacy")] PrivacySettings Privacy);

/// <summary>What the Add transaction flow sends. Amount is signed minor units (negative = money out).</summary>
public sealed record NewTransactionRequest(
    string AccountId,
    string Date,
    long AmountMinor,
    string Description,
    string? Category,
    string? Notes);

public sealed record NewAccountRequest(string Name, string Kind, string Currency, long OpeningBalanceMinor);

/// <summary>CSV column mapping the Import flow sends (see kernel/src/import/csv_format.rs).</summary>
public sealed record CsvMapping(
    string Date,
    string DateFormat,
    string Description,
    string? Amount,
    string? Debit,
    string? Credit,
    string? Category,
    string Delimiter,
    string DecimalSeparator,
    bool InvertSign);
