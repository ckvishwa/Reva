using Reva.Desktop.Finance;

namespace Reva.Desktop.ViewModels;

/// <summary>One account card in the strip at the top of Finance.</summary>
public sealed class AccountCardViewModel
{
    public AccountCardViewModel(AccountBalance balance)
    {
        AccountId = balance.AccountId;
        Title = balance.Name;
        Currency = balance.Currency;
        BalanceMinor = balance.BalanceMinor;
        BalanceText = MoneyFormat.Format(balance.BalanceMinor, balance.Currency);
        Caption = $"{FinanceDisplay.AccountKindLabel(balance.Kind)} · {balance.Currency}";
        AccessibleName = $"{Title}, {FinanceDisplay.AccountKindLabel(balance.Kind)}, balance {BalanceText}";
    }

    public string AccountId { get; }

    public string Title { get; }

    public string Currency { get; }

    public long BalanceMinor { get; }

    public string BalanceText { get; }

    public string Caption { get; }

    public string AccessibleName { get; }
}

/// <summary>The "Net worth snapshot" card: the latest snapshot, one line per currency.</summary>
public sealed class NetWorthCardViewModel
{
    public NetWorthCardViewModel(NetWorthSnapshot? snapshot, DateOnly today)
    {
        if (snapshot is null || snapshot.ByCurrency.Count == 0)
        {
            ValueText = "No snapshot yet";
            Caption = "Take one to record today's net worth";
            HasSnapshot = false;
        }
        else
        {
            ValueText = string.Join(
                " · ",
                snapshot.ByCurrency.OrderBy(e => e.Key, StringComparer.Ordinal)
                    .Select(e => MoneyFormat.Format(e.Value.NetMinor, e.Key)));
            Caption = $"Taken {FinanceDisplay.ShortDate(snapshot.AsOf, today)}";
            HasSnapshot = true;
        }

        AccessibleName = $"Net worth snapshot, {ValueText}, {Caption}";
    }

    public bool HasSnapshot { get; }

    public string ValueText { get; }

    public string Caption { get; }

    public string AccessibleName { get; }
}

public sealed class BudgetRowViewModel
{
    public BudgetRowViewModel(BudgetStatus status)
    {
        Name = status.Category ?? "Budget";
        AmountsText = $"{MoneyFormat.Format(status.SpentMinor, status.Currency)} / {MoneyFormat.Format(status.BudgetMinor, status.Currency)}";
        Fraction = FinanceDisplay.BarFraction(status.UsedBasisPoints);
        IsNearLimit = FinanceDisplay.IsNearLimit(status.UsedBasisPoints);
        IsOver = status.OverBudget;
        Percent = FinanceDisplay.Percent(status.UsedBasisPoints);
        AccessibleName = status.OverBudget
            ? $"{Name}: {AmountsText}, over budget by {MoneyFormat.Format(-status.RemainingMinor, status.Currency)}"
            : $"{Name}: {AmountsText}, {Percent} percent used";
    }

    public string Name { get; }

    public string AmountsText { get; }

    /// <summary>0 to 1, how much of the bar to fill.</summary>
    public double Fraction { get; }

    public bool IsNearLimit { get; }

    public bool IsOver { get; }

    public int Percent { get; }

    public string AccessibleName { get; }
}

public sealed class BillRowViewModel
{
    public BillRowViewModel(FinanceBill bill, DateOnly today)
    {
        Name = bill.Name;
        AmountText = MoneyFormat.Format(bill.AmountMinor, bill.Currency);
        DueText = FinanceDisplay.DueText(bill, today);
        IsSoon = bill.DaysUntil is <= 7;
        IsIncome = string.Equals(bill.Kind, "income", StringComparison.Ordinal);
        AccessibleName = $"{Name}, {AmountText}, {DueText}";
    }

    public string Name { get; }

    public string AmountText { get; }

    public string DueText { get; }

    /// <summary>Due within a week (or overdue): shown in the accent colour.</summary>
    public bool IsSoon { get; }

    public bool IsIncome { get; }

    public string AccessibleName { get; }
}

public sealed class TransactionRowViewModel
{
    public TransactionRowViewModel(
        FinanceTransaction transaction, string accountName, string categoryName, DateOnly today)
    {
        Id = transaction.Id;
        DateText = FinanceDisplay.RelativeDate(transaction.Date, today);
        Description = transaction.Description;
        CategoryText = categoryName;
        AccountText = accountName;
        AmountMinor = transaction.AmountMinor;
        AmountText = MoneyFormat.Format(transaction.AmountMinor, transaction.Currency, showPlus: true);
        IsIncome = transaction.AmountMinor > 0;
        SourceText = FinanceDisplay.SourceText(transaction.SourceKind);
        AccessibleName =
            $"{DateText}, {Description}, {CategoryText}, {AccountText}, {AmountText}, source {SourceText}";
    }

    public string Id { get; }

    public string DateText { get; }

    public string Description { get; }

    public string CategoryText { get; }

    public string AccountText { get; }

    public long AmountMinor { get; }

    public string AmountText { get; }

    public bool IsIncome { get; }

    public string SourceText { get; }

    public string AccessibleName { get; }
}

/// <summary>The sync-conflict banner: the same transaction has two different amounts, one per device.</summary>
public sealed class ConflictBannerViewModel
{
    public ConflictBannerViewModel(FinanceConflict conflict)
    {
        Id = conflict.Id;
        var currency = conflict.Currency ?? "USD";
        var label = string.IsNullOrWhiteSpace(conflict.Label) ? "This record" : conflict.Label!;
        var local = FormatValue(conflict.LocalValue, currency);
        var remote = FormatValue(conflict.RemoteValue, currency);
        LocalText = local;
        RemoteText = remote;
        Message = $"{label} was {local} on this PC and {remote} on your phone. Which is right?";
    }

    public long Id { get; }

    public string Message { get; }

    public string LocalText { get; }

    public string RemoteText { get; }

    private static string FormatValue(string raw, string currency) =>
        long.TryParse(raw, System.Globalization.NumberStyles.AllowLeadingSign, System.Globalization.CultureInfo.InvariantCulture, out var minor)
            ? MoneyFormat.Format(minor, currency)
            : raw;
}
