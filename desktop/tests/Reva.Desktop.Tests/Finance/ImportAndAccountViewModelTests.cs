using System.Text;
using Reva.Desktop.Finance;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Finance;

public class ImportViewModelTests
{
    private const string BankCsv =
        "Date,Description,Debit,Credit,Category\n05/10/2026,COFFEE,4.50,,Dining\n13/10/2026,PAYCHECK,,1500.00,Income\n";

    private static byte[] Bytes(string text) => Encoding.UTF8.GetBytes(text);

    private static ImportViewModel Create(FakeFinanceApi? api = null) =>
        new(api ?? new FakeFinanceApi(), new[] { TestData.Checking(), TestData.Card() });

    private static ImportReport Report(bool dryRun, long accepted = 2, long duplicates = 0, params ImportRejected[] rejected) =>
        new(
            accepted,
            duplicates,
            rejected,
            new[]
            {
                new ImportRow(2, "accepted", null, "2026-10-05", -450, "COFFEE", null, "05/10/2026,COFFEE"),
                new ImportRow(3, "accepted", null, "2026-10-13", 150_000, "PAYCHECK", "category not found", "x"),
            }.Concat(rejected.Select(r => new ImportRow(r.Row, "rejected", r.Reason, null, null, null, null, r.Raw))).ToList(),
            dryRun,
            "BATCH");

    [Fact]
    public void A_csv_proposes_the_columns_and_date_format_from_the_header()
    {
        var vm = Create();
        vm.LoadFile("statement.csv", Bytes(BankCsv));

        Assert.Equal("csv", vm.Format);
        Assert.True(vm.IsCsv);
        Assert.True(vm.NeedsAccount);
        Assert.Equal("Date", vm.DateColumn);
        Assert.Equal("Description", vm.DescriptionColumn);
        Assert.Null(vm.AmountColumn);
        Assert.Equal("Debit", vm.DebitColumn);
        Assert.Equal("Credit", vm.CreditColumn);
        Assert.Equal("Category", vm.CategoryColumn);
        Assert.Equal("%d/%m/%Y", vm.DateFormat); // 13/10/2026 can only be day-first
        Assert.False(vm.DateFormatIsAmbiguous);
        Assert.Equal(new[] { "Date", "Description", "Debit", "Credit", "Category" }, vm.Headers);
    }

    [Fact]
    public void A_date_like_05_10_2026_is_flagged_as_ambiguous_so_the_person_checks_it()
    {
        var vm = Create();
        vm.LoadFile("a.csv", Bytes("Date,Memo,Amount\n05/10/2026,x,-1.00\n06/11/2026,y,-2.00\n"));

        Assert.True(vm.DateFormatIsAmbiguous);
        Assert.Equal("%d/%m/%Y", vm.DateFormat);
        Assert.Equal("Amount", vm.AmountColumn);
        Assert.Equal("Memo", vm.DescriptionColumn);
    }

    [Fact]
    public void Ofx_and_json_need_no_column_mapping_and_unknown_files_are_refused()
    {
        var vm = Create();
        vm.LoadFile("bank.QFX", Bytes("<OFX>"));
        Assert.Equal("ofx", vm.Format);
        Assert.False(vm.IsCsv);
        Assert.True(vm.NeedsAccount);

        vm.LoadFile("backup.json", Bytes("{}"));
        Assert.Equal("json", vm.Format);
        Assert.False(vm.NeedsAccount);

        vm.LoadFile("photo.png", new byte[] { 1 });
        Assert.Equal(string.Empty, vm.Format);
        Assert.Contains("isn't one of them", vm.Error);
        Assert.False(vm.CanCheck && vm.Format.Length > 0);
    }

    [Fact]
    public async Task Check_runs_a_dry_run_with_the_mapping_and_saves_nothing()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        vm.SelectedAccount = vm.Accounts[1];

        Assert.True(await vm.CheckAsync());

        var call = Assert.Single(api.Imports);
        Assert.Equal("csv", call.Format);
        Assert.True(call.DryRun);
        Assert.Equal("acct-card", call.AccountId);
        Assert.Equal("Date", call.Mapping!.Date);
        Assert.Equal("%d/%m/%Y", call.Mapping.DateFormat);
        Assert.Equal("Debit", call.Mapping.Debit);
        Assert.Null(call.Mapping.Amount);
        Assert.Equal(",", call.Mapping.Delimiter);
        Assert.True(vm.HasReport);
        Assert.True(vm.CanConfirm);
        Assert.Equal("2 will import · 0 already there · 0 rejected. Nothing has been saved yet.", vm.SummaryText);
        Assert.Equal("Import 2 rows", vm.ConfirmText);
        Assert.Equal(2, vm.ReportRows.Count);
        Assert.Equal("will import", vm.ReportRows[0].StatusText);
        Assert.Contains("-$4.50", vm.ReportRows[0].Summary);
    }

    [Fact]
    public async Task The_import_button_is_not_available_before_the_report_has_been_seen()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));

        Assert.False(vm.CanConfirm);
        Assert.False(await vm.ConfirmAsync());
        Assert.Empty(api.Imports);
        Assert.Equal("Check the file first. Nothing is saved until you confirm.", vm.SummaryText);
    }

    [Fact]
    public async Task Confirm_runs_the_real_import_exactly_once_and_reports_the_result()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        await vm.CheckAsync();

        Assert.True(await vm.ConfirmAsync());
        Assert.False(await vm.ConfirmAsync()); // a second press does nothing

        Assert.Equal(new[] { true, false }, api.Imports.Select(i => i.DryRun));
        Assert.Equal("Imported 2 rows. 0 were already there, 0 were rejected.", vm.ResultText);
        Assert.False(vm.CanConfirm);
        Assert.False(vm.CanCheck);
    }

    [Fact]
    public async Task Changing_any_choice_after_the_check_throws_the_report_away()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        await vm.CheckAsync();
        Assert.True(vm.CanConfirm);

        vm.DateFormat = "%m/%d/%Y";

        Assert.False(vm.HasReport);
        Assert.False(vm.CanConfirm);
        Assert.Empty(vm.ReportRows);
        Assert.False(await vm.ConfirmAsync());
        Assert.Single(api.Imports); // only the dry run happened
    }

    [Fact]
    public async Task Rejected_rows_are_listed_with_the_reason_and_the_raw_row()
    {
        var api = new FakeFinanceApi
        {
            ImportResponder = dry => Report(dry, 2, 1, new ImportRejected(5, "date does not match %d/%m/%Y", "31/02/2026,BAD,1.00")),
        };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        await vm.CheckAsync();

        Assert.Equal("2 will import · 1 already there · 1 rejected. Nothing has been saved yet.", vm.SummaryText);
        var rejected = vm.ReportRows.Single(r => r.Status == "rejected");
        Assert.Equal("5", rejected.RowText);
        Assert.Equal("31/02/2026,BAD,1.00", rejected.Summary);
        Assert.Equal("date does not match %d/%m/%Y", rejected.Detail);
        Assert.Contains("Row 5, rejected", rejected.AccessibleName);
    }

    [Fact]
    public async Task A_check_with_nothing_to_import_cannot_be_confirmed()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry, 0, 3) };
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        await vm.CheckAsync();

        Assert.True(vm.HasReport);
        Assert.False(vm.CanConfirm);
        Assert.Equal("Import", vm.ConfirmText);
    }

    [Theory]
    [InlineData(null, "Choose which column holds the date.")]
    [InlineData("Date", "Choose which column holds the description.")]
    public async Task Missing_columns_are_explained_before_anything_is_sent(string? dateColumn, string message)
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        vm.DateColumn = dateColumn;
        vm.DescriptionColumn = null;

        Assert.False(await vm.CheckAsync());
        Assert.Equal(message, vm.Error);
        Assert.Empty(api.Imports);
    }

    [Fact]
    public async Task One_amount_column_or_debit_and_credit_but_not_both()
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));
        vm.AmountColumn = "Debit";

        Assert.False(await vm.CheckAsync());
        Assert.Equal("Use either one Amount column or Debit/Credit columns, not both.", vm.Error);

        vm.AmountColumn = null;
        vm.DebitColumn = null;
        vm.CreditColumn = null;
        Assert.False(await vm.CheckAsync());
        Assert.Equal("Choose the Amount column, or the Debit and Credit columns.", vm.Error);
        Assert.Empty(api.Imports);
    }

    [Fact]
    public async Task Core_failures_are_shown_without_internals_and_leave_no_report()
    {
        var api = new FakeFinanceApi();
        api.Failures["Import"] = new FinanceError(FinanceErrorKind.Validation, "mapping: no column named \"Date\"", "mapping", "no column named \"Date\"");
        var vm = Create(api);
        vm.LoadFile("statement.csv", Bytes(BankCsv));

        Assert.False(await vm.CheckAsync());
        Assert.False(vm.HasReport);
        Assert.Contains("no column named", vm.Error);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Ofx_imports_send_the_account_and_no_mapping()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("bank.ofx", Bytes("<OFX></OFX>"));

        Assert.True(await vm.CheckAsync());
        var call = Assert.Single(api.Imports);
        Assert.Equal("ofx", call.Format);
        Assert.Equal("acct-checking", call.AccountId);
        Assert.Null(call.Mapping);
    }

    [Fact]
    public async Task Json_restores_send_no_account()
    {
        var api = new FakeFinanceApi { ImportResponder = dry => Report(dry) };
        var vm = Create(api);
        vm.LoadFile("backup.json", Bytes("{}"));

        Assert.True(await vm.CheckAsync());
        Assert.Null(api.Imports[0].AccountId);
    }
}

public class AddAccountViewModelTests
{
    [Fact]
    public async Task Cards_and_loans_store_what_you_owe_as_a_negative_balance()
    {
        var api = new FakeFinanceApi();
        var vm = new AddAccountViewModel(api) { Name = "Visa", Kind = "credit", Currency = "usd", OpeningText = "250.00" };

        Assert.True(await vm.SubmitAsync());

        Assert.Equal(new NewAccountRequest("Visa", "credit", "USD", -25_000), Assert.Single(api.AddedAccounts));
        Assert.Contains("owe", vm.OpeningHint);
    }

    [Fact]
    public async Task A_checking_account_keeps_the_balance_as_typed_and_blank_means_zero()
    {
        var api = new FakeFinanceApi();
        var vm = new AddAccountViewModel(api) { Name = "Main", OpeningText = "1,000.50" };
        Assert.True(await vm.SubmitAsync());
        vm.OpeningText = string.Empty;
        vm.Name = "Second";
        Assert.True(await vm.SubmitAsync());

        Assert.Equal(new long[] { 100_050, 0 }, api.AddedAccounts.Select(a => a.OpeningBalanceMinor));
    }

    [Fact]
    public async Task Bad_input_is_explained_and_not_sent()
    {
        var api = new FakeFinanceApi();
        var vm = new AddAccountViewModel(api) { Name = " ", Currency = "dollars", OpeningText = "x" };

        Assert.False(await vm.SubmitAsync());

        Assert.Equal("Enter a name.", vm.NameError);
        Assert.Equal("Use a 3-letter currency code such as USD.", vm.CurrencyError);
        Assert.Empty(api.AddedAccounts);

        vm.Currency = "USD";
        vm.Name = "Ok";
        Assert.False(await vm.SubmitAsync());
        Assert.Equal("That is not a valid amount.", vm.OpeningError);
    }

    [Fact]
    public async Task A_duplicate_name_is_shown_next_to_the_name()
    {
        var api = new FakeFinanceApi();
        api.Failures["AddAccount"] = new FinanceError(
            FinanceErrorKind.Conflict, "an account named \"Main\" already exists", null, "an account named \"Main\" already exists");
        var vm = new AddAccountViewModel(api) { Name = "Main" };

        Assert.False(await vm.SubmitAsync());
        Assert.Equal("an account named \"Main\" already exists", vm.NameError);
    }
}
