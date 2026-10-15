using System.Net;
using System.Text;
using Reva.Desktop.Services;
using Reva.Desktop.Settings;
using Reva.Desktop.ViewModels;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Voice;

internal sealed class FakeCloudApi : ICloudSettingsApi
{
    public bool Enabled;
    public bool KeyConfigured;
    public Dictionary<string, bool> Domains = new()
    {
        ["memory"] = false, ["finance"] = false, ["health"] = false, ["personal"] = false,
        ["coach"] = false, ["career"] = false, ["learn"] = false, ["cyber"] = false,
    };
    public string? KeySeen;
    public string? FailWith;
    public int Gets;

    private SettingsResult<CloudSettingsSnapshot> Snapshot() =>
        SettingsResult<CloudSettingsSnapshot>.Success(new CloudSettingsSnapshot(
            Enabled,
            new Dictionary<string, bool>(Domains),
            KeyConfigured,
            "claude-opus-5-5",
            8,
            new CloudDisclosure(
                new[] { "What you say in a free-form question" },
                new[] { "Your voice or any audio" },
                "Anthropic (api.anthropic.com)",
                "If it is slow REVA answers with the local model.")));

    private SettingsResult<CloudSettingsSnapshot>? Refusal() =>
        FailWith is null
            ? null
            : SettingsResult<CloudSettingsSnapshot>.Failure(new SettingsError(FailWith));

    public Task<SettingsResult<CloudSettingsSnapshot>> GetAsync(CancellationToken ct = default)
    {
        Gets++;
        return Task.FromResult(Snapshot());
    }

    public Task<SettingsResult<CloudSettingsSnapshot>> SetEnabledAsync(bool enabled, CancellationToken ct = default)
    {
        if (Refusal() is { } refused)
        {
            return Task.FromResult(refused);
        }

        Enabled = enabled;
        return Task.FromResult(Snapshot());
    }

    public Task<SettingsResult<CloudSettingsSnapshot>> SetDomainAsync(string domain, bool allowed, CancellationToken ct = default)
    {
        Domains[domain] = allowed;
        return Task.FromResult(Snapshot());
    }

    public Task<SettingsResult<CloudSettingsSnapshot>> StoreKeyAsync(string apiKey, CancellationToken ct = default)
    {
        KeySeen = apiKey;
        KeyConfigured = true;
        return Task.FromResult(Snapshot());
    }

    public Task<SettingsResult<CloudSettingsSnapshot>> RemoveKeyAsync(CancellationToken ct = default)
    {
        KeyConfigured = false;
        Enabled = false;
        return Task.FromResult(Snapshot());
    }
}

public class CloudSettingsViewModelTests
{
    [Fact]
    public async Task Loading_shows_everything_off_the_sensitive_four_first_and_the_disclosure()
    {
        var vm = new CloudSettingsViewModel(new FakeCloudApi());

        await vm.LoadAsync();

        Assert.False(vm.Enabled);
        Assert.False(vm.KeyConfigured);
        Assert.False(vm.CanSwitchOn);
        Assert.Equal(new[] { "Memory", "Finance", "Health", "Personal", "Coach", "Career", "Learn", "Cyber" }, vm.Domains.Select(d => d.Label));
        Assert.All(vm.Domains, d => Assert.False(d.IsOn));
        Assert.Equal(4, vm.Domains.Count(d => d.StartsOff));
        Assert.Contains("Your voice or any audio", vm.NeverSent);
        Assert.Equal("Anthropic (api.anthropic.com)", vm.Provider);
    }

    [Fact]
    public async Task A_stored_key_unlocks_the_switch_and_is_not_kept_by_the_view_model()
    {
        var api = new FakeCloudApi();
        var vm = new CloudSettingsViewModel(api);
        await vm.LoadAsync();

        await vm.StoreKeyAsync("  sk-ant-api03-test-0123456789  ");

        Assert.Equal("sk-ant-api03-test-0123456789", api.KeySeen);
        Assert.True(vm.KeyConfigured && vm.CanSwitchOn);
        Assert.Equal("A key is stored in Windows Credential Manager.", vm.KeyStatus);
        Assert.False(vm.Enabled);
        Assert.DoesNotContain("sk-ant", vm.Message ?? string.Empty);
        Assert.DoesNotContain("sk-ant", vm.KeyStatus);
    }

    [Fact]
    public async Task An_empty_key_is_not_sent()
    {
        var api = new FakeCloudApi();
        var vm = new CloudSettingsViewModel(api);

        await vm.StoreKeyAsync("   ");

        Assert.Null(api.KeySeen);
        Assert.Equal("Paste your Anthropic API key first.", vm.Error);
    }

    [Fact]
    public async Task Switching_on_and_choosing_a_domain_round_trips_through_core()
    {
        var api = new FakeCloudApi { KeyConfigured = true };
        var vm = new CloudSettingsViewModel(api);
        await vm.LoadAsync();

        await vm.SetEnabledAsync(true);
        await vm.SetDomainAsync("coach", true);

        Assert.True(vm.Enabled && api.Enabled);
        Assert.True(api.Domains["coach"]);
        Assert.True(vm.Domains.Single(d => d.Id == "coach").IsOn);
        Assert.False(vm.Domains.Single(d => d.Id == "finance").IsOn);
    }

    [Fact]
    public async Task A_refused_change_shows_the_reason_and_reverts_to_what_core_holds()
    {
        var api = new FakeCloudApi { FailWith = "Add your Anthropic key first, then switch cloud on." };
        var vm = new CloudSettingsViewModel(api);
        await vm.LoadAsync();
        var gets = api.Gets;

        await vm.SetEnabledAsync(true);

        Assert.False(vm.Enabled);
        Assert.Equal("Add your Anthropic key first, then switch cloud on.", vm.Error);
        Assert.True(api.Gets > gets); // re-read, so the switch shows the real state
    }

    [Fact]
    public async Task Removing_the_key_turns_cloud_off()
    {
        var api = new FakeCloudApi { KeyConfigured = true, Enabled = true };
        var vm = new CloudSettingsViewModel(api);
        await vm.LoadAsync();

        await vm.RemoveKeyAsync();

        Assert.False(vm.Enabled);
        Assert.False(vm.KeyConfigured);
        Assert.False(vm.CanSwitchOn);
    }
}

public class CloudSettingsApiTests
{
    private sealed class Handler : HttpMessageHandler
    {
        public readonly List<(HttpMethod Method, string Path, string? Auth, string? Body)> Seen = new();
        public HttpStatusCode Status = HttpStatusCode.OK;
        public string Body = "{\"enabled\":false,\"domains\":{\"coach\":false},\"key_configured\":true,\"model\":\"m\",\"timeout_seconds\":8,\"disclosure\":{\"sent_when_on\":[\"a\"],\"never_sent\":[\"b\"],\"provider\":\"p\",\"fallback\":\"f\"}}";

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Seen.Add((
                request.Method,
                request.RequestUri!.AbsolutePath,
                request.Headers.Authorization?.ToString(),
                request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken)));
            return new HttpResponseMessage(Status) { Content = new StringContent(Body, Encoding.UTF8, "application/json") };
        }
    }

    private sealed class Tokens : ILocalTokenProvider
    {
        public bool Available = true;

        public Task<TokenLoadResult> GetTokenAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(Available ? TokenLoadResult.Available("tok") : TokenLoadResult.Unavailable());
    }

    private static (CloudSettingsApi api, Handler handler, Tokens tokens) Make()
    {
        var handler = new Handler();
        var tokens = new Tokens();
        var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        return (new CloudSettingsApi(http, tokens), handler, tokens);
    }

    [Fact]
    public async Task Calls_use_the_right_routes_methods_bodies_and_the_bearer_token()
    {
        var (api, handler, _) = Make();

        await api.GetAsync();
        await api.SetEnabledAsync(true);
        await api.SetDomainAsync("coach", true);
        await api.StoreKeyAsync("sk-ant-x");
        await api.RemoveKeyAsync();

        Assert.Equal(
            new[]
            {
                (HttpMethod.Get, "/v1/settings/cloud", (string?)null),
                (HttpMethod.Put, "/v1/settings/cloud", "{\"enabled\":true}"),
                (HttpMethod.Put, "/v1/settings/cloud", "{\"domains\":{\"coach\":true}}"),
                (HttpMethod.Put, "/v1/settings/cloud/key", "{\"api_key\":\"sk-ant-x\"}"),
                (HttpMethod.Delete, "/v1/settings/cloud/key", null),
            },
            handler.Seen.Select(s => (s.Method, s.Path, s.Body)));
        Assert.All(handler.Seen, s => Assert.Equal("Bearer tok", s.Auth));
    }

    [Fact]
    public async Task No_token_means_no_request()
    {
        var (api, handler, tokens) = Make();
        tokens.Available = false;

        var result = await api.GetAsync();

        Assert.False(result.IsSuccess);
        Assert.Empty(handler.Seen);
    }

    [Theory]
    [InlineData(409, "key_required", "Add your Anthropic key first, then switch cloud on.")]
    [InlineData(422, "invalid_key", "That doesn't look like an Anthropic API key (it starts with sk-ant-).")]
    [InlineData(503, "secret_store_unavailable", "Windows Credential Manager isn't available, so the key can't be stored.")]
    [InlineData(401, "Unauthorized", "REVA Core rejected local authentication.")]
    public async Task Errors_become_fixed_sentences_that_never_repeat_the_response(int status, string code, string expected)
    {
        var (api, handler, _) = Make();
        handler.Status = (HttpStatusCode)status;
        handler.Body = $"{{\"error\":\"{code}\",\"echo\":\"sk-ant-SECRET-0123456789\"}}";

        var result = await api.StoreKeyAsync("sk-ant-SECRET-0123456789");

        Assert.False(result.IsSuccess);
        Assert.Equal(expected, result.Error!.SafeMessage);
        Assert.DoesNotContain("SECRET", result.Error.SafeMessage);
    }

    [Fact]
    public async Task A_garbled_success_body_is_reported_not_thrown()
    {
        var (api, handler, _) = Make();
        handler.Body = "not json";

        var result = await api.GetAsync();

        Assert.False(result.IsSuccess);
    }
}

public class LiveVoiceNoticeTests
{
    [Fact]
    public async Task A_cloud_fallback_notice_is_shown_with_the_reply_and_cleared_on_the_next_turn()
    {
        var client = new FakeClient();
        var loop = new VoiceLoopController(client, new FakeCapture(), new FakePlayback(), null, _ => Task.CompletedTask);
        var vm = new LiveVoiceViewModel(loop);
        await vm.TurnOnAsync();

        client.Raise("assistant.text.final", 1, new { text = "Local answer.", provider = "local", notice = "The cloud model was too slow, so I answered with the local model." });
        Assert.Equal("The cloud model was too slow, so I answered with the local model.", vm.Notice);
        Assert.Equal("REVA: Local answer.", vm.Reply);

        client.Raise("speech.transcript.final", 2, new { text = "next question" });
        Assert.Null(vm.Notice);
    }
}
