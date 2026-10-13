using Reva.Desktop.Finance;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Finance;

public class FinanceViewModelTests
{
    private static FinanceViewModel Create(FakeFinanceApi api) => new(api, () => TestData.Today);

    [Fact]
    public async Task Refresh_loads_every_section_of_the_page()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);

        await vm.RefreshAsync();

        Assert.True(vm.HasLoaded);
        Assert.False(vm.HasError);
        Assert.False(vm.IsLoading);
        Assert.Equal(new[] { "Checking", "Credit card" }, vm.Accounts.Select(a => a.Title));
        Assert.Equal("$6,605.00", vm.Accounts[0].BalanceText);
        Assert.Equal("-$228.49", vm.Accounts[1].BalanceText);
        Assert.Equal(2, vm.Budgets.Count);
        Assert.Equal(2, vm.Bills.Count);
        Assert.Equal(4, vm.Transactions.Count);
        Assert.True(vm.NetWorth.HasSnapshot);
        Assert.Equal("$6,376.51", vm.NetWorth.ValueText);
        Assert.Equal("Taken Oct 12", vm.NetWorth.Caption);
        Assert.False(vm.ShowEmptyState);
    }

    [Fact]
    public async Task Budget_bars_over_ninety_percent_are_flagged_and_fill_is_capped()
    {
        var api = TestData.PopulatedApi();
        api.Budgets.Clear();
        api.Budgets.AddRange(new[]
        {
            TestData.Budget("Low", 10_000, 2_000, 2_000),
            TestData.Budget("Edge", 10_000, 9_000, 9_000),
            TestData.Budget("Near", 10_000, 9_100, 9_100),
            TestData.Budget("Over", 10_000, 12_500, 12_500, over: true),
        });
        var vm = Create(api);
        await vm.RefreshAsync();

        Assert.Equal(new[] { false, false, true, true }, vm.Budgets.Select(b => b.IsNearLimit));
        Assert.Equal(new[] { 0.2, 0.9, 0.91, 1.0 }, vm.Budgets.Select(b => Math.Round(b.Fraction, 2)));
        Assert.True(vm.Budgets[3].IsOver);
        Assert.Equal("$20.00 / $100.00", vm.Budgets[0].AmountsText);
        Assert.Contains("over budget by $25.00", vm.Budgets[3].AccessibleName);
        Assert.Contains("20 percent used", vm.Budgets[0].AccessibleName);
    }

    [Fact]
    public async Task Transactions_show_relative_dates_signed_amounts_and_where_each_came_from()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();

        var rows = vm.Transactions;
        Assert.Equal(new[] { "Today", "Yesterday", "Oct 9", "Oct 1" }, rows.Select(r => r.DateText));
        Assert.Equal(new[] { "-$12.00", "-$84.50", "-$23.00", "+$3,000.00" }, rows.Select(r => r.AmountText));
        Assert.Equal(
            new[] { "voice · confirmed", "csv import", "phone · synced", "manual" },
            rows.Select(r => r.SourceText));
        Assert.Equal(
            new[] { "Food · Dining", "Food · Dining", "Food · Dining", "Uncategorized" },
            rows.Select(r => r.CategoryText));
        Assert.Equal("Credit card", rows[0].AccountText);
        Assert.True(rows[3].IsIncome);
        Assert.False(rows[0].IsIncome);
        Assert.Contains("source voice · confirmed", rows[0].AccessibleName);
    }

    [Fact]
    public async Task A_locked_finance_file_is_reported_plainly_and_loading_still_finishes()
    {
        var api = TestData.PopulatedApi();
        var locked = new FinanceError(
            FinanceErrorKind.Locked, "Finance is locked: REVA has no key that opens the Finance data on this PC.");
        foreach (var call in new[]
        {
            "GetBalances", "GetCategories", "GetTransactions", "GetBudgetStatus", "GetBills",
            "GetNetWorthSnapshots", "GetConflicts", "GetPrivacy",
        })
        {
            api.Failures[call] = locked;
        }

        var vm = Create(api);
        await vm.RefreshAsync();

        Assert.True(vm.IsLocked);
        Assert.True(vm.HasError);
        Assert.Contains("locked", vm.ErrorMessage);
        Assert.True(vm.HasLoaded);
        Assert.False(vm.IsLoading);
        Assert.False(vm.ShowEmptyState);
    }

    [Fact]
    public async Task A_fresh_install_offers_add_account_instead_of_an_error()
    {
        var vm = Create(new FakeFinanceApi());
        await vm.RefreshAsync();

        Assert.True(vm.ShowEmptyState);
        Assert.False(vm.HasError);
        Assert.False(vm.HasAccounts);
        Assert.False(vm.HasTransactions);
        Assert.Equal("No transactions yet.", vm.TransactionsEmptyText);
        Assert.False(vm.NetWorth.HasSnapshot);
        Assert.Equal("No snapshot yet", vm.NetWorth.ValueText);
    }

    [Fact]
    public async Task Refresh_does_not_block_the_caller_while_core_is_slow()
    {
        var api = TestData.PopulatedApi();
        api.Gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var vm = Create(api);

        var started = vm.RefreshAsync();

        // The call returned control immediately: the work is still pending and the UI shows loading.
        Assert.False(started.IsCompleted);
        Assert.True(vm.IsLoading);
        Assert.Empty(vm.Accounts);

        api.Gate.SetResult();
        await started;
        Assert.False(vm.IsLoading);
        Assert.Equal(2, vm.Accounts.Count);
    }

    [Fact]
    public async Task A_newer_refresh_wins_over_an_older_slower_one()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();

        api.Gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        api.Balances = new List<AccountBalance> { TestData.Checking() with { Name = "OLD" } };
        var slow = vm.RefreshAsync();
        var gate = api.Gate;

        api.Gate = null;
        api.Balances = new List<AccountBalance> { TestData.Checking() with { Name = "NEW" } };
        await vm.RefreshAsync();
        Assert.Equal("NEW", vm.Accounts[0].Title);

        gate.SetResult();
        await slow;
        Assert.Equal("NEW", vm.Accounts[0].Title);
        Assert.False(vm.IsLoading);
    }

    [Fact]
    public async Task Search_asks_core_for_matching_transactions_and_shows_an_empty_message()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();

        vm.SearchText = "lunch";
        await vm.SearchAsync();
        Assert.Equal(new[] { "Lunch" }, vm.Transactions.Select(t => t.Description));
        Assert.Contains("GetTransactions:q=lunch", api.Calls);

        vm.SearchText = "zzz";
        await vm.SearchAsync();
        Assert.Empty(vm.Transactions);
        Assert.False(vm.HasTransactions);
        Assert.Equal("No transactions match that search.", vm.TransactionsEmptyText);
    }

    [Fact]
    public async Task A_slow_old_search_never_overwrites_a_newer_one()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();

        api.Gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        vm.SearchText = "lunch";
        var slow = vm.SearchAsync();
        var gate = api.Gate;
        api.Gate = null;
        vm.SearchText = "market";
        await vm.SearchAsync();
        Assert.Equal(new[] { "Market" }, vm.Transactions.Select(t => t.Description));

        gate.SetResult();
        await slow;
        Assert.Equal(new[] { "Market" }, vm.Transactions.Select(t => t.Description));
    }

    [Fact]
    public async Task A_conflict_that_arrives_from_a_sync_while_the_page_is_open_appears_without_a_full_reload()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();
        Assert.False(vm.HasConflict);
        var callsBefore = api.Calls.Count;

        // A paired phone syncs and disagrees about an amount; Core now lists the conflict.
        api.Conflicts.Add(new FinanceConflict(9, "transaction", "tx-2", "amount_minor", "-500", "-900", "Taxi", "USD"));
        await vm.RefreshConflictsAsync();

        Assert.True(vm.HasConflict);
        Assert.Equal("Taxi was -$5.00 on this PC and -$9.00 on your phone. Which is right?", vm.Conflict!.Message);
        Assert.Equal(new[] { "GetConflicts" }, api.Calls.Skip(callsBefore));
    }

    [Fact]
    public async Task The_conflict_refresh_clears_the_banner_when_it_was_resolved_elsewhere_and_ignores_failures()
    {
        var api = TestData.PopulatedApi();
        api.Conflicts.Add(new FinanceConflict(7, "transaction", "tx-1", "amount_minor", "-1111", "-2222", "Corner Cafe", "USD"));
        var vm = Create(api);
        await vm.RefreshAsync();
        var banner = vm.Conflict;

        await vm.RefreshConflictsAsync();
        Assert.Same(banner, vm.Conflict); // unchanged conflict: the banner object is not replaced

        api.Failures["GetConflicts"] = new FinanceError(FinanceErrorKind.Unavailable, "down");
        await vm.RefreshConflictsAsync();
        Assert.Same(banner, vm.Conflict); // a failed poll never wipes the banner

        api.Failures.Clear();
        api.Conflicts.Clear();
        await vm.RefreshConflictsAsync();
        Assert.False(vm.HasConflict);
    }

    [Fact]
    public async Task The_sync_conflict_banner_names_the_record_and_both_amounts()
    {
        var api = TestData.PopulatedApi();
        api.Conflicts.Add(new FinanceConflict(7, "transaction", "tx-1", "amount_minor", "-1111", "-2222", "Corner Cafe", "USD"));
        var vm = Create(api);
        await vm.RefreshAsync();

        Assert.True(vm.HasConflict);
        Assert.Equal(
            "Corner Cafe was -$11.11 on this PC and -$22.22 on your phone. Which is right?",
            vm.Conflict!.Message);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Resolving_a_conflict_tells_core_which_side_to_keep_and_clears_the_banner(bool keepPc)
    {
        var api = TestData.PopulatedApi();
        api.Conflicts.Add(new FinanceConflict(7, "transaction", "tx-1", "amount_minor", "-1111", "-2222", "Corner Cafe", "USD"));
        var vm = Create(api);
        await vm.RefreshAsync();

        await vm.ResolveConflictAsync(keepPc);

        Assert.Equal(new[] { (7L, keepPc) }, api.Resolutions);
        Assert.False(vm.HasConflict);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task A_failed_resolution_keeps_the_banner_and_says_why()
    {
        var api = TestData.PopulatedApi();
        api.Conflicts.Add(new FinanceConflict(7, "transaction", "tx-1", "amount_minor", "-1", "-2", "X", "USD"));
        api.Failures["ResolveConflict"] = new FinanceError(FinanceErrorKind.Conflict, "this conflict is already resolved");
        var vm = Create(api);
        await vm.RefreshAsync();

        await vm.ResolveConflictAsync(true);

        Assert.True(vm.HasConflict);
        Assert.Equal("this conflict is already resolved", vm.ErrorMessage);
    }

    [Fact]
    public async Task Privacy_switches_start_from_core_and_changing_one_saves_only_that_one()
    {
        var api = TestData.PopulatedApi();
        api.Privacy = new PrivacySettings(true, false);
        var vm = Create(api);
        await vm.RefreshAsync();
        Assert.True(vm.SyncEnabled);
        Assert.False(vm.HostedModelEnabled);
        Assert.Empty(api.PrivacyWrites); // loading the page must never write

        vm.HostedModelEnabled = true;
        await vm.PendingPrivacyChange;

        Assert.Equal(new (bool?, bool?)[] { (null, true) }, api.PrivacyWrites);
        Assert.True(vm.HostedModelEnabled);
        Assert.True(vm.SyncEnabled);
        Assert.Null(vm.PrivacyMessage);
    }

    [Fact]
    public async Task A_privacy_switch_goes_back_if_it_could_not_be_saved()
    {
        var api = TestData.PopulatedApi();
        api.Failures["SetPrivacy"] = new FinanceError(FinanceErrorKind.ServerFailure, "x");
        var vm = Create(api);
        await vm.RefreshAsync();

        vm.SyncEnabled = false;
        await vm.PendingPrivacyChange;

        Assert.True(vm.SyncEnabled);
        Assert.Contains("unchanged", vm.PrivacyMessage);
    }

    [Fact]
    public async Task Switching_the_budget_period_reloads_only_the_budgets()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();
        api.Calls.Clear();

        await vm.SetBudgetPeriodAsync(FinanceViewModel.LastMonth);
        await vm.SetBudgetPeriodAsync("nonsense");

        Assert.Equal(new[] { "GetBudgetStatus:last_month" }, api.Calls);
        Assert.Equal(FinanceViewModel.LastMonth, vm.BudgetPeriod);
    }

    [Fact]
    public async Task Taking_a_net_worth_snapshot_updates_the_card()
    {
        var api = TestData.PopulatedApi();
        api.Snapshots.Clear();
        var vm = Create(api);
        await vm.RefreshAsync();
        Assert.False(vm.NetWorth.HasSnapshot);

        api.Snapshots.Add(new NetWorthSnapshot("nw-9", "2026-10-12", new Dictionary<string, NetWorthEntry>
        {
            ["EUR"] = new(10_000, 0, 10_000),
            ["USD"] = new(5_000, 1_000, 4_000),
        }));
        await vm.TakeSnapshotAsync();

        Assert.True(vm.NetWorth.HasSnapshot);
        Assert.Equal("€100.00 · $40.00", vm.NetWorth.ValueText);
    }

    [Fact]
    public async Task Export_returns_core_bytes_and_clears_the_busy_flag()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);

        var result = await vm.ExportAsync("csv");

        Assert.True(result.IsSuccess);
        Assert.Equal(new byte[] { 1, 2, 3 }, result.Value);
        Assert.Contains("Export:csv", api.Calls);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Dialog_view_models_start_from_the_loaded_accounts_and_categories()
    {
        var api = TestData.PopulatedApi();
        var vm = Create(api);
        await vm.RefreshAsync();

        var add = vm.NewAddTransaction();
        Assert.Equal(new[] { "Checking (USD)", "Credit card (USD)" }, add.Accounts.Select(a => a.Display));
        Assert.Equal(new[] { "Food · Dining", "Groceries" }, add.CategoryNames);
        Assert.Equal(2, vm.NewImport().Accounts.Count);
    }

    [Fact]
    public void The_no_money_movement_note_is_fixed_text()
    {
        Assert.Equal(
            "REVA records and analyses money. It can't pay, transfer, buy or log in to a bank — those actions don't exist.",
            FinanceViewModel.NoMoneyMovementNote);
    }
}
