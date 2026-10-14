using Reva.Desktop.Finance;

namespace Reva.Desktop.Tests.Finance;

internal static class TestData
{
    public static readonly DateOnly Today = new(2026, 10, 12);

    public static AccountBalance Checking() => new("acct-checking", "Checking", "checking", "USD", false, 660_500);

    public static AccountBalance Card() => new("acct-card", "Credit card", "credit", "USD", false, -22_849);

    public static FinanceCategory Dining() => new("cat-dining", "Food · Dining", "expense", new[] { "lunch" });

    public static FinanceCategory Groceries() => new("cat-groceries", "Groceries", "expense", Array.Empty<string>());

    public static FinanceTransaction Tx(
        string id, string date, long amount, string description, string? sourceKind = "manual",
        string account = "acct-card", string? category = "cat-dining") =>
        new(id, account, date, amount, "USD", description, null, category, null, sourceKind, sourceKind);

    public static BudgetStatus Budget(string name, long budget, long spent, long usedBp, bool over = false) =>
        new("bud-" + name, "cat-" + name, name, "USD", "2026-10", budget, spent, budget - spent, usedBp, over, 19);

    public static FinanceBill Bill(string name, string due, int? daysUntil, string kind = "bill", bool overdue = false) =>
        new("bill-" + name, name, kind, 120_000, "USD", "monthly", due, true, daysUntil, overdue);

    public static FakeFinanceApi PopulatedApi()
    {
        var api = new FakeFinanceApi();
        api.Balances.AddRange(new[] { Checking(), Card() });
        api.Categories.AddRange(new[] { Dining(), Groceries() });
        api.Transactions.AddRange(new[]
        {
            Tx("tx-1", "2026-10-12", -1200, "Lunch", "voice"),
            Tx("tx-2", "2026-10-11", -8450, "Market", "csv"),
            Tx("tx-3", "2026-10-09", -2300, "Taxi", "phone"),
            Tx("tx-4", "2026-10-01", 300_000, "Paycheck", "manual", "acct-checking", null),
        });
        api.Budgets.AddRange(new[]
        {
            Budget("Dining", 20_000, 5_800, 2_900),
            Budget("Groceries", 50_000, 47_000, 9_400),
        });
        api.Bills.AddRange(new[]
        {
            Bill("Rent", "2026-10-14", 2),
            Bill("Streaming", "2026-11-02", 21, "subscription"),
        });
        api.Snapshots.Add(new NetWorthSnapshot(
            "nw-1", "2026-10-12",
            new Dictionary<string, NetWorthEntry> { ["USD"] = new(660_500, 22_849, 637_651) }));
        return api;
    }
}
