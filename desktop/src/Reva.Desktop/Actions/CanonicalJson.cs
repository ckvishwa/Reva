using System.Globalization;
using System.Text;
using System.Text.Json;

namespace Reva.Desktop.Actions;

/// <summary>One spelling for a JSON value, matching Python's
/// <c>json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=...)</c> byte for byte, so
/// the argument hash and the signed grant bytes agree with the Core's (shared vectors in
/// tests/fixtures/grant_vectors.json). Numbers other than whole integers are refused: an executor
/// only ever acts on text arguments, and a float spelled differently by two languages would be a
/// hole in the check.</summary>
public static class CanonicalJson
{
    public static string Write(JsonElement value, bool ensureAscii)
    {
        var builder = new StringBuilder();
        Append(builder, value, ensureAscii);
        return builder.ToString();
    }

    public static byte[] Bytes(JsonElement value, bool ensureAscii) =>
        Encoding.UTF8.GetBytes(Write(value, ensureAscii));

    private static void Append(StringBuilder builder, JsonElement value, bool ensureAscii)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                builder.Append('{');
                var first = true;
                foreach (var property in value.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
                {
                    if (!first)
                    {
                        builder.Append(',');
                    }

                    first = false;
                    AppendString(builder, property.Name, ensureAscii);
                    builder.Append(':');
                    Append(builder, property.Value, ensureAscii);
                }

                builder.Append('}');
                break;
            case JsonValueKind.Array:
                builder.Append('[');
                var index = 0;
                foreach (var item in value.EnumerateArray())
                {
                    if (index++ > 0)
                    {
                        builder.Append(',');
                    }

                    Append(builder, item, ensureAscii);
                }

                builder.Append(']');
                break;
            case JsonValueKind.String:
                AppendString(builder, value.GetString() ?? string.Empty, ensureAscii);
                break;
            case JsonValueKind.Number:
                if (!value.TryGetInt64(out var whole))
                {
                    throw new FormatException("only whole numbers can be part of a signed action");
                }

                builder.Append(whole.ToString(CultureInfo.InvariantCulture));
                break;
            case JsonValueKind.True:
                builder.Append("true");
                break;
            case JsonValueKind.False:
                builder.Append("false");
                break;
            case JsonValueKind.Null:
                builder.Append("null");
                break;
            default:
                throw new FormatException("unsupported JSON value");
        }
    }

    /// <summary>Python's string escaping: quote, backslash and control characters; everything else
    /// is kept as is, or written as \uXXXX (with surrogate pairs) when <paramref name="ensureAscii"/>.</summary>
    public static string WriteString(string text, bool ensureAscii)
    {
        var builder = new StringBuilder();
        AppendString(builder, text, ensureAscii);
        return builder.ToString();
    }

    private static void AppendString(StringBuilder builder, string text, bool ensureAscii)
    {
        builder.Append('"');
        foreach (var c in text)
        {
            switch (c)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                case '\b': builder.Append("\\b"); break;
                case '\f': builder.Append("\\f"); break;
                default:
                    if (c < 0x20 || (ensureAscii && c > 0x7f))
                    {
                        builder.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        builder.Append(c);
                    }

                    break;
            }
        }

        builder.Append('"');
    }
}
