using Reva.Desktop.Actions;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Tests.Actions;

public sealed class AppsAndScannerTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "reva-apps-" + Guid.NewGuid().ToString("N"));

    public AppsAndScannerTests() => Directory.CreateDirectory(_dir);

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    [Theory]
    [InlineData("Visual Studio Code", "visual-studio-code")]
    [InlineData("  Obsidian  ", "obsidian")]
    [InlineData("7-Zip File Manager", "app-7-zip-file-manager")]
    [InlineData("Caf\u00e9 !! Tool", "caf-tool")]
    [InlineData("A", null)]
    [InlineData("!!!", null)]
    [InlineData("This Is A Very Long Application Name That Goes On", "this-is-a-very-long-application")]
    public void Keys_are_short_lowercase_slugs(string name, string? key)
    {
        Assert.Equal(key, StartMenuScanner.Slug(name));
    }

    [Fact]
    public void The_scan_lists_shortcuts_skips_uninstallers_and_help_and_dedupes()
    {
        Directory.CreateDirectory(Path.Combine(_dir, "Tools"));
        foreach (var name in new[] { "Obsidian.lnk", "Uninstall Obsidian.lnk", "Tools\\Obsidian.lnk", "Tools\\Slack.lnk", "Slack Help.lnk", "notes.txt" })
        {
            File.WriteAllText(Path.Combine(_dir, name), string.Empty);
        }

        var found = StartMenuScanner.Scan(new[] { _dir, Path.Combine(_dir, "missing") });

        Assert.Equal(new[] { "obsidian", "slack" }, found.Select(a => a.Key).ToArray());
        Assert.All(found, a => Assert.EndsWith(".lnk", a.Shortcut));
    }

    [Fact]
    public void Built_in_apps_have_fixed_targets_that_a_stored_app_cannot_replace()
    {
        var store = new AppTargetStore(Path.Combine(_dir, "t.json"));

        store.Remember("notepad", "Evil", @"C:\evil.exe");

        Assert.Equal("notepad.exe", store.Find("notepad")!.OpenTarget);
        Assert.Equal("spotify:", store.Find("spotify")!.OpenTarget);
        Assert.Null(store.Find("never-heard-of-it"));
    }

    [Fact]
    public void An_approved_apps_target_and_learned_process_name_survive_a_restart()
    {
        var path = Path.Combine(_dir, "t.json");
        var first = new AppTargetStore(path);
        first.Remember("obsidian", "Obsidian", @"C:\Start\Obsidian.lnk");
        first.Learn("obsidian", "Obsidian");
        first.Learn("obsidian", "obsidian"); // same name, any case: once

        var again = new AppTargetStore(path).Find("obsidian")!;

        Assert.Equal(@"C:\Start\Obsidian.lnk", again.OpenTarget);
        Assert.Equal(new[] { "Obsidian" }, again.ProcessNames);
        new AppTargetStore(path).Forget("obsidian");
        Assert.Null(new AppTargetStore(path).Find("obsidian"));
    }

    [Fact]
    public void A_damaged_target_file_means_no_extra_apps_not_a_crash()
    {
        var path = Path.Combine(_dir, "t.json");
        File.WriteAllText(path, "{ not json");

        Assert.Null(new AppTargetStore(path).Find("obsidian"));
    }

    [Fact]
    public async Task Opening_the_page_reports_what_the_scan_found_and_remembers_the_shortcuts()
    {
        var api = new FakeApi();
        var store = new AppTargetStore(null);
        var model = new AppsViewModel(api, store, () => new[] { new DiscoveredApp("obsidian", "Obsidian", @"C:\S\Obsidian.lnk") });

        await model.LoadAsync();

        Assert.Equal(new[] { ("obsidian", "Obsidian") }, api.Discovered.Single().ToArray());
        Assert.Equal(@"C:\S\Obsidian.lnk", store.Find("obsidian")!.OpenTarget);
    }

    [Fact]
    public async Task Allow_sends_the_names_the_owner_typed_and_nothing_else()
    {
        var api = new FakeApi
        {
            Snapshot = new AppsSnapshot(
                new[] { new AppRow("notepad", "Notepad", new[] { "notepad" }, true) },
                new[] { new WaitingApp("obsidian", "Obsidian") }),
        };
        var model = new AppsViewModel(api, new AppTargetStore(null), () => Array.Empty<DiscoveredApp>());
        await model.LoadAsync();
        var row = Assert.Single(model.Waiting);
        row.Aliases = " my notes ,second brain,, ";

        await model.ApproveAsync(row);

        var approved = Assert.Single(api.Approved);
        Assert.Equal("obsidian", approved.Key);
        Assert.Equal(new[] { "my notes", "second brain" }, approved.Aliases.ToArray());
        Assert.Contains("Obsidian is allowed", model.Message);
    }
}
