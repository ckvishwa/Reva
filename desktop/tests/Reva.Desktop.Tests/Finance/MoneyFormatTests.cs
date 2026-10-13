using Reva.Desktop.Finance;

namespace Reva.Desktop.Tests.Finance;

public class MoneyFormatTests
{
    [Theory]
    [InlineData(123_450L, "USD", "$1,234.50")]
    [InlineData(-1_200L, "USD", "-$12.00")]
    [InlineData(5L, "USD", "$0.05")]
    [InlineData(0L, "USD", "$0.00")]
    [InlineData(1_234_567_890L, "EUR", "€12,345,678.90")]
    [InlineData(500L, "JPY", "¥500")]
    [InlineData(1_234L, "KWD", "KWD 1.234")]
    [InlineData(-5L, "CAD", "-CAD 0.05")]
    public void Formats_minor_units_the_same_way_on_every_pc(long minor, string currency, string expected) =>
        Assert.Equal(expected, MoneyFormat.Format(minor, currency));

    [Fact]
    public void Formats_a_plus_sign_only_when_asked_and_only_for_positive_amounts()
    {
        Assert.Equal("+$3,000.00", MoneyFormat.Format(300_000, "USD", showPlus: true));
        Assert.Equal("$0.00", MoneyFormat.Format(0, "USD", showPlus: true));
        Assert.Equal("-$1.00", MoneyFormat.Format(-100, "USD", showPlus: true));
    }

    [Fact]
    public void Formatting_ignores_the_current_culture()
    {
        var previous = System.Globalization.CultureInfo.CurrentCulture;
        try
        {
            System.Globalization.CultureInfo.CurrentCulture = new System.Globalization.CultureInfo("de-DE");
            Assert.Equal("$1,234.50", MoneyFormat.Format(123_450, "USD"));
        }
        finally
        {
            System.Globalization.CultureInfo.CurrentCulture = previous;
        }
    }

    [Fact]
    public void Handles_the_most_negative_amount_without_overflow() =>
        Assert.StartsWith("-$", MoneyFormat.Format(long.MinValue, "USD"));

    [Theory]
    [InlineData("12", "USD", 1_200L)]
    [InlineData("12.5", "USD", 1_250L)]
    [InlineData("12.50", "USD", 1_250L)]
    [InlineData("-12.50", "USD", -1_250L)]
    [InlineData("$1,234.50", "USD", 123_450L)]
    [InlineData("(3.99)", "USD", -399L)]
    [InlineData("  7  ", "USD", 700L)]
    [InlineData("500", "JPY", 500L)]
    [InlineData("1.234", "KWD", 1_234L)]
    [InlineData("12.500", "USD", 1_250L)]
    [InlineData(".5", "USD", 50L)]
    [InlineData("0", "USD", 0L)]
    public void Parses_what_people_type(string text, string currency, long expected)
    {
        Assert.True(MoneyFormat.TryParse(text, currency, out var minor, out var error), error);
        Assert.Equal(expected, minor);
    }

    [Theory]
    [InlineData("", "Enter an amount.")]
    [InlineData("   ", "Enter an amount.")]
    [InlineData("abc", "That is not a valid amount.")]
    [InlineData("1.2.3", "That is not a valid amount.")]
    [InlineData("12.345", "At most 2 decimal places for USD.")]
    [InlineData("12,50", "Use a point for decimals, for example 12.50.")]
    [InlineData("99999999999999999999", "That amount is too large.")]
    public void Refuses_ambiguous_or_lossy_amounts_with_a_short_message(string text, string message)
    {
        Assert.False(MoneyFormat.TryParse(text, "USD", out _, out var error));
        Assert.Equal(message, error);
    }

    [Fact]
    public void Currencies_without_decimals_refuse_fractions()
    {
        Assert.False(MoneyFormat.TryParse("5.5", "JPY", out _, out var error));
        Assert.Equal("JPY has no decimal places.", error);
    }

    [Fact]
    public void Format_and_parse_round_trip()
    {
        foreach (var minor in new long[] { 0, 1, 99, 100, -100, 123_456_789, -987_654_321 })
        {
            var text = MoneyFormat.Format(minor, "USD").Replace("$", string.Empty);
            Assert.True(MoneyFormat.TryParse(text, "USD", out var back, out var error), error);
            Assert.Equal(minor, back);
        }
    }
}
