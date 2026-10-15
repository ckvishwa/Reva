using System.Text.Json;
using Reva.Desktop.Actions;

namespace Reva.Desktop.Tests.Actions;

/// <summary>Runs the vectors the Core's own tests run (tests/fixtures/grant_vectors.json), so a
/// grant the Core signs is accepted or refused for the same reason on both sides.</summary>
public sealed class GrantVerifierTests
{
    public static IEnumerable<object[]> Cases()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(VectorPath()));
        foreach (var item in document.RootElement.GetProperty("cases").EnumerateArray())
        {
            yield return new object[] { item.GetProperty("name").GetString()! };
        }
    }

    [Theory]
    [MemberData(nameof(Cases))]
    public void Shared_vectors_give_the_same_answer_as_the_core(string name)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(VectorPath()));
        var root = document.RootElement;
        var item = root.GetProperty("cases").EnumerateArray().Single(c => c.GetProperty("name").GetString() == name);
        using var verifier = new GrantVerifier(root.GetProperty("public_key_pem").GetString()!);

        Assert.True(GrantVerifier.TryParseGrant(item.GetProperty("grant"), out var grant));
        var result = verifier.Verify(
            grant,
            item.GetProperty("signature").GetString()!,
            DateTimeOffset.Parse(item.GetProperty("now").GetString()!),
            item.GetProperty("capability").GetString()!,
            GrantVerifier.ArgsHash(item.GetProperty("args")),
            item.GetProperty("target_device").GetString()!,
            item.GetProperty("actor").GetString()!);

        Assert.Equal(item.GetProperty("expect").GetString(), result.Reason);
        Assert.Equal(result.Reason == "OK", result.Ok);
    }

    [Fact]
    public void A_replayed_grant_is_refused_the_second_time()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(VectorPath()));
        var root = document.RootElement;
        var item = root.GetProperty("cases").EnumerateArray().First(c => c.GetProperty("name").GetString() == "valid");
        using var verifier = new GrantVerifier(root.GetProperty("public_key_pem").GetString()!);
        Assert.True(GrantVerifier.TryParseGrant(item.GetProperty("grant"), out var grant));

        GrantCheck Run() => verifier.Verify(
            grant,
            item.GetProperty("signature").GetString()!,
            DateTimeOffset.Parse(item.GetProperty("now").GetString()!),
            "windows.app.open",
            GrantVerifier.ArgsHash(item.GetProperty("args")),
            "local",
            "owner");

        Assert.True(Run().Ok);
        Assert.Equal("REPLAYED", Run().Reason);
    }

    [Fact]
    public void A_failed_check_does_not_use_up_the_key()
    {
        using var document = JsonDocument.Parse(File.ReadAllText(VectorPath()));
        var root = document.RootElement;
        var item = root.GetProperty("cases").EnumerateArray().First(c => c.GetProperty("name").GetString() == "valid");
        using var verifier = new GrantVerifier(root.GetProperty("public_key_pem").GetString()!);
        Assert.True(GrantVerifier.TryParseGrant(item.GetProperty("grant"), out var grant));
        var now = DateTimeOffset.Parse(item.GetProperty("now").GetString()!);
        var hash = GrantVerifier.ArgsHash(item.GetProperty("args"));
        var signature = item.GetProperty("signature").GetString()!;

        Assert.Equal("WRONG_TARGET", verifier.Verify(grant, signature, now, "windows.app.open", hash, "other", "owner").Reason);
        Assert.True(verifier.Verify(grant, signature, now, "windows.app.open", hash, "local", "owner").Ok);
    }

    [Fact]
    public void A_grant_with_a_missing_or_extra_field_does_not_parse()
    {
        using var missing = JsonDocument.Parse("""{"grant_id":"g"}""");
        using var extra = JsonDocument.Parse(
            """{"action_id":"a","actor":"o","args_hash":"h","capability":"c","expires_at":"e","grant_id":"g","idempotency_key":"i","issued_at":"t","target_device":"d","version":"1","extra":"x"}""");
        using var numeric = JsonDocument.Parse(
            """{"action_id":1,"actor":"o","args_hash":"h","capability":"c","expires_at":"e","grant_id":"g","idempotency_key":"i","issued_at":"t","target_device":"d","version":"1"}""");

        Assert.False(GrantVerifier.TryParseGrant(missing.RootElement, out _));
        Assert.False(GrantVerifier.TryParseGrant(extra.RootElement, out _));
        Assert.False(GrantVerifier.TryParseGrant(numeric.RootElement, out _));
    }

    [Fact]
    public void Only_whole_numbers_can_be_part_of_a_signed_action()
    {
        using var floating = JsonDocument.Parse("""{"amount":12.5}""");
        using var whole = JsonDocument.Parse("""{"b":2,"a":[1,true,null,"x"]}""");

        Assert.Throws<FormatException>(() => CanonicalJson.Write(floating.RootElement, false));
        Assert.Equal("""{"a":[1,true,null,"x"],"b":2}""", CanonicalJson.Write(whole.RootElement, false));
    }

    private static string VectorPath()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "grant_vectors.json");
            if (File.Exists(candidate))
            {
                return candidate;
            }

            directory = directory.Parent;
        }

        throw new FileNotFoundException("tests/fixtures/grant_vectors.json was not found above the test output");
    }
}
