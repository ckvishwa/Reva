using System.Net;
using Reva.Desktop.Finance;

namespace Reva.Desktop.Tests.Finance;

/// <summary>
/// Contract tests: the real REVA Core responses captured by tools/desktop/generate_finance_fixtures.py
/// (and kept current by tests/contract/test_finance_ui_fixtures.py) are fed through the real
/// <see cref="FinanceApiClient"/>. If Core changes a response shape, one side of this pair fails.
/// </summary>
public class FinanceContractFixtureTests
{
    private static string Fixture(string name) =>
        File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Fixtures", "finance", name + ".json"));

    private static FinanceApiClient ClientServing(params (string Contains, string Fixture)[] routes) =>
        ClientServing(HttpStatusCode.OK, routes);

    private static FinanceApiClient ClientServing(HttpStatusCode status, params (string Contains, string Fixture)[] routes)
    {
        var handler = new StubHandler
        {
            Responder = (request, _) =>
            {
                var path = request.RequestUri!.PathAndQuery;
                var route = routes.FirstOrDefault(r => path.Contains(r.Contains, StringComparison.Ordinal));
                return Task.FromResult(route.Fixture is null
                    ? StubHandler.Json(HttpStatusCode.NotFound, "{}")
                    : StubHandler.Json(status, Fixture(route.Fixture)));
            },
        };
        return new FinanceApiClient(
            new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") },
            new StubTokens(),
            TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task Account_balances_match_what_the_kernel_computed()
    {
        var result = await ClientServing(("account_balances", "balances")).GetBalancesAsync();

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var balances = result.Value!.ToDictionary(b => b.AccountId);
        Assert.Equal(3, balances.Count);
        Assert.Equal(800_750, balances["acct-checking"].BalanceMinor); // 500000 + 300000 + imported -450 and +1200
        Assert.Equal(1_500_000, balances["acct-savings"].BalanceMinor);
        Assert.Equal("credit", balances["acct-card"].Kind);
        Assert.All(balances.Values, b => Assert.Equal("USD", b.Currency));
        Assert.All(balances.Values, b => Assert.False(b.Archived));
    }

    [Fact]
    public async Task Transactions_carry_every_source_kind_the_table_shows()
    {
        var result = await ClientServing(("/transactions", "transactions")).GetTransactionsAsync(null, 100);

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var rows = result.Value!;
        Assert.Equal(6, rows.Count);
        Assert.Equal(
            new[] { "csv", "manual", "phone", "voice" },
            rows.Select(r => r.SourceKind).Distinct().OrderBy(k => k, StringComparer.Ordinal));
        var lunch = rows.Single(r => r.Id == "tx-lunch-0001");
        Assert.Equal(-1_200, lunch.AmountMinor);
        Assert.Equal("voice", lunch.Source);
        Assert.Equal("cat-dining", lunch.CategoryId);
        Assert.Equal("phone", rows.Single(r => r.Id == "tx-phone-0001").SourceKind);
        Assert.Equal("2026-10-12", lunch.Date);
        Assert.All(rows, r => Assert.Equal("USD", r.Currency));
    }

    [Fact]
    public async Task A_search_returns_only_the_matching_rows()
    {
        var result = await ClientServing(("q=lunch", "transactions-search")).GetTransactionsAsync("lunch", 100);

        Assert.Equal(new[] { "Lunch" }, result.Value!.Select(t => t.Description));
    }

    [Fact]
    public async Task Categories_include_their_aliases()
    {
        var result = await ClientServing(("/categories", "categories")).GetCategoriesAsync();

        var dining = result.Value!.Single(c => c.Id == "cat-dining");
        Assert.Equal("Food · Dining", dining.Name);
        Assert.Equal(new[] { "lunch", "restaurants" }, dining.Aliases);
        Assert.Equal("income", result.Value!.Single(c => c.Id == "cat-income").Kind);
    }

    [Fact]
    public async Task Budget_status_rows_have_the_numbers_the_bars_need()
    {
        var result = await ClientServing(("budget_status", "budget-status")).GetBudgetStatusAsync("this_month");

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var dining = result.Value!.Single(b => b.CategoryId == "cat-dining");
        Assert.Equal("Food · Dining", dining.Category);
        Assert.Equal(20_000, dining.BudgetMinor);
        Assert.Equal(1_200, dining.SpentMinor);
        Assert.Equal(18_800, dining.RemainingMinor);
        Assert.Equal(600, dining.UsedBasisPoints);
        Assert.False(dining.OverBudget);
        Assert.Equal("2026-10", dining.Month);
        Assert.Equal(2, result.Value!.Count);
    }

    [Fact]
    public async Task Bills_include_the_days_until_due_and_the_kind()
    {
        var result = await ClientServing(("upcoming_bills", "bills")).GetBillsAsync();

        var bills = result.Value!.ToDictionary(b => b.Name);
        Assert.Equal(2, bills["Rent"].DaysUntil);
        Assert.Equal("2026-10-14", bills["Rent"].DueDate);
        Assert.Equal(6, bills["Phone"].DaysUntil);
        Assert.Equal("subscription", bills["Streaming"].Kind);
        Assert.All(bills.Values, b => Assert.False(b.Overdue));
    }

    [Fact]
    public async Task Net_worth_snapshots_are_keyed_by_currency()
    {
        var result = await ClientServing(("networth-snapshots", "networth-snapshots")).GetNetWorthSnapshotsAsync();

        var snapshot = Assert.Single(result.Value!);
        Assert.Equal("2026-10-12", snapshot.AsOf);
        var usd = snapshot.ByCurrency["USD"];
        Assert.Equal(usd.AssetsMinor - usd.LiabilitiesMinor, usd.NetMinor);
    }

    [Fact]
    public async Task A_sync_conflict_names_the_transaction_and_both_amounts()
    {
        var result = await ClientServing(("/conflicts", "conflicts")).GetConflictsAsync();

        var conflict = Assert.Single(result.Value!);
        Assert.Equal("Market", conflict.Label);
        Assert.Equal("USD", conflict.Currency);
        Assert.Equal("amount_minor", conflict.Field);
        Assert.Equal("transaction", conflict.AggregateType);
        Assert.Contains("-8540", new[] { conflict.LocalValue, conflict.RemoteValue });
        var banner = new ViewModels.ConflictBannerViewModel(conflict);
        Assert.StartsWith("Market was ", banner.Message);
        Assert.EndsWith("Which is right?", banner.Message);
    }

    [Fact]
    public async Task Privacy_settings_round_trip()
    {
        var read = await ClientServing(("/privacy", "privacy")).GetPrivacyAsync();
        var patched = await ClientServing(("/privacy", "privacy-after-patch")).SetPrivacyAsync(null, true);

        Assert.Equal(new PrivacySettings(true, false), read.Value);
        Assert.Equal(new PrivacySettings(true, true), patched.Value);
    }

    [Fact]
    public async Task Today_has_the_budget_left_and_the_bills_in_seven_days()
    {
        var result = await ClientServing(("/v1/today", "today")).GetTodayAsync();

        Assert.True(result.IsSuccess, result.Error?.SafeMessage);
        var finance = result.Value!.Domains.Finance!;
        var left = Assert.Single(finance.BudgetLeft);
        Assert.Equal("USD", left.Currency);
        Assert.Equal(70_000, left.BudgetMinor);
        Assert.Equal(left.BudgetMinor - left.SpentMinor, left.RemainingMinor);
        Assert.Equal(new[] { "Rent", "Phone" }, finance.BillsDue.Select(b => b.Name));
        Assert.Equal("2026-10-12", result.Value.AsOf);
    }

    [Fact]
    public async Task A_dry_run_import_report_lists_every_row_with_its_reason()
    {
        var result = await ClientServing(("/import", "import-dry-run"))
            .ImportAsync("csv", new byte[] { 1 }, "acct-checking", null, dryRun: true);

        var report = result.Value!;
        Assert.True(report.DryRun);
        Assert.Equal(2, report.Accepted);
        Assert.Equal(0, report.Duplicates);
        var rejected = Assert.Single(report.Rejected);
        Assert.Equal(4, rejected.Row);
        Assert.Contains("date does not match", rejected.Reason);
        Assert.Equal(3, report.Rows.Count);
        Assert.Equal(new[] { "accepted", "accepted", "rejected" }, report.Rows.Select(r => r.Status));
        Assert.Equal("Imported coffee", report.Rows[0].Description);
        Assert.Equal(-450, report.Rows[0].AmountMinor);
    }

    [Fact]
    public async Task A_commit_response_names_the_new_record()
    {
        var result = await ClientServing(("/transactions", "commit"))
            .AddTransactionAsync(new NewTransactionRequest("acct-checking", "2026-10-12", -500, "Coffee", null, null));

        Assert.Equal("tx-new-00001", result.Value!.AggregateId);
        Assert.Equal(1, result.Value.Version);
    }

    [Fact]
    public async Task The_domains_listing_reports_state_schema_and_privacy()
    {
        // The Finance page does not call /v1/domains, but the shape is part of the contract the
        // Settings screen will use; parse it generically so a rename is noticed.
        var json = System.Text.Json.JsonDocument.Parse(Fixture("domains")).RootElement;
        var finance = json.GetProperty("domains")[0];
        Assert.Equal("finance", finance.GetProperty("domain").GetString());
        Assert.Equal("ready", finance.GetProperty("state").GetString());
        Assert.Equal(3, finance.GetProperty("schema_version").GetInt32());
        Assert.True(finance.GetProperty("privacy").GetProperty("sync").GetBoolean());
        await Task.CompletedTask;
    }

    [Theory]
    [InlineData("error-validation", HttpStatusCode.UnprocessableEntity, FinanceErrorKind.Validation, "category")]
    [InlineData("error-conflict", HttpStatusCode.Conflict, FinanceErrorKind.Conflict, null)]
    [InlineData("error-not-found", HttpStatusCode.NotFound, FinanceErrorKind.NotFound, null)]
    [InlineData("error-deleted", HttpStatusCode.Gone, FinanceErrorKind.Deleted, null)]
    [InlineData("error-locked", (HttpStatusCode)423, FinanceErrorKind.Locked, null)]
    public async Task Real_error_bodies_map_to_the_right_error_kind(string fixture, HttpStatusCode status, FinanceErrorKind kind, string? field)
    {
        var captured = System.Text.Json.JsonDocument.Parse(Fixture(fixture)).RootElement;
        Assert.Equal((int)status, captured.GetProperty("status").GetInt32());
        var body = captured.GetProperty("body").GetRawText();
        var handler = new StubHandler { Responder = (_, _) => Task.FromResult(StubHandler.Json(status, body)) };
        var client = new FinanceApiClient(
            new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") }, new StubTokens());

        var result = await client.GetBalancesAsync();

        Assert.Equal(kind, result.Error!.Kind);
        Assert.Equal(field, result.Error.Field);
    }
}
