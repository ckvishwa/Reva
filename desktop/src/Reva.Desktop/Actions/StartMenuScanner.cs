using System.Text;
using System.Text.RegularExpressions;

namespace Reva.Desktop.Actions;

public sealed record DiscoveredApp(string Key, string DisplayName, string Shortcut);

/// <summary>Finds apps in the Start Menu so the owner can choose which ones REVA may open. Finding an
/// app allows nothing: it only goes to the "waiting for you" list on the Apps &amp; Actions page.</summary>
public static partial class StartMenuScanner
{
    private const int MaxApps = 200;
    private const int MaxKeyLength = 32;

    private static readonly string[] SkipWords =
    {
        "uninstall", "readme", "help", "documentation", "release notes", "website", "license", "manual", "support",
    };

    public static IReadOnlyList<DiscoveredApp> Scan(IEnumerable<string> roots)
    {
        var found = new Dictionary<string, DiscoveredApp>(StringComparer.Ordinal);
        foreach (var root in roots)
        {
            if (!Directory.Exists(root))
            {
                continue;
            }

            IEnumerable<string> files;
            try
            {
                files = Directory.EnumerateFiles(root, "*.lnk", SearchOption.AllDirectories);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                continue;
            }

            foreach (var file in files)
            {
                var name = Path.GetFileNameWithoutExtension(file).Trim();
                if (name.Length == 0 || SkipWords.Any(w => name.Contains(w, StringComparison.OrdinalIgnoreCase)))
                {
                    continue;
                }

                var key = Slug(name);
                if (key is null || found.ContainsKey(key))
                {
                    continue;
                }

                found[key] = new DiscoveredApp(key, name.Length > 60 ? name[..60] : name, file);
                if (found.Count >= MaxApps)
                {
                    return found.Values.OrderBy(a => a.DisplayName, StringComparer.OrdinalIgnoreCase).ToList();
                }
            }
        }

        return found.Values.OrderBy(a => a.DisplayName, StringComparer.OrdinalIgnoreCase).ToList();
    }

    public static IEnumerable<string> DefaultRoots()
    {
        yield return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu), "Programs");
        yield return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs");
    }

    /// <summary>A key like <c>visual-studio-code</c>: lowercase letters, digits and hyphens, starting with
    /// a letter, at most 32 characters. Null when nothing usable is left.</summary>
    public static string? Slug(string name)
    {
        var builder = new StringBuilder();
        foreach (var c in name.ToLowerInvariant())
        {
            builder.Append(c is >= 'a' and <= 'z' or >= '0' and <= '9' ? c : '-');
        }

        var slug = Dashes().Replace(builder.ToString(), "-").Trim('-');
        if (slug.Length == 0)
        {
            return null;
        }

        if (!char.IsAsciiLetter(slug[0]))
        {
            slug = "app-" + slug;
        }

        if (slug.Length > MaxKeyLength)
        {
            slug = slug[..MaxKeyLength].TrimEnd('-');
        }

        return slug.Length >= 2 ? slug : null;
    }

    [GeneratedRegex("-{2,}")]
    private static partial Regex Dashes();
}
