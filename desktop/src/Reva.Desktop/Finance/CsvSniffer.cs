using System.Globalization;
using System.Text;

namespace Reva.Desktop.Finance;

public sealed record CsvProbe(string Delimiter, IReadOnlyList<string> Headers, IReadOnlyList<IReadOnlyList<string>> SampleRows);

public sealed record CsvGuess(
    string? Date,
    string? Description,
    string? Amount,
    string? Debit,
    string? Credit,
    string? Category,
    string DateFormat,
    bool DateFormatIsAmbiguous,
    string DecimalSeparator);

/// <summary>Looks at the first lines of a bank CSV on the client to propose a column mapping. It only
/// proposes: the person can change every choice, and the dry run shows how every row is read.</summary>
public static class CsvSniffer
{
    // (Kernel format, .NET format)
    private static readonly (string Kernel, string Net)[] DateFormats =
    {
        ("%Y-%m-%d", "yyyy-MM-dd"),
        ("%d/%m/%Y", "d/M/yyyy"),
        ("%m/%d/%Y", "M/d/yyyy"),
        ("%d-%m-%Y", "d-M-yyyy"),
        ("%d.%m.%Y", "d.M.yyyy"),
        ("%Y/%m/%d", "yyyy/M/d"),
        ("%d %b %Y", "d MMM yyyy"),
        ("%d/%m/%y", "d/M/yy"),
        ("%m/%d/%y", "M/d/yy"),
    };

    public static string DecodeText(byte[] data)
    {
        var bytes = data.AsSpan();
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF)
        {
            bytes = bytes[3..];
        }

        try
        {
            return new UTF8Encoding(false, throwOnInvalidBytes: true).GetString(bytes);
        }
        catch (DecoderFallbackException)
        {
            return Encoding.Latin1.GetString(bytes);
        }
    }

    public static CsvProbe? Probe(byte[] data, int sampleRows = 8)
    {
        var lines = DecodeText(data)
            .Split('\n')
            .Select(l => l.TrimEnd('\r'))
            .Where(l => l.Trim().Length > 0)
            .Take(sampleRows + 1)
            .ToList();
        if (lines.Count == 0)
        {
            return null;
        }

        var delimiter = new[] { ',', ';', '\t', '|' }
            .OrderByDescending(d => CountOutsideQuotes(lines[0], d))
            .First();
        if (CountOutsideQuotes(lines[0], delimiter) == 0)
        {
            return null;
        }

        var parsed = lines.Select(l => SplitLine(l, delimiter)).ToList();
        return new CsvProbe(delimiter.ToString(), parsed[0], parsed.Skip(1).ToList());
    }

    public static CsvGuess Guess(CsvProbe probe)
    {
        string? Find(Func<string, bool> match) =>
            probe.Headers.FirstOrDefault(h => match(h.Trim().ToLowerInvariant()));

        var date = Find(h => h.Contains("posted", StringComparison.Ordinal) && h.Contains("date", StringComparison.Ordinal))
            ?? Find(h => h.Contains("date", StringComparison.Ordinal));
        var description = Find(h => h is "description" or "memo" or "payee" or "details" or "narrative" or "name" or "merchant")
            ?? Find(h => h.Contains("descr", StringComparison.Ordinal) || h.Contains("memo", StringComparison.Ordinal)
                || h.Contains("payee", StringComparison.Ordinal) || h.Contains("detail", StringComparison.Ordinal));
        var debit = Find(h => h.Contains("debit", StringComparison.Ordinal) || h.Contains("withdrawal", StringComparison.Ordinal)
            || h.Contains("money out", StringComparison.Ordinal) || h.Contains("paid out", StringComparison.Ordinal));
        var credit = Find(h => h.Contains("credit", StringComparison.Ordinal) || h.Contains("deposit", StringComparison.Ordinal)
            || h.Contains("money in", StringComparison.Ordinal) || h.Contains("paid in", StringComparison.Ordinal));
        var amount = Find(h => h.Contains("amount", StringComparison.Ordinal) && !h.Contains("debit", StringComparison.Ordinal)
            && !h.Contains("credit", StringComparison.Ordinal));
        var category = Find(h => h.Contains("category", StringComparison.Ordinal));

        if (amount is not null)
        {
            debit = null;
            credit = null;
        }

        var (format, ambiguous) = GuessDateFormat(probe, date);
        var amountColumn = amount ?? debit;
        var decimalSeparator = GuessDecimalSeparator(probe, amountColumn);
        return new CsvGuess(date, description, amount, debit, credit, category, format, ambiguous, decimalSeparator);
    }

    public static IReadOnlyList<string> KernelDateFormats => DateFormats.Select(f => f.Kernel).ToList();

    private static (string Format, bool Ambiguous) GuessDateFormat(CsvProbe probe, string? dateColumn)
    {
        var index = dateColumn is null ? -1 : probe.Headers.ToList().IndexOf(dateColumn);
        var samples = index < 0
            ? new List<string>()
            : probe.SampleRows.Where(r => index < r.Count).Select(r => r[index].Trim()).Where(s => s.Length > 0).ToList();
        if (samples.Count == 0)
        {
            return ("%Y-%m-%d", false);
        }

        var fits = DateFormats
            .Where(f => samples.All(s => DateTime.TryParseExact(s, f.Net, CultureInfo.InvariantCulture, DateTimeStyles.None, out _)))
            .Select(f => f.Kernel)
            .ToList();
        if (fits.Count == 0)
        {
            return ("%Y-%m-%d", false);
        }

        var ambiguous = fits.Contains("%d/%m/%Y") && fits.Contains("%m/%d/%Y");
        return (fits[0], ambiguous);
    }

    private static string GuessDecimalSeparator(CsvProbe probe, string? amountColumn)
    {
        var index = amountColumn is null ? -1 : probe.Headers.ToList().IndexOf(amountColumn);
        if (index < 0)
        {
            return ".";
        }

        var values = probe.SampleRows.Where(r => index < r.Count).Select(r => r[index].Trim()).ToList();
        var commaDecimal = values.Count(v => System.Text.RegularExpressions.Regex.IsMatch(v, @"\d,\d{1,2}$") && !v.Contains('.', StringComparison.Ordinal));
        return commaDecimal > 0 ? "," : ".";
    }

    private static int CountOutsideQuotes(string line, char delimiter)
    {
        var inQuotes = false;
        var count = 0;
        foreach (var ch in line)
        {
            if (ch == '"')
            {
                inQuotes = !inQuotes;
            }
            else if (ch == delimiter && !inQuotes)
            {
                count++;
            }
        }

        return count;
    }

    private static IReadOnlyList<string> SplitLine(string line, char delimiter)
    {
        var fields = new List<string>();
        var current = new StringBuilder();
        var inQuotes = false;
        for (var i = 0; i < line.Length; i++)
        {
            var ch = line[i];
            if (inQuotes)
            {
                if (ch == '"' && i + 1 < line.Length && line[i + 1] == '"')
                {
                    current.Append('"');
                    i++;
                }
                else if (ch == '"')
                {
                    inQuotes = false;
                }
                else
                {
                    current.Append(ch);
                }
            }
            else if (ch == '"')
            {
                inQuotes = true;
            }
            else if (ch == delimiter)
            {
                fields.Add(current.ToString());
                current.Clear();
            }
            else
            {
                current.Append(ch);
            }
        }

        fields.Add(current.ToString());
        return fields;
    }
}
