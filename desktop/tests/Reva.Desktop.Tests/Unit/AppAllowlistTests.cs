using Reva.Desktop.Services;

namespace Reva.Desktop.Tests.Unit;

public class AppAllowlistTests
{
    [Theory]
    [InlineData("chrome", "chrome")]
    [InlineData("google chrome", "chrome")]
    [InlineData("edge", "edge")]
    [InlineData("microsoft edge", "edge")]
    [InlineData("notepad", "notepad")]
    [InlineData("calculator", "calculator")]
    [InlineData("calc", "calculator")]
    [InlineData("vscode", "vscode")]
    [InlineData("vs code", "vscode")]
    [InlineData("code", "vscode")]
    [InlineData("file explorer", "explorer")]
    [InlineData("explorer", "explorer")]
    [InlineData("settings", "settings")]
    [InlineData("windows settings", "settings")]
    public void FindByAlias_KnownAlias_ReturnsExpectedDescriptor(string alias, string expectedKey)
    {
        var descriptor = AppAllowlist.FindByAlias(alias);

        Assert.NotNull(descriptor);
        Assert.Equal(expectedKey, descriptor!.Key);
    }

    [Theory]
    [InlineData("photoshop")]
    [InlineData("chrome and tell me about tabs")]
    [InlineData("")]
    [InlineData("chrome; rm -rf")]
    [InlineData("chrome | more")]
    [InlineData("chrome && calc")]
    public void FindByAlias_UnknownOrInjectionLikeArgument_ReturnsNull(string argument)
    {
        Assert.Null(AppAllowlist.FindByAlias(argument));
    }

    [Fact]
    public void All_HasExactlySevenEntries()
    {
        Assert.Equal(7, AppAllowlist.All.Count);
    }

    [Fact]
    public void All_AliasesAreUniqueAcrossEntries()
    {
        // A duplicated alias would make the dictionary build throw at type-init
        // time — a startup crash, not a test failure. Catch it here instead.
        var aliases = AppAllowlist.All.SelectMany(d => d.Aliases).ToList();

        Assert.Equal(aliases.Count, aliases.Distinct().Count());
    }

    [Fact]
    public void All_AliasesAreAlreadyLowercase()
    {
        // FindByAlias uses an Ordinal dictionary against a lowercased argument;
        // an uppercase alias in the table would be permanently unreachable.
        foreach (var alias in AppAllowlist.All.SelectMany(d => d.Aliases))
        {
            Assert.Equal(alias.ToLowerInvariant(), alias);
        }
    }

    [Theory]
    [InlineData("explorer")]
    [InlineData("settings")]
    public void All_ExplorerAndSettings_AreOpenOnly(string key)
    {
        Assert.Null(AppAllowlist.All.Single(d => d.Key == key).CloseProcessNames);
    }

    [Theory]
    [InlineData("chrome")]
    [InlineData("edge")]
    [InlineData("notepad")]
    [InlineData("calculator")]
    [InlineData("vscode")]
    public void All_ConsumerApps_SupportClose(string key)
    {
        var descriptor = AppAllowlist.All.Single(d => d.Key == key);

        Assert.NotNull(descriptor.CloseProcessNames);
        Assert.NotEmpty(descriptor.CloseProcessNames!);
    }

    [Fact]
    public void All_NoEntryTargetsAShellOrRevaItself()
    {
        var forbidden = new[] { "cmd", "powershell", "pwsh", "wscript", "cscript", "reva" };

        foreach (var descriptor in AppAllowlist.All)
        {
            var target = descriptor.OpenTarget.ToLowerInvariant();
            foreach (var bad in forbidden)
            {
                Assert.False(
                    target.Contains(bad, StringComparison.Ordinal),
                    $"Allowlist entry '{descriptor.Key}' targets '{descriptor.OpenTarget}'.");
            }

            foreach (var processName in descriptor.CloseProcessNames ?? Array.Empty<string>())
            {
                Assert.DoesNotContain(processName.ToLowerInvariant(), forbidden);
            }
        }
    }
}
