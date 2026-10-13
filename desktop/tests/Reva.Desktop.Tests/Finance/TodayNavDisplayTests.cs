using System.Text;
using Reva.Desktop.Finance;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Finance;

public class TodayViewModelTests
{
    private static TodaySummary Summary(IReadOnlyList<TodayBudgetLeft> budgets, IReadOnlyList<FinanceBill> bills) =>
        new("2026-10-12", new TodayDomains(new TodayFinance(budgets, bills)));

    [Fact]
    public async Task Shows_budget_left_this_month_and_the_bills_due_in_seven_days()
    {
        var api = new FakeFinanceApi
        {
            Today = Summary(
                new[] { new TodayBudgetLeft("USD", 70_000, 16_350, 53_650) },
                new[] { TestData.Bill("Gym", "2026-10-10", -2, overdue: true), TestData.Bill("Internet", "2026-10-14", 2) }),
        };
        var vm = new TodayViewModel(api, () => TestData.Today);

        await vm.RefreshAsync();

        Assert.True(vm.HasBudget);
        Assert.Equal("$536.50", vm.BudgetLeftText);
        Assert.Equal("of $700.00", vm.BudgetOfText);
        Assert.Equal(0.2335, Math.Round(vm.BudgetFraction, 4));
        Assert.False(vm.BudgetNearLimit);
        Assert.Equal("Bills in 7 days · Gym Oct 10 · Internet Oct 14", vm.BillsText);
        Assert.Contains("Budget left this month: $536.50 of $700.00", vm.AccessibleSummary);
        Assert.False(vm.HasError);
        Assert.False(vm.IsLoading);
    }

    [Fact]
    public async Task A_budget_that_is_nearly_used_turns_the_bar_light_orange()
    {
        var api = new FakeFinanceApi { Today = Summary(new[] { new TodayBudgetLeft("USD", 10_000, 9_500, 500) }, Array.Empty<FinanceBill>()) };
        var vm = new TodayViewModel(api, () => TestData.Today);
        await vm.RefreshAsync();

        Assert.True(vm.BudgetNearLimit);
        Assert.Equal(0.95, vm.BudgetFraction);
    }

    [Fact]
    public async Task Income_is_not_listed_as_a_bill_and_an_empty_week_is_said_plainly()
    {
        var api = new FakeFinanceApi
        {
            Today = Summary(new[] { new TodayBudgetLeft("USD", 100, 0, 100) }, new[] { TestData.Bill("Paycheck", "2026-10-15", 3, "income") }),
        };
        var vm = new TodayViewModel(api, () => TestData.Today);
        await vm.RefreshAsync();

        Assert.Equal("No bills in the next 7 days", vm.BillsText);
    }

    [Fact]
    public async Task With_no_budgets_it_says_so_instead_of_showing_zero()
    {
        var vm = new TodayViewModel(new FakeFinanceApi(), () => TestData.Today);
        await vm.RefreshAsync();

        Assert.False(vm.HasBudget);
        Assert.Equal("No budgets set", vm.BudgetLeftText);
        Assert.Equal(string.Empty, vm.BudgetOfText);
        Assert.Equal(0, vm.BudgetFraction);
    }

    [Fact]
    public async Task Other_currencies_get_a_short_line_each()
    {
        var api = new FakeFinanceApi
        {
            Today = Summary(
                new[] { new TodayBudgetLeft("EUR", 5_000, 1_000, 4_000), new TodayBudgetLeft("USD", 70_000, 16_350, 53_650) },
                Array.Empty<FinanceBill>()),
        };
        var vm = new TodayViewModel(api, () => TestData.Today);
        await vm.RefreshAsync();

        Assert.Equal("$536.50", vm.BudgetLeftText);
        Assert.Equal("€40.00 left of €50.00", vm.OtherCurrenciesText);
    }

    [Fact]
    public async Task A_failure_shows_a_safe_message_and_no_numbers()
    {
        var api = new FakeFinanceApi();
        api.Failures["GetToday"] = new FinanceError(FinanceErrorKind.Unavailable, "REVA Core is not reachable.");
        var vm = new TodayViewModel(api, () => TestData.Today);
        await vm.RefreshAsync();

        Assert.True(vm.HasError);
        Assert.Equal("REVA Core is not reachable.", vm.ErrorMessage);
        Assert.False(vm.HasBudget);
        Assert.Equal("REVA Core is not reachable.", vm.AccessibleSummary);
    }

    [Fact]
    public async Task Refreshing_never_blocks_the_caller()
    {
        var api = new FakeFinanceApi { Gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously) };
        var vm = new TodayViewModel(api, () => TestData.Today);

        var pending = vm.RefreshAsync();
        Assert.False(pending.IsCompleted);
        Assert.True(vm.IsLoading);

        api.Gate.SetResult();
        await pending;
        Assert.False(vm.IsLoading);
    }
}

public class NavigationViewModelTests
{
    [Fact]
    public void Every_section_from_the_design_is_listed_in_order()
    {
        var vm = new NavigationViewModel();

        Assert.Equal(
            new[] { "Talk & Today", "Finance", "Health", "Coach", "Career", "Learn", "Cyber", "Personal", "Memory" },
            vm.DomainSections.Select(s => s.Title));
        Assert.Equal(
            new[] { "Apps & Actions", "Activity", "Devices", "Persona & Voice", "Settings" },
            vm.ToolSections.Select(s => s.Title));
    }

    [Fact]
    public void Only_talk_finance_and_devices_are_built_and_the_rest_say_coming_soon()
    {
        var built = NavigationViewModel.AllSections.Where(s => s.IsBuilt).Select(s => s.Id);
        Assert.Equal(new[] { "talk", "finance", "devices" }, built);

        var vm = new NavigationViewModel();
        Assert.True(vm.ShowsTalk);
        Assert.False(vm.ShowsComingSoon);

        Assert.True(vm.Select("health"));
        Assert.False(vm.ShowsTalk);
        Assert.False(vm.ShowsFinance);
        Assert.True(vm.ShowsComingSoon);
        Assert.Equal("Health", vm.ComingSoonTitle);
        Assert.Equal("Health is coming soon. It isn't built yet.", vm.ComingSoonText);
        Assert.Equal("Health, coming soon", vm.Selected.AccessibleName);
        Assert.Equal("soon", vm.Selected.Badge);
    }

    [Fact]
    public void Finance_is_selectable_and_unknown_ids_are_ignored()
    {
        var vm = new NavigationViewModel();
        var changes = new List<string?>();
        vm.PropertyChanged += (_, e) => changes.Add(e.PropertyName);

        Assert.True(vm.Select("finance"));
        Assert.True(vm.ShowsFinance);
        Assert.Contains(nameof(NavigationViewModel.ShowsFinance), changes);
        Assert.Equal("Finance", vm.Selected.AccessibleName);
        Assert.Equal(string.Empty, vm.Selected.Badge);

        Assert.False(vm.Select("nonexistent"));
        Assert.Equal("finance", vm.Selected.Id);
    }

    [Fact]
    public void Every_section_has_a_unique_id()
    {
        var ids = NavigationViewModel.AllSections.Select(s => s.Id).ToList();
        Assert.Equal(ids.Count, ids.Distinct().Count());
        Assert.Equal(14, ids.Count);
    }
}

public class FinanceDisplayTests
{
    [Theory]
    [InlineData("2026-10-12", "Today")]
    [InlineData("2026-10-11", "Yesterday")]
    [InlineData("2026-10-01", "Oct 1")]
    [InlineData("2025-12-31", "Dec 31, 2025")]
    [InlineData("not a date", "not a date")]
    public void Relative_dates(string iso, string expected) =>
        Assert.Equal(expected, FinanceDisplay.RelativeDate(iso, TestData.Today));

    [Theory]
    [InlineData("bill", false, "Due Oct 14")]
    [InlineData("subscription", false, "Renews Oct 14")]
    [InlineData("income", false, "Expected Oct 14")]
    [InlineData("bill", true, "Overdue since Oct 14")]
    [InlineData("income", true, "Expected Oct 14")]
    public void Due_text_depends_on_the_kind(string kind, bool overdue, string expected) =>
        Assert.Equal(expected, FinanceDisplay.DueText(TestData.Bill("x", "2026-10-14", 2, kind, overdue), TestData.Today));

    [Theory]
    [InlineData("manual", "manual")]
    [InlineData(null, "manual")]
    [InlineData("voice", "voice · confirmed")]
    [InlineData("csv", "csv import")]
    [InlineData("ofx", "ofx import")]
    [InlineData("json", "restored from export")]
    [InlineData("phone", "phone · synced")]
    [InlineData("import", "import")]
    public void Source_column_text(string? kind, string expected) =>
        Assert.Equal(expected, FinanceDisplay.SourceText(kind));

    [Theory]
    [InlineData(0L, 0.0, false)]
    [InlineData(9_000L, 0.9, false)]
    [InlineData(9_001L, 0.9001, true)]
    [InlineData(10_000L, 1.0, true)]
    [InlineData(25_000L, 1.0, true)]
    [InlineData(-5L, 0.0, false)]
    public void Budget_bar_fill_and_the_ninety_percent_rule(long basisPoints, double fraction, bool near)
    {
        Assert.Equal(fraction, FinanceDisplay.BarFraction(basisPoints), 4);
        Assert.Equal(near, FinanceDisplay.IsNearLimit(basisPoints));
    }
}

public class CsvSnifferTests
{
    [Theory]
    [InlineData("a,b,c\n1,2,3\n", ",")]
    [InlineData("a;b;c\n1;2;3\n", ";")]
    [InlineData("a\tb\tc\n1\t2\t3\n", "\t")]
    [InlineData("a|b|c\n1|2|3\n", "|")]
    public void Detects_the_delimiter(string text, string delimiter) =>
        Assert.Equal(delimiter, CsvSniffer.Probe(Encoding.UTF8.GetBytes(text))!.Delimiter);

    [Fact]
    public void Quoted_commas_do_not_confuse_the_delimiter_or_the_columns()
    {
        var probe = CsvSniffer.Probe(Encoding.UTF8.GetBytes("Date,\"Memo, long\",Amount\n2026-10-01,\"Hi, there\",-1.00\n"))!;

        Assert.Equal(new[] { "Date", "Memo, long", "Amount" }, probe.Headers);
        Assert.Equal(new[] { "2026-10-01", "Hi, there", "-1.00" }, probe.SampleRows[0]);
    }

    [Fact]
    public void A_utf8_byte_order_mark_is_ignored_and_latin1_is_still_readable()
    {
        var bom = new byte[] { 0xEF, 0xBB, 0xBF }.Concat(Encoding.UTF8.GetBytes("Date,Memo\n2026-10-01,Café\n")).ToArray();
        Assert.Equal("Date", CsvSniffer.Probe(bom)!.Headers[0]);

        var latin1 = new byte[] { 0x44, 0x61, 0x74, 0x65, 0x2C, 0x4D, 0x0A, 0x31, 0x2C, 0x43, 0x61, 0x66, 0xE9, 0x0A };
        Assert.Equal("Café", CsvSniffer.Probe(latin1)!.SampleRows[0][1]);
    }

    [Fact]
    public void Text_that_is_not_a_table_gives_no_probe()
    {
        Assert.Null(CsvSniffer.Probe(Encoding.UTF8.GetBytes("just one column of text\nsecond line\n")));
        Assert.Null(CsvSniffer.Probe(Array.Empty<byte>()));
    }

    [Fact]
    public void Guesses_columns_from_common_bank_headers()
    {
        var a = CsvSniffer.Guess(CsvSniffer.Probe(Encoding.UTF8.GetBytes(
            "Transaction Date,Posted Date,Payee,Amount,Category\n2026-10-01,2026-10-02,Shop,-3.00,Food\n"))!);
        Assert.Equal("Posted Date", a.Date);
        Assert.Equal("Payee", a.Description);
        Assert.Equal("Amount", a.Amount);
        Assert.Equal("Category", a.Category);
        Assert.Equal("%Y-%m-%d", a.DateFormat);

        var b = CsvSniffer.Guess(CsvSniffer.Probe(Encoding.UTF8.GetBytes(
            "Date;Details;Money out;Money in\n01.10.2026;Shop;3,00;\n"))!);
        Assert.Equal("Details", b.Description);
        Assert.Equal("Money out", b.Debit);
        Assert.Equal("Money in", b.Credit);
        Assert.Null(b.Amount);
        Assert.Equal("%d.%m.%Y", b.DateFormat);
        Assert.Equal(",", b.DecimalSeparator);
    }
}
