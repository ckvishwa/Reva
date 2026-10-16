using System.Text.Json;
using Reva.Desktop.Actions;
using Reva.Desktop.Settings;
using Reva.Desktop.ViewModels;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Tests.Actions;

public sealed class ActionCoordinatorTests : IDisposable
{
    private static readonly DateTimeOffset VectorNow = DateTimeOffset.Parse("2026-10-15T12:00:00+00:00");

    private readonly JsonDocument _vectors = JsonDocument.Parse(File.ReadAllText(VectorPath()));
    private readonly FakeApi _api = new();
    private readonly FakeLauncher _launcher = new();
    private readonly FakeWindows _windows = new();
    private readonly GrantVerifier _verifier;

    public ActionCoordinatorTests()
    {
        _verifier = new GrantVerifier(_vectors.RootElement.GetProperty("public_key_pem").GetString()!);
    }

    public void Dispose()
    {
        _verifier.Dispose();
        _vectors.Dispose();
    }

    private AppActionExecutor Executor() =>
        new(_verifier, new FakeTargets(), _windows, _launcher, new TickingTime(VectorNow), poll: TimeSpan.Zero);

    private VoiceEvent Proposed(string vectorName = "valid")
    {
        var item = _vectors.RootElement.GetProperty("cases").EnumerateArray().Single(c => c.GetProperty("name").GetString() == vectorName);
        var json =
            "{\"action_id\":\"act-0001\",\"capability\":\"windows.app.open\",\"tier\":\"T1\",\"status\":\"granted\",\"reason\":\"OK\","
            + "\"order\":{\"grant\":" + item.GetProperty("grant").GetRawText()
            + ",\"signature\":\"" + item.GetProperty("signature").GetString() + "\","
            + "\"capability\":\"windows.app.open\",\"args\":" + item.GetProperty("args").GetRawText()
            + ",\"target_device_id\":\"local\"}}";
        return new VoiceEvent("action.proposed", 1, JsonDocument.Parse(json).RootElement.Clone());
    }

    [Fact]
    public async Task A_proposed_order_is_executed_and_the_report_with_evidence_goes_to_the_core()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x40), 99, "notepad"));
        var coordinator = new ActionCoordinator(_api, Executor());

        coordinator.OnCoreEvent(Proposed());
        await _api.WaitForReportAsync();

        var (actionId, grantId, report) = Assert.Single(_api.Reports);
        Assert.Equal("act-0001", actionId);
        Assert.Equal("grant-valid", grantId);
        Assert.Equal("verified", report.Status);
        Assert.Equal("pid:99 window:0x40", report.Evidence!.Reference);
    }

    [Fact]
    public async Task A_process_without_a_window_is_reported_as_unknown()
    {
        _launcher.StartPid = 3;
        _launcher.Running = new[] { 3 };
        var coordinator = new ActionCoordinator(_api, Executor());

        coordinator.OnCoreEvent(Proposed());
        await _api.WaitForReportAsync();

        Assert.Equal("unknown", Assert.Single(_api.Reports).Report.Status);
    }

    [Fact]
    public async Task Without_an_executor_the_order_is_reported_failed_and_nothing_starts()
    {
        var coordinator = new ActionCoordinator(_api, (AppActionExecutor?)null);

        coordinator.OnCoreEvent(Proposed());
        await _api.WaitForReportAsync();

        Assert.Equal("failed", Assert.Single(_api.Reports).Report.Status);
        Assert.Equal(0, _launcher.Starts);
    }

    [Fact]
    public async Task The_executor_is_built_late_when_the_grant_key_appears_after_the_app_started()
    {
        var attempts = 0;
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x41), 7, "notepad"));
        var coordinator = new ActionCoordinator(_api, () => ++attempts < 2 ? null : Executor());

        coordinator.OnCoreEvent(Proposed()); // key not there yet: failed
        await _api.WaitForReportAsync();
        coordinator.OnCoreEvent(Proposed("valid_close")); // key there now, but a different grant
        await _api.WaitForReportAsync(2);

        Assert.Equal(2, attempts);
        Assert.Equal("failed", _api.Reports[0].Report.Status);
    }

    [Fact]
    public async Task The_same_order_twice_runs_once()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x42), 5, "notepad"));
        var coordinator = new ActionCoordinator(_api, Executor());

        coordinator.OnCoreEvent(Proposed());
        coordinator.OnCoreEvent(Proposed());
        await _api.WaitForReportAsync();
        await Task.Delay(50);

        Assert.Equal(1, _launcher.Starts);
        Assert.Single(_api.Reports);
    }

    [Fact]
    public void An_approval_request_shows_the_cores_sentence_and_the_outcome_closes_the_card()
    {
        var coordinator = new ActionCoordinator(_api, (AppActionExecutor?)null);
        var shown = new List<ApprovalCard>();
        var closed = new List<string>();
        var said = new List<(string, string)>();
        coordinator.CardRequested += shown.Add;
        coordinator.CardClosed += closed.Add;
        coordinator.Outcome += (id, text) => said.Add((id, text));

        coordinator.OnCoreEvent(Event("action.approval_required", """{"action_id":"a1","capability":"finance.add_transaction","status":"awaiting_approval","prompt":"Add $12.00 for Food · Dining? Confirm on screen."}"""));
        coordinator.OnCoreEvent(Event("action.outcome", """{"action_id":"a1","capability":"finance.add_transaction","status":"verified","speak":"Saved."}"""));

        Assert.Equal("Add $12.00 for Food · Dining? Confirm on screen.", Assert.Single(shown).Prompt);
        Assert.Equal(new[] { "a1" }, closed);
        Assert.Equal(("a1", "Saved."), Assert.Single(said));
    }

    [Fact]
    public async Task Confirm_sends_a_click_and_a_returned_order_is_executed()
    {
        _launcher.RunningSequence = new Queue<int[]>(new[] { new[] { 7 }, Array.Empty<int>() });
        var coordinator = new ActionCoordinator(_api, Executor());
        var closed = new List<string>();
        coordinator.CardClosed += closed.Add;
        _api.DecideResult = ParseState(Proposed().Payload);

        await coordinator.DecideAsync("act-0001", approve: true);

        Assert.Equal(new[] { ("act-0001", true) }, _api.Decisions.ToArray());
        Assert.Equal(new[] { "act-0001" }, closed);
        // The vector's grant is an open grant, so the report exists (verified or not) once the order ran.
        Assert.Single(_api.Reports);
    }

    [Fact]
    public async Task A_confirm_the_core_did_not_accept_leaves_the_card_up()
    {
        var coordinator = new ActionCoordinator(_api, (AppActionExecutor?)null);
        var closed = new List<string>();
        coordinator.CardClosed += closed.Add;
        _api.DecideResult = new ActionState("a1", "finance.add_transaction", "awaiting_approval", null, "p", null, null);

        await coordinator.DecideAsync("a1", approve: true);

        Assert.Empty(closed);
        Assert.Empty(_api.Reports);
    }

    [Fact]
    public async Task Not_now_closes_the_card_and_runs_nothing()
    {
        var coordinator = new ActionCoordinator(_api, Executor());
        var closed = new List<string>();
        coordinator.CardClosed += closed.Add;
        _api.DecideResult = new ActionState("a1", "windows.app.close", "denied", "Okay, I won't do that.", null, null, null);

        await coordinator.DecideAsync("a1", approve: false);

        Assert.Equal(new[] { ("a1", false) }, _api.Decisions.ToArray());
        Assert.Equal(new[] { "a1" }, closed);
        Assert.Equal(0, _launcher.Starts);
    }

    [Fact]
    public async Task A_failed_confirm_call_keeps_the_card()
    {
        var coordinator = new ActionCoordinator(_api, (AppActionExecutor?)null);
        var closed = new List<string>();
        coordinator.CardClosed += closed.Add;
        _api.DecideResult = null;

        await coordinator.DecideAsync("a1", approve: true);

        Assert.Empty(closed);
    }

    [Fact]
    public async Task The_card_view_model_shows_one_card_at_a_time_and_disables_buttons_while_deciding()
    {
        var coordinator = new ActionCoordinator(_api, (AppActionExecutor?)null);
        var model = new ApprovalCardViewModel(coordinator, action => action());
        _api.DecideResult = new ActionState("a1", "finance.add_transaction", "verified", "Saved.", null, null, null);

        model.Add(new ApprovalCard("a1", "First?", null));
        model.Add(new ApprovalCard("a2", "Second?", null));

        Assert.True(model.IsVisible);
        Assert.Equal("First?", model.Prompt);
        Assert.Equal("1 more waiting", model.Waiting);
        await model.ConfirmAsync();
        Assert.Equal("Second?", model.Prompt);
        Assert.Equal(new[] { ("a1", true) }, _api.Decisions.ToArray());
        model.Remove("a2");
        Assert.False(model.IsVisible);
    }

    // ------------------------------------------------------------ phone requests (C2)

    private PhoneRequest PhoneOrder(string vectorName = "valid")
    {
        var order = ActionsApi.ParseOrder(Proposed(vectorName).Payload)!;
        return new PhoneRequest("act-0001", order.Capability, "granted", null, null, "Pixel 8", order);
    }

    [Fact]
    public async Task A_phone_order_is_executed_and_reported_like_any_other_order()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x50), 21, "notepad"));
        var coordinator = new ActionCoordinator(_api, Executor());

        await coordinator.OnPhoneRequestAsync(PhoneOrder());

        var (actionId, grantId, report) = Assert.Single(_api.Reports);
        Assert.Equal(("act-0001", "grant-valid", "verified"), (actionId, grantId, report.Status));
        Assert.Equal(1, _launcher.Starts);
    }

    [Fact]
    public async Task The_same_phone_order_twice_runs_once()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x51), 22, "notepad"));
        var coordinator = new ActionCoordinator(_api, Executor());

        await coordinator.OnPhoneRequestAsync(PhoneOrder());
        await coordinator.OnPhoneRequestAsync(PhoneOrder());

        Assert.Equal(1, _launcher.Starts);
        Assert.Single(_api.Reports);
    }

    [Theory]
    [InlineData("wrong_signer")]
    [InlineData("tampered_args_hash")]
    [InlineData("substituted_args")]
    [InlineData("malformed_signature")]
    [InlineData("not_base64")]
    public async Task A_phone_order_the_executor_cannot_verify_starts_nothing_and_is_reported_failed(string vector)
    {
        var coordinator = new ActionCoordinator(_api, Executor());

        await coordinator.OnPhoneRequestAsync(PhoneOrder(vector));

        Assert.Equal(0, _launcher.Starts);
        Assert.Equal("failed", Assert.Single(_api.Reports).Report.Status);
    }

    [Theory]
    [InlineData("expired")]
    [InlineData("from_the_future")]
    public async Task A_phone_order_outside_its_validity_window_starts_nothing(string vector)
    {
        var at = DateTimeOffset.Parse(_vectors.RootElement.GetProperty("cases").EnumerateArray()
            .Single(c => c.GetProperty("name").GetString() == vector).GetProperty("now").GetString()!);
        var executor = new AppActionExecutor(_verifier, new FakeTargets(), _windows, _launcher, new TickingTime(at), poll: TimeSpan.Zero);
        var coordinator = new ActionCoordinator(_api, executor);

        await coordinator.OnPhoneRequestAsync(PhoneOrder(vector));

        Assert.Equal(0, _launcher.Starts);
        Assert.Equal("failed", Assert.Single(_api.Reports).Report.Status);
    }

    [Fact]
    public async Task A_phone_request_that_waits_for_approval_becomes_a_card_that_names_the_phone()
    {
        var coordinator = new ActionCoordinator(_api, Executor());
        var shown = new List<ApprovalCard>();
        coordinator.CardRequested += shown.Add;
        var request = new PhoneRequest("ph-1", "windows.app.close", "awaiting_approval", "Close Calculator? Approve it on screen.", null, "Pixel 8", null);

        await coordinator.OnPhoneRequestAsync(request);

        var card = Assert.Single(shown);
        Assert.Equal(("ph-1", "Close Calculator? Approve it on screen.", "Pixel 8"), (card.ActionId, card.Prompt, card.From));
        Assert.Empty(_api.Reports);
        Assert.Equal(0, _launcher.Starts);
        var model = new ApprovalCardViewModel(coordinator, action => action());
        model.Add(card);
        Assert.Equal("Pixel 8 asks: Close Calculator? Approve it on screen.", model.Prompt);
    }

    [Fact]
    public async Task A_phone_request_with_no_order_and_no_prompt_does_nothing()
    {
        var coordinator = new ActionCoordinator(_api, Executor());
        var shown = new List<ApprovalCard>();
        coordinator.CardRequested += shown.Add;

        await coordinator.OnPhoneRequestAsync(new PhoneRequest("ph-1", "windows.app.open", "refused", null, null, "Pixel 8", null));
        await coordinator.OnPhoneRequestAsync(new PhoneRequest("ph-2", "windows.app.close", "awaiting_approval", "", null, "Pixel 8", null));

        Assert.Empty(shown);
        Assert.Empty(_api.Reports);
    }

    private static VoiceEvent Event(string kind, string json) =>
        new(kind, 1, JsonDocument.Parse(json).RootElement.Clone());

    private static ActionState? ParseState(JsonElement payload) => ActionsApi.ParseAction(payload);

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

        throw new FileNotFoundException("tests/fixtures/grant_vectors.json not found");
    }
}

internal sealed class FakeApi : IActionsApi
{
    private TaskCompletionSource _reported = new(TaskCreationOptions.RunContinuationsAsynchronously);

    public List<(string ActionId, string GrantId, ActionReport Report)> Reports { get; } = new();

    public List<(string ActionId, bool Approve)> Decisions { get; } = new();

    public ActionState? DecideResult { get; set; }

    public List<(long After, TimeSpan Wait)> PhoneRequestCalls { get; } = new();

    public Queue<SettingsResult<PhoneRequests>> PhoneResponses { get; } = new();

    public Func<long, TimeSpan, CancellationToken, Task>? OnPhoneRequests { get; set; }

    public async Task<SettingsResult<PhoneRequests>> GetPhoneRequestsAsync(long after, TimeSpan wait, CancellationToken ct = default)
    {
        PhoneRequestCalls.Add((after, wait));
        if (OnPhoneRequests is not null)
        {
            await OnPhoneRequests(after, wait, ct);
        }

        return PhoneResponses.Count > 0
            ? PhoneResponses.Dequeue()
            : SettingsResult<PhoneRequests>.Success(new PhoneRequests(after, Array.Empty<PhoneRequest>()));
    }

    public async Task WaitForReportAsync(int count = 1)
    {
        for (var i = 0; i < 200 && Reports.Count < count; i++)
        {
            await Task.Delay(10);
        }

        Assert.True(Reports.Count >= count, "the executor never reported");
    }

    public Task<SettingsResult<ActionState>> DecideAsync(string actionId, bool approve, CancellationToken ct = default)
    {
        Decisions.Add((actionId, approve));
        return Task.FromResult(DecideResult is null
            ? SettingsResult<ActionState>.Failure(new SettingsError("down"))
            : SettingsResult<ActionState>.Success(DecideResult));
    }

    public Task<SettingsResult<ActionState>> ReportAsync(string actionId, string grantId, ActionReport report, CancellationToken ct = default)
    {
        Reports.Add((actionId, grantId, report));
        _reported.TrySetResult();
        return Task.FromResult(SettingsResult<ActionState>.Success(
            new ActionState(actionId, string.Empty, report.Status, null, null, null, null)));
    }

    public List<IReadOnlyList<(string, string)>> Discovered { get; } = new();

    public List<(string Key, string? Name, IReadOnlyList<string> Aliases)> Approved { get; } = new();

    public AppsSnapshot Snapshot { get; set; } = new(Array.Empty<AppRow>(), Array.Empty<WaitingApp>());

    public Task<SettingsResult<AppsSnapshot>> GetAppsAsync(CancellationToken ct = default) =>
        Task.FromResult(SettingsResult<AppsSnapshot>.Success(Snapshot));

    public Task<SettingsResult<AppsSnapshot>> ReportDiscoveredAsync(IReadOnlyList<(string Key, string DisplayName)> found, CancellationToken ct = default)
    {
        Discovered.Add(found);
        return GetAppsAsync(ct);
    }

    public Task<SettingsResult<AppsSnapshot>> ApproveAppAsync(string key, string? displayName, IReadOnlyList<string> aliases, CancellationToken ct = default)
    {
        Approved.Add((key, displayName, aliases));
        return GetAppsAsync(ct);
    }

    public Task<SettingsResult<AppsSnapshot>> RemoveAppAsync(string key, CancellationToken ct = default) => GetAppsAsync(ct);

    public Task<SettingsResult<IReadOnlyList<ActivityRow>>> GetActivityAsync(int limit, CancellationToken ct = default) =>
        Task.FromResult(SettingsResult<IReadOnlyList<ActivityRow>>.Success(Array.Empty<ActivityRow>()));
}
