using System.Text.Json;
using Reva.Desktop.Actions;

namespace Reva.Desktop.Tests.Actions;

public sealed class AppActionExecutorTests : IDisposable
{
    private static readonly DateTimeOffset VectorNow = DateTimeOffset.Parse("2026-10-15T12:00:00+00:00");

    private readonly JsonDocument _vectors = JsonDocument.Parse(File.ReadAllText(VectorPath()));
    private readonly FakeLauncher _launcher = new();
    private readonly FakeWindows _windows = new();
    private readonly FakeTargets _targets = new();
    private readonly TickingTime _time = new(VectorNow);
    private readonly GrantVerifier _verifier;

    public AppActionExecutorTests()
    {
        _verifier = new GrantVerifier(_vectors.RootElement.GetProperty("public_key_pem").GetString()!);
    }

    public void Dispose()
    {
        _verifier.Dispose();
        _vectors.Dispose();
    }

    private AppActionExecutor Executor() =>
        new(_verifier, _targets, _windows, _launcher, _time, windowTimeout: TimeSpan.FromSeconds(8),
            exitTimeout: TimeSpan.FromSeconds(5), poll: TimeSpan.Zero);

    // ----------------------------------------------------------------- open

    [Fact]
    public async Task A_valid_grant_and_a_new_window_is_verified_with_process_and_window_evidence()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x1A2B), 4242, "notepad"));

        var report = await Executor().ExecuteAsync(Order("valid"));

        Assert.Equal("verified", report.Status);
        Assert.Equal(new ActionEvidence("process_started", "pid:4242 window:0x1A2B"), report.Evidence);
        Assert.Equal(1, _launcher.Starts);
    }

    [Fact]
    public async Task A_process_that_never_shows_a_window_is_unknown_not_verified_and_not_failed()
    {
        _launcher.StartPid = 777;
        _launcher.Running = new[] { 777 };

        var report = await Executor().ExecuteAsync(Order("valid"));

        Assert.Equal("unknown", report.Status);
        Assert.Equal("pid:777 no_window", report.Evidence!.Reference);
    }

    [Fact]
    public async Task Nothing_running_and_no_window_means_the_launch_failed()
    {
        _launcher.StartPid = null;

        var report = await Executor().ExecuteAsync(Order("valid"));

        Assert.Equal("failed", report.Status);
        Assert.Null(report.Evidence);
    }

    [Fact]
    public async Task A_launch_that_throws_is_a_failure()
    {
        _launcher.OnStart = () => throw new System.ComponentModel.Win32Exception("no such file");

        Assert.Equal("failed", (await Executor().ExecuteAsync(Order("valid"))).Status);
    }

    [Fact]
    public async Task A_window_from_another_app_does_not_count()
    {
        _launcher.StartPid = 5;
        _launcher.Running = new[] { 5 };
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x99), 900, "chrome"));

        Assert.Equal("unknown", (await Executor().ExecuteAsync(Order("valid"))).Status);
    }

    [Fact]
    public async Task An_app_that_was_already_open_and_came_to_the_front_is_verified_by_its_foreground_window()
    {
        _windows.Add(new TopWindow(new IntPtr(0x77), 1234, "notepad"));
        _windows.ForegroundWindow = new IntPtr(0x77);

        var report = await Executor().ExecuteAsync(Order("valid"));

        Assert.Equal("verified", report.Status);
        Assert.Equal("pid:1234 window:0x77", report.Evidence!.Reference);
    }

    [Fact]
    public async Task An_already_open_app_that_did_not_come_forward_is_not_claimed_as_opened()
    {
        _windows.Add(new TopWindow(new IntPtr(0x77), 1234, "notepad"));
        _launcher.StartPid = 1234;
        _launcher.Running = new[] { 1234 };

        Assert.Equal("unknown", (await Executor().ExecuteAsync(Order("valid"))).Status);
    }

    [Fact]
    public async Task An_approved_app_with_no_known_process_needs_a_window_that_looks_like_it()
    {
        _targets.Add(new LaunchTarget("obsidian", "Obsidian", @"C:\Start\Obsidian.lnk", Array.Empty<string>()));
        _launcher.StartPid = 31;
        _launcher.Running = new[] { 31 };
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x56), 90, "SomethingElse", "Unrelated popup"));

        var report = await Executor().ExecuteAsync(Order("valid_obsidian"));

        Assert.Equal("unknown", report.Status);
        Assert.Empty(_targets.Learned);
    }

    [Fact]
    public async Task An_approved_app_with_no_known_process_learns_its_name_from_the_window()
    {
        _targets.Add(new LaunchTarget("obsidian", "Obsidian", @"C:\Start\Obsidian.lnk", Array.Empty<string>()));
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x55), 31, "Obsidian", "Vault - Obsidian v1.5"));

        var report = await Executor().ExecuteAsync(Order("valid_obsidian"));

        Assert.Equal("verified", report.Status);
        Assert.Equal(new[] { ("obsidian", "Obsidian") }, _targets.Learned.ToArray());
    }

    // -------------------------------------------- forged, replayed, expired, substituted

    [Theory]
    [InlineData("wrong_signer")]
    [InlineData("tampered_args_hash")]
    [InlineData("expired")]
    [InlineData("from_the_future")]
    [InlineData("substituted_args")]
    [InlineData("substituted_capability")]
    [InlineData("malformed_signature")]
    [InlineData("not_base64")]
    public async Task A_bad_grant_is_refused_and_nothing_is_launched(string name)
    {
        var order = Order(name);
        _time.Set(DateTimeOffset.Parse(Case(name).GetProperty("now").GetString()!));

        var report = await Executor().ExecuteAsync(order);

        Assert.Equal("failed", report.Status);
        Assert.StartsWith("grant refused", report.Note);
        Assert.Equal(0, _launcher.Starts);
    }

    [Fact]
    public async Task A_grant_for_another_device_or_another_owner_is_refused()
    {
        var elsewhere = new AppActionExecutor(_verifier, _targets, _windows, _launcher, _time,
            deviceId: "phone-0001", poll: TimeSpan.Zero);
        var someoneElse = new AppActionExecutor(_verifier, _targets, _windows, _launcher, _time,
            actor: "someone", poll: TimeSpan.Zero);

        var first = await elsewhere.ExecuteAsync(Order("valid"));
        var second = await someoneElse.ExecuteAsync(Order("valid"));

        Assert.Equal("grant refused: WRONG_TARGET", first.Note);
        Assert.Equal("grant refused: WRONG_ACTOR", second.Note);
        Assert.Equal(0, _launcher.Starts);
    }

    [Fact]
    public async Task A_replayed_grant_does_nothing_the_second_time()
    {
        _launcher.OnStart = () => _windows.Add(new TopWindow(new IntPtr(0x1), 10, "notepad"));
        var executor = Executor();

        var first = await executor.ExecuteAsync(Order("valid"));
        var second = await executor.ExecuteAsync(Order("valid"));

        Assert.Equal("verified", first.Status);
        Assert.Equal("failed", second.Status);
        Assert.Equal("grant refused: REPLAYED", second.Note);
        Assert.Equal(1, _launcher.Starts);
    }

    [Fact]
    public async Task A_valid_grant_for_an_unsupported_capability_does_nothing()
    {
        // Signed for windows.app.open but offered as another capability: the grant check refuses it
        // before any dispatch happens.
        var report = await Executor().ExecuteAsync(Order("substituted_capability"));

        Assert.Equal("failed", report.Status);
        Assert.Equal(0, _launcher.Starts);
    }

    // ---------------------------------------------------------------- false success

    [Fact]
    public async Task False_success_corpus_a_launch_with_no_new_window_is_never_verified_0_of_100()
    {
        var random = new Random(11);
        var verified = 0;
        for (var i = 0; i < 100; i++)
        {
            using var verifier = new GrantVerifier(_vectors.RootElement.GetProperty("public_key_pem").GetString()!);
            var launcher = new FakeLauncher();
            var windows = new FakeWindows();
            switch (random.Next(5))
            {
                case 0: // process exists, no window
                    launcher.StartPid = random.Next(1, 90000);
                    launcher.Running = new[] { launcher.StartPid.Value };
                    break;
                case 1: // a different app's window appears
                    launcher.OnStart = () => windows.Add(new TopWindow(new IntPtr(random.Next(1, 9999)), 5, "chrome"));
                    break;
                case 2: // the app's window was already there but is in the background
                    windows.Add(new TopWindow(new IntPtr(0x10), 3, "notepad"));
                    launcher.StartPid = 3;
                    break;
                case 3: // nothing at all
                    break;
                default: // a window exists but belongs to a process that has no name
                    launcher.OnStart = () => windows.Add(new TopWindow(new IntPtr(0x20), 8, string.Empty));
                    break;
            }

            var executor = new AppActionExecutor(verifier, _targets, windows, launcher, new TickingTime(VectorNow),
                windowTimeout: TimeSpan.FromSeconds(8), poll: TimeSpan.Zero);
            var report = await executor.ExecuteAsync(Order("valid"));
            if (report.Status == "verified")
            {
                verified++;
            }
        }

        Assert.Equal(0, verified);
    }

    // ----------------------------------------------------------------- close

    [Fact]
    public async Task Close_is_verified_only_when_the_process_is_gone()
    {
        _targets.Add(new LaunchTarget("notepad", "Notepad", "notepad.exe", new[] { "notepad" }));
        _launcher.RunningSequence = new Queue<int[]>(new[] { new[] { 77 }, new[] { 77 }, Array.Empty<int>() });

        var report = await Executor().ExecuteAsync(CloseOrder());

        Assert.Equal("verified", report.Status);
        Assert.Equal(new ActionEvidence("process_exited", "pid:77 exited"), report.Evidence);
        Assert.Equal(1, _launcher.CloseRequests);
    }

    [Fact]
    public async Task Close_lists_every_process_that_went_away()
    {
        _launcher.RunningSequence = new Queue<int[]>(new[] { new[] { 77, 78 }, Array.Empty<int>() });

        var report = await Executor().ExecuteAsync(CloseOrder());

        Assert.Equal("pids:77,78 exited", report.Evidence!.Reference);
    }

    [Fact]
    public async Task A_window_that_stays_open_is_unknown_never_closed()
    {
        _launcher.Running = new[] { 77 };

        var report = await Executor().ExecuteAsync(CloseOrder());

        Assert.Equal("unknown", report.Status);
        Assert.Null(report.Evidence);
    }

    [Fact]
    public async Task Closing_an_app_that_is_not_running_is_a_failure_not_a_success()
    {
        _launcher.Running = Array.Empty<int>();

        var report = await Executor().ExecuteAsync(CloseOrder());

        Assert.Equal("failed", report.Status);
        Assert.Equal(0, _launcher.CloseRequests);
    }

    // ----------------------------------------------------------------- helpers

    private JsonElement Case(string name) =>
        _vectors.RootElement.GetProperty("cases").EnumerateArray().Single(c => c.GetProperty("name").GetString() == name);

    private ActionOrder Order(string name, string? argsOverride = null)
    {
        var item = Case(name);
        Assert.True(GrantVerifier.TryParseGrant(item.GetProperty("grant"), out var grant));
        var args = argsOverride is null
            ? item.GetProperty("args").Clone()
            : JsonDocument.Parse(argsOverride).RootElement.Clone();
        return new ActionOrder(
            grant,
            item.GetProperty("signature").GetString()!,
            item.GetProperty("capability").GetString()!,
            args,
            item.GetProperty("target_device").GetString()!);
    }

    private ActionOrder CloseOrder() => Order("valid_close");

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

internal sealed class TickingTime : TimeProvider
{
    private DateTimeOffset _now;

    public TickingTime(DateTimeOffset start) => _now = start;

    public void Set(DateTimeOffset value) => _now = value;

    public override DateTimeOffset GetUtcNow()
    {
        var current = _now;
        _now = _now.AddSeconds(1);
        return current;
    }
}

internal sealed class FakeLauncher : IAppLauncher
{
    public int Starts { get; private set; }

    public int CloseRequests { get; private set; }

    public int? StartPid { get; set; }

    public Action? OnStart { get; set; }

    public IReadOnlyList<int> Running { get; set; } = Array.Empty<int>();

    public Queue<int[]>? RunningSequence { get; set; }

    public int? Start(LaunchTarget target)
    {
        Starts++;
        OnStart?.Invoke();
        return StartPid;
    }

    public IReadOnlyList<int> RunningProcessIds(IReadOnlyList<string> processNames) =>
        RunningSequence is { Count: > 0 } sequence ? sequence.Dequeue() : Running;

    public bool RequestClose(IReadOnlyList<string> processNames)
    {
        CloseRequests++;
        return true;
    }
}

internal sealed class FakeWindows : IWindowProbe
{
    private readonly List<TopWindow> _windows = new();

    public IntPtr ForegroundWindow { get; set; }

    public void Add(TopWindow window) => _windows.Add(window);

    public IReadOnlyList<TopWindow> VisibleWindows() => _windows.ToList();

    public IntPtr Foreground() => ForegroundWindow;
}

internal sealed class FakeTargets : IAppTargets
{
    private readonly Dictionary<string, LaunchTarget> _targets = new()
    {
        ["notepad"] = new("notepad", "Notepad", "notepad.exe", new[] { "notepad" }),
    };

    public List<(string Key, string Process)> Learned { get; } = new();

    public void Add(LaunchTarget target) => _targets[target.Key] = target;

    public LaunchTarget? Find(string key) => _targets.GetValueOrDefault(key);

    public void Learn(string key, string processName) => Learned.Add((key, processName));
}
