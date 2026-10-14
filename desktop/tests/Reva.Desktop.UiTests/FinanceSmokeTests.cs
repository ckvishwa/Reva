using FlaUI.Core.AutomationElements;
using FlaUI.Core.Input;
using FlaUI.Core.Tools;
using FlaUI.Core.WindowsAPI;

namespace Reva.Desktop.UiTests;

/// <summary>
/// One shared app instance for all smoke tests (starting Core takes several seconds). Each test
/// calls <see cref="Finance.Open"/> and the idempotent <see cref="Finance.EnsureAccount"/>.
/// </summary>
public sealed class FinanceFixture : IDisposable
{
    public FinanceFixture()
    {
        Harness = new AppHarness();
        if (Environment.GetEnvironmentVariable("REVA_RUN_UI_TESTS") == "1")
        {
            Harness.WaitForCore();
        }
    }

    public AppHarness Harness { get; }

    public void Dispose() => Harness.Dispose();

    public void Open()
    {
        Harness.Require("Nav_finance").AsButton().Invoke();
        // Loading is done when either the empty state or the first account card is on screen.
        var ready = Retry.WhileFalse(
            () => Harness.Window.FindFirstDescendant(cf => cf.ByAutomationId("AccountCard")) is not null
                || Harness.Window.FindFirstDescendant(cf => cf.ByAutomationId("EmptyAddAccountButton")) is not null,
            TimeSpan.FromSeconds(30),
            TimeSpan.FromMilliseconds(250));
        Assert.True(ready.Success, "The Finance page never finished loading from Core.");
    }

    public void EnsureAccount()
    {
        if (Harness.Window.FindFirstDescendant(cf => cf.ByAutomationId("AccountCard")) is not null)
        {
            return;
        }

        Harness.Require("EmptyAddAccountButton").AsButton().Invoke();
        var dialog = Harness.Require("AddAccountDialog");
        Harness.Require("AccountName").AsTextBox().Text = "Smoke Checking";
        Harness.Require("AccountOpening").AsTextBox().Text = "100.00";
        ClickPrimary(dialog, "Add");
        Assert.True(Harness.GoneWithin("AddAccountDialog", TimeSpan.FromSeconds(20)), "The Add account dialog did not close.");
        Assert.NotNull(Harness.Find("AccountCard"));
    }

    public void ClickPrimary(AutomationElement dialog, string text)
    {
        var button = dialog.FindFirstDescendant(cf => cf.ByAutomationId("PrimaryButton"))
            ?? dialog.FindFirstDescendant(cf => cf.ByName(text))
            ?? Harness.Window.FindFirstDescendant(cf => cf.ByName(text));
        Assert.NotNull(button);
        button!.AsButton().Invoke();
    }

    public IReadOnlyList<string> TransactionRowNames() =>
        Harness.Window.FindAllDescendants(cf => cf.ByAutomationId("TransactionRow")).Select(r => r.Name).ToList();
}

[Collection("ui")] // one app window at a time: the tests use the keyboard and the foreground window
public class FinanceSmokeTests : IClassFixture<FinanceFixture>
{
    private readonly FinanceFixture _finance;

    public FinanceSmokeTests(FinanceFixture finance) => _finance = finance;

    private AppHarness App => _finance.Harness;

    [UiFact]
    public void Opening_Finance_and_adding_a_manual_transaction_shows_it_in_the_table()
    {
        _finance.Open();
        _finance.EnsureAccount();

        App.Require("AddTransactionButton").AsButton().Invoke();
        var dialog = App.Require("AddTransactionDialog");
        App.Require("TxAmount").AsTextBox().Text = "12.50";
        App.Require("TxDescription").AsTextBox().Text = "Smoke lunch";
        Retry.WhileFalse(
            () => App.Require("TxPreview").Name.Contains("12.50", StringComparison.Ordinal),
            TimeSpan.FromSeconds(5),
            TimeSpan.FromMilliseconds(100));
        _finance.ClickPrimary(dialog, "Save");

        Assert.True(
            App.GoneWithin("AddTransactionDialog", TimeSpan.FromSeconds(20)),
            "The Add transaction dialog did not close. Screenshot: " + App.Screenshot("add-transaction-stuck"));
        var shown = Retry.WhileFalse(
            () => _finance.TransactionRowNames().Any(n => n.Contains("Smoke lunch", StringComparison.Ordinal)),
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        Assert.True(shown.Success, "The new transaction never appeared in the table.");
        var row = _finance.TransactionRowNames().First(n => n.Contains("Smoke lunch", StringComparison.Ordinal));
        Assert.Contains("-$12.50", row);
        Assert.Contains("source manual", row);
    }

    [UiFact]
    public void Finance_can_be_used_with_the_keyboard_alone()
    {
        _finance.Open();
        _finance.EnsureAccount();

        // Enter on the focused button opens the dialog; the amount box takes focus; Tab moves on; Enter saves.
        App.BringToFront();
        App.Require("AddTransactionButton").Focus();
        var before = App.FocusedDescription();
        Keyboard.Type(VirtualKeyShort.ENTER);
        Assert.True(App.Find("AddTransactionDialog", TimeSpan.FromSeconds(8)) is not null, $"Enter did not open the dialog. Focus before: {before}; after: {App.FocusedDescription()}");
        Thread.Sleep(600); // let the dialog finish moving focus to the amount box
        var focusOnOpen = App.FocusedDescription();
        Keyboard.Type("7.25");
        Keyboard.Type(VirtualKeyShort.TAB);
        Keyboard.Type("Keyboard only");
        Keyboard.Type(VirtualKeyShort.ENTER);

        var shown = Retry.WhileFalse(
            () => _finance.TransactionRowNames().Any(n => n.Contains("Keyboard only", StringComparison.Ordinal)),
            TimeSpan.FromSeconds(20),
            TimeSpan.FromMilliseconds(250));
        var diagnostics = App.Find("TxAmount", TimeSpan.FromSeconds(1)) is { } amount
            ? $"dialog still open; amount='{amount.AsTextBox().Text}', description='{App.Find("TxDescription")?.AsTextBox().Text}', focus: {App.FocusedDescription()}"
            : "dialog closed";
        Assert.True(shown.Success, "A transaction added with the keyboard alone never appeared. Focus on open: " + focusOnOpen + ". " + diagnostics);

        // Escape closes a dialog without saving.
        App.BringToFront();
        App.Require("AddTransactionButton").Focus();
        Keyboard.Type(VirtualKeyShort.ENTER);
        Assert.NotNull(App.Find("AddTransactionDialog"));
        Thread.Sleep(600);
        Keyboard.Type(VirtualKeyShort.ESCAPE);
        Assert.True(App.GoneWithin("AddTransactionDialog", TimeSpan.FromSeconds(10)), "Escape did not close the dialog.");
    }

    [UiFact]
    public void Interactive_controls_have_names_are_focusable_and_meet_the_44_pixel_target()
    {
        _finance.Open();
        _finance.EnsureAccount();
        var minimum = (int)Math.Floor(44 * App.DpiScale("AddTransactionButton")) - 1; // 44 DIP in UI Automation pixels

        foreach (var id in new[]
        {
            "Nav_talk", "Nav_finance", "Nav_health", "AddTransactionButton", "AddAccountButton", "ImportButton",
            "ExportButton", "TransactionSearch", "SnapshotButton", "PrivacySync", "PrivacyHostedModel", "BudgetPeriod",
        })
        {
            var element = App.ScrollIntoView(id, minimum); // fully on screen, so its real height is reported
            Assert.False(string.IsNullOrWhiteSpace(element.Name) && id != "TransactionSearch", $"{id} has no accessible name.");
            Assert.True(element.Properties.IsKeyboardFocusable.ValueOrDefault, $"{id} is not keyboard focusable.");
            Assert.True(element.BoundingRectangle.Height >= minimum, $"{id} is {element.BoundingRectangle.Height}px tall (< {minimum}px); rect={element.BoundingRectangle}, offscreen={element.Properties.IsOffscreen.ValueOrDefault}, window={App.Window.BoundingRectangle}.");
        }

        Assert.Equal("Search transactions", App.Require("TransactionSearch").Name);
        Assert.Contains("can't pay, transfer, buy or log in to a bank", App.Require("NoMoneyMovementNote").Name);
    }

    [UiFact]
    public void Sections_that_are_not_built_say_coming_soon()
    {
        App.Require("Nav_health").AsButton().Invoke();

        var page = App.Require("ComingSoon");
        Assert.NotNull(page);
        Assert.Equal("Health, coming soon", App.Require("Nav_health").Name.Replace(", current page", string.Empty));
        Assert.Null(App.Window.FindFirstDescendant(cf => cf.ByAutomationId("AddTransactionButton")));
    }
}
