using System.Globalization;
using System.Text;

namespace Reva.Desktop.Finance;

/// <summary>Money as integer minor units plus an ISO 4217 code, formatted the same way on every PC
/// (point decimals, comma thousands, culture-independent). Parsing refuses to round.</summary>
public static class MoneyFormat
{
    public const long MaxAbsMinor = 1_000_000_000_000_000; // 10^15, same bound as the Kernel

    public static int Exponent(string currency) => currency switch
    {
        "BIF" or "CLP" or "DJF" or "GNF" or "ISK" or "JPY" or "KMF" or "KRW" or "PYG" or "RWF" or "UGX" or "UYI"
            or "VND" or "VUV" or "XAF" or "XOF" or "XPF" => 0,
        "BHD" or "IQD" or "JOD" or "KWD" or "LYD" or "OMR" or "TND" => 3,
        _ => 2,
    };

    public static string Symbol(string currency) => currency switch
    {
        "USD" => "$",
        "EUR" => "€",
        "GBP" => "£",
        "INR" => "₹",
        "JPY" => "¥",
        _ => currency + " ",
    };

    /// <summary>"$1,234.56", "-$12.00". With <paramref name="showPlus"/>, positive values start with "+".</summary>
    public static string Format(long minor, string currency, bool showPlus = false)
    {
        var exponent = Exponent(currency);
        var magnitude = minor < 0 ? (ulong)(-(minor + 1)) + 1UL : (ulong)minor;
        var divisor = (ulong)Math.Pow(10, exponent);
        var whole = exponent == 0 ? magnitude : magnitude / divisor;
        var fraction = exponent == 0 ? 0UL : magnitude % divisor;
        var builder = new StringBuilder();
        builder.Append(minor < 0 ? "-" : showPlus && minor > 0 ? "+" : string.Empty);
        builder.Append(Symbol(currency));
        builder.Append(whole.ToString("N0", CultureInfo.InvariantCulture));
        if (exponent > 0)
        {
            builder.Append('.').Append(fraction.ToString(CultureInfo.InvariantCulture).PadLeft(exponent, '0'));
        }

        return builder.ToString();
    }

    /// <summary>Parse what a person types: "12", "12.5", "-12.50", "$1,234.50". Returns false with a
    /// short message for anything ambiguous or lossy.</summary>
    public static bool TryParse(string? text, string currency, out long minor, out string error)
    {
        minor = 0;
        error = string.Empty;
        var value = (text ?? string.Empty).Trim();
        if (value.Length == 0)
        {
            error = "Enter an amount.";
            return false;
        }

        var negative = false;
        if (value.StartsWith('(') && value.EndsWith(')'))
        {
            negative = true;
            value = value[1..^1].Trim();
        }

        if (value.StartsWith('-'))
        {
            negative = !negative;
            value = value[1..].Trim();
        }
        else if (value.StartsWith('+'))
        {
            value = value[1..].Trim();
        }

        value = value.Replace(Symbol(currency).Trim(), string.Empty, StringComparison.Ordinal).Trim();
        foreach (var symbol in new[] { "$", "€", "£", "₹", "¥" })
        {
            value = value.Replace(symbol, string.Empty, StringComparison.Ordinal);
        }

        if (System.Text.RegularExpressions.Regex.IsMatch(value, @"^\d+,\d{1,2}$"))
        {
            error = "Use a point for decimals, for example 12.50.";
            return false;
        }

        value = value.Replace(",", string.Empty, StringComparison.Ordinal).Replace(" ", string.Empty, StringComparison.Ordinal);
        if (value.Length == 0 || value.Count(c => c == '.') > 1 || value.Any(c => !char.IsAsciiDigit(c) && c != '.'))
        {
            error = "That is not a valid amount.";
            return false;
        }

        var parts = value.Split('.');
        var whole = parts[0].Length == 0 ? "0" : parts[0];
        var fraction = parts.Length > 1 ? parts[1] : string.Empty;
        var exponent = Exponent(currency);
        if (fraction.Length > exponent && fraction[exponent..].Any(c => c != '0'))
        {
            error = exponent == 0
                ? $"{currency} has no decimal places."
                : $"At most {exponent} decimal places for {currency}.";
            return false;
        }

        fraction = fraction.Length > exponent ? fraction[..exponent] : fraction.PadRight(exponent, '0');
        var digits = (whole + fraction).TrimStart('0');
        if (digits.Length == 0)
        {
            minor = 0;
            return true;
        }

        if (digits.Length > 16 || !long.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out var magnitude)
            || magnitude > MaxAbsMinor)
        {
            error = "That amount is too large.";
            return false;
        }

        minor = negative ? -magnitude : magnitude;
        return true;
    }
}
