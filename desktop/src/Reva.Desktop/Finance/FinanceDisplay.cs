using System.Globalization;

namespace Reva.Desktop.Finance;

/// <summary>Text the Finance screens show, kept out of XAML so it can be unit tested.</summary>
public static class FinanceDisplay
{
    private static readonly CultureInfo Invariant = CultureInfo.InvariantCulture;

    public static bool TryParseDate(string? iso, out DateOnly date) =>
        DateOnly.TryParseExact(iso, "yyyy-MM-dd", Invariant, DateTimeStyles.None, out date);

    /// <summary>"Today", "Yesterday", otherwise "Oct 11" (with the year when it is not this year).</summary>
    public static string RelativeDate(string? iso, DateOnly today)
    {
        if (!TryParseDate(iso, out var date))
        {
            return iso ?? string.Empty;
        }

        if (date == today)
        {
            return "Today";
        }

        if (date == today.AddDays(-1))
        {
            return "Yesterday";
        }

        return date.Year == today.Year
            ? date.ToString("MMM d", Invariant)
            : date.ToString("MMM d, yyyy", Invariant);
    }

    public static string ShortDate(string? iso, DateOnly today)
    {
        if (!TryParseDate(iso, out var date))
        {
            return iso ?? string.Empty;
        }

        return date.Year == today.Year ? date.ToString("MMM d", Invariant) : date.ToString("MMM d, yyyy", Invariant);
    }

    /// <summary>"Due Oct 14", "Renews Dec 20" (subscriptions), "Overdue since Oct 10", "Expected Nov 1" (income).</summary>
    public static string DueText(FinanceBill bill, DateOnly today)
    {
        var date = ShortDate(bill.DueDate, today);
        if (bill.Overdue == true && !string.Equals(bill.Kind, "income", StringComparison.Ordinal))
        {
            return $"Overdue since {date}";
        }

        return bill.Kind switch
        {
            "subscription" => $"Renews {date}",
            "income" => $"Expected {date}",
            _ => $"Due {date}",
        };
    }

    /// <summary>Where a transaction came from, as the table's Source column shows it.</summary>
    public static string SourceText(string? sourceKind) => sourceKind switch
    {
        "voice" => "voice · confirmed",
        "csv" => "csv import",
        "ofx" => "ofx import",
        "json" => "restored from export",
        "import" => "import",
        "phone" => "phone · synced",
        _ => "manual",
    };

    public static string AccountKindLabel(string kind) => kind switch
    {
        "checking" => "Checking",
        "savings" => "Savings",
        "credit" => "Credit card",
        "cash" => "Cash",
        "investment" => "Investment",
        "loan" => "Loan",
        _ => "Account",
    };

    public static int Percent(long usedBasisPoints) => (int)Math.Clamp(usedBasisPoints / 100, 0, 999);

    /// <summary>The share of the bar to fill, 0 to 1 (a budget that is over the limit fills the bar).</summary>
    public static double BarFraction(long usedBasisPoints) => Math.Clamp(usedBasisPoints / 10_000.0, 0.0, 1.0);

    /// <summary>Bars past 90% of the limit turn light orange (design rule).</summary>
    public static bool IsNearLimit(long usedBasisPoints) => usedBasisPoints > 9_000;
}
