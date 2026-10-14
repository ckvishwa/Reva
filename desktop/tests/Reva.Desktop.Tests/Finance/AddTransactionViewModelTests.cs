using Reva.Desktop.Finance;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Finance;

public class AddTransactionViewModelTests
{
    private static AddTransactionViewModel Create(FakeFinanceApi? api = null) =>
        new(
            api ?? new FakeFinanceApi(),
            new[] { TestData.Checking(), TestData.Card() },
            new[] { TestData.Groceries(), TestData.Dining() },
            TestData.Today);

    private static void Fill(AddTransactionViewModel vm, string amount = "12.00", string description = "Lunch")
    {
        vm.AmountText = amount;
        vm.Description = description;
    }

    [Fact]
    public void Starts_on_the_first_account_with_todays_date_and_expense_selected()
    {
        var vm = Create();

        Assert.Equal("Checking", vm.SelectedAccount!.Name);
        Assert.Equal(new DateTime(2026, 10, 12), vm.Date.Date);
        Assert.True(vm.IsExpense);
        Assert.False(vm.IsIncome);
        Assert.Equal(new[] { "Food · Dining", "Groceries" }, vm.CategoryNames);
    }

    [Fact]
    public void The_preview_states_exactly_what_will_be_recorded()
    {
        var vm = Create();
        Assert.Equal("Enter an amount to see what will be recorded.", vm.PreviewText);

        Fill(vm);
        Assert.Equal("Will record $12.00 spent from Checking on 2026-10-12.", vm.PreviewText);

        vm.IsIncome = true;
        Assert.Equal("Will record $12.00 added to Checking on 2026-10-12.", vm.PreviewText);

        vm.AmountText = "12.345";
        Assert.Equal("Enter an amount to see what will be recorded.", vm.PreviewText);
    }

    [Theory]
    [InlineData("12.00", true, -1_200L)]
    [InlineData("12.00", false, 1_200L)]
    [InlineData("-12.00", true, -1_200L)]
    [InlineData("-12.00", false, 1_200L)]
    public void The_sign_comes_from_expense_or_income_never_from_a_typing_accident(string typed, bool expense, long expected)
    {
        var vm = Create();
        vm.AmountText = typed;
        vm.IsExpense = expense;

        Assert.Equal(expected, vm.SignedAmountMinor);
    }

    [Fact]
    public async Task Submitting_an_empty_form_reports_every_problem_and_sends_nothing()
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);

        var saved = await vm.SubmitAsync();

        Assert.False(saved);
        Assert.Equal("Enter an amount.", vm.AmountError);
        Assert.Equal("Enter a description.", vm.DescriptionError);
        Assert.Null(vm.AccountError);
        Assert.Empty(api.AddedTransactions);
    }

    [Theory]
    [InlineData("0", "The amount can't be zero.")]
    [InlineData("abc", "That is not a valid amount.")]
    [InlineData("1.234", "At most 2 decimal places for USD.")]
    [InlineData("12,50", "Use a point for decimals, for example 12.50.")]
    public async Task Bad_amounts_are_explained_and_not_sent(string typed, string message)
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);
        Fill(vm, typed);

        Assert.False(await vm.SubmitAsync());
        Assert.Equal(message, vm.AmountError);
        Assert.Empty(api.AddedTransactions);
    }

    [Fact]
    public async Task A_valid_form_is_sent_to_core_once_with_trimmed_text()
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);
        vm.SelectedAccount = vm.Accounts[1];
        Fill(vm, "$1,234.50", "  Lunch with Sam  ");
        vm.Category = " lunch ";
        vm.Notes = "  team  ";
        vm.Date = new DateTimeOffset(new DateTime(2026, 10, 9));

        var saved = await vm.SubmitAsync();

        Assert.True(saved);
        var sent = Assert.Single(api.AddedTransactions);
        Assert.Equal(new NewTransactionRequest("acct-card", "2026-10-09", -123_450, "Lunch with Sam", "lunch", "team"), sent);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Blank_category_and_notes_are_not_sent()
    {
        var api = new FakeFinanceApi();
        var vm = Create(api);
        Fill(vm);

        await vm.SubmitAsync();

        var sent = Assert.Single(api.AddedTransactions);
        Assert.Null(sent.Category);
        Assert.Null(sent.Notes);
    }

    [Fact]
    public async Task Core_rejecting_the_category_shows_the_message_next_to_the_category()
    {
        var api = new FakeFinanceApi();
        api.Failures["AddTransaction"] = new FinanceError(
            FinanceErrorKind.Validation, "category: no category or alias named \"zzz\"", "category", "no category or alias named \"zzz\"");
        var vm = Create(api);
        Fill(vm);
        vm.Category = "zzz";

        Assert.False(await vm.SubmitAsync());

        Assert.Equal("no category or alias named \"zzz\"", vm.CategoryError);
        Assert.Null(vm.GeneralError);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Other_failures_show_a_safe_general_message()
    {
        var api = new FakeFinanceApi();
        api.Failures["AddTransaction"] = new FinanceError(FinanceErrorKind.Locked, "Finance is locked: REVA has no key that opens the Finance data on this PC.");
        var vm = Create(api);
        Fill(vm);

        Assert.False(await vm.SubmitAsync());
        Assert.Contains("locked", vm.GeneralError);
    }

    [Fact]
    public async Task A_second_submit_while_the_first_is_in_flight_is_ignored()
    {
        var api = new FakeFinanceApi { Gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously) };
        var vm = Create(api);
        Fill(vm);

        var first = vm.SubmitAsync();
        var second = await vm.SubmitAsync();
        Assert.False(first.IsCompleted);
        Assert.True(vm.IsBusy);
        Assert.False(vm.CanSubmit);
        Assert.False(second);

        api.Gate.SetResult();
        Assert.True(await first);
        Assert.Single(api.AddedTransactions);
    }

    [Fact]
    public void Editing_a_field_clears_its_error()
    {
        var vm = Create();
        vm.Validate();
        Assert.NotNull(vm.AmountError);
        Assert.NotNull(vm.DescriptionError);

        vm.AmountText = "1";
        vm.Description = "x";

        Assert.Null(vm.AmountError);
        Assert.Null(vm.DescriptionError);
    }

    [Fact]
    public void A_date_far_in_the_future_is_refused()
    {
        var vm = Create();
        Fill(vm);
        vm.Date = new DateTimeOffset(new DateTime(2028, 1, 1));

        Assert.False(vm.Validate());
        Assert.Equal("That date is more than a year ahead.", vm.DateError);
    }

    [Fact]
    public void Without_any_account_the_dialog_says_so_and_cannot_submit()
    {
        var vm = new AddTransactionViewModel(new FakeFinanceApi(), Array.Empty<AccountBalance>(), Array.Empty<FinanceCategory>(), TestData.Today);
        Fill(vm);

        Assert.False(vm.HasAccounts);
        Assert.False(vm.Validate());
        Assert.Equal("Choose an account.", vm.AccountError);
    }
}
