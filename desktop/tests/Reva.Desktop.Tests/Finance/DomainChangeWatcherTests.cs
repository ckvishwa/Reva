using System.Diagnostics;
using System.Net;
using Reva.Desktop.Finance;

namespace Reva.Desktop.Tests.Finance;

/// <summary>SYNC-1e: the PC screens reload when Core says Finance changed, without a tab switch,
/// and never on (or blocking) the UI thread.</summary>
public class DomainChangeWatcherTests
{
    /// <summary>A Core whose change counter the test moves by hand.</summary>
    private sealed class FakeChangesApi : IDomainChangesApi
    {
        private readonly object _gate = new();
        private long _counter;
        private TaskCompletionSource _moved = NewSignal();
        public List<long?> Asked { get; } = new();
        public Queue<FinanceError> Failures { get; } = new();

        public void Commit()
        {
            lock (_gate)
            {
                _counter++;
                _moved.TrySetResult();
            }
        }

        public async Task<FinanceResult<DomainChange>> WaitForChangeAsync(
            string domain, long? since, TimeSpan wait, CancellationToken ct = default)
        {
            TaskCompletionSource signal;
            lock (_gate)
            {
                Asked.Add(since);
                if (Failures.Count > 0)
                {
                    return FinanceResult<DomainChange>.Failure(Failures.Dequeue());
                }

                if (since is null || since != _counter)
                {
                    return FinanceResult<DomainChange>.Success(new DomainChange(domain, _counter, true));
                }

                _moved = NewSignal();
                signal = _moved;
            }

            await signal.Task.WaitAsync(ct).ConfigureAwait(false);
            lock (_gate)
            {
                return FinanceResult<DomainChange>.Success(new DomainChange(domain, _counter, true));
            }
        }

        private static TaskCompletionSource NewSignal() =>
            new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    /// <summary>Runs queued actions only when the test pumps them, like a UI thread would.</summary>
    private sealed class FakeUi : IUiDispatcher
    {
        private readonly Queue<Action> _queue = new();

        public bool TryEnqueue(Action action)
        {
            lock (_queue)
            {
                _queue.Enqueue(action);
            }

            return true;
        }

        public int Pump()
        {
            var ran = 0;
            while (true)
            {
                Action? next;
                lock (_queue)
                {
                    next = _queue.Count > 0 ? _queue.Dequeue() : null;
                }

                if (next is null)
                {
                    return ran;
                }

                next();
                ran++;
            }
        }
    }

    /// <summary>A delay the test releases by hand, so debounce and back-off take no real time.</summary>
    private sealed class ManualDelay
    {
        private readonly object _gate = new();
        public List<(TimeSpan Span, TaskCompletionSource Done)> Pending { get; } = new();
        public List<TimeSpan> Requested { get; } = new();

        public Task Delay(TimeSpan span, CancellationToken ct)
        {
            var done = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (_gate)
            {
                Requested.Add(span);
                Pending.Add((span, done));
            }

            ct.Register(() => done.TrySetCanceled(ct));
            return done.Task;
        }

        public void ReleaseAll()
        {
            List<(TimeSpan, TaskCompletionSource)> all;
            lock (_gate)
            {
                all = Pending.ToList();
                Pending.Clear();
            }

            foreach (var (_, done) in all)
            {
                done.TrySetResult();
            }
        }
    }

    private static async Task Until(Func<bool> condition, int milliseconds = 3000)
    {
        var timer = Stopwatch.StartNew();
        while (!condition())
        {
            if (timer.ElapsedMilliseconds > milliseconds)
            {
                throw new TimeoutException("condition not reached");
            }

            await Task.Delay(5);
        }
    }

    private static (DomainChangeWatcher Watcher, FakeChangesApi Api, FakeUi Ui, ManualDelay Delay, List<string> Seen)
        Create()
    {
        var api = new FakeChangesApi();
        var ui = new FakeUi();
        var delay = new ManualDelay();
        var seen = new List<string>();
        var watcher = new DomainChangeWatcher(
            api, ui, domain =>
            {
                seen.Add(domain);
                return Task.CompletedTask;
            }, delay.Delay);
        return (watcher, api, ui, delay, seen);
    }

    [Fact]
    public async Task The_first_answer_is_only_a_baseline_and_triggers_no_reload()
    {
        var (watcher, api, ui, delay, seen) = Create();
        using (watcher)
        {
            watcher.Start();
            await Until(() => api.Asked.Count >= 2); // baseline, then waiting on it

            delay.ReleaseAll();
            Assert.Equal(0, ui.Pump());
            Assert.Empty(seen);
            Assert.Null(api.Asked[0]);
            Assert.Equal(0, api.Asked[1]);
        }
    }

    [Fact]
    public async Task A_commit_reloads_the_open_screen_once_on_the_ui_thread()
    {
        var (watcher, api, ui, delay, seen) = Create();
        using (watcher)
        {
            watcher.Start();
            await Until(() => api.Asked.Count >= 2);

            api.Commit();
            await Until(() => delay.Pending.Count == 1); // the debounce window is open
            delay.ReleaseAll();
            await Until(() => ui.Pump() > 0 || seen.Count > 0);

            Assert.Equal(new[] { "finance" }, seen);
        }
    }

    [Fact]
    public async Task A_burst_of_commits_inside_the_debounce_window_reloads_once()
    {
        var (watcher, api, ui, delay, seen) = Create();
        using (watcher)
        {
            watcher.Start();
            await Until(() => api.Asked.Count >= 2);

            for (var i = 0; i < 5; i++)
            {
                api.Commit();
                await Until(() => api.Asked.Count >= 3 + i); // the watcher asked again after each
            }

            delay.ReleaseAll();
            await Task.Delay(50);
            ui.Pump();
            ui.Pump();

            Assert.Single(seen);
        }
    }

    [Fact]
    public async Task Start_returns_at_once_even_while_core_is_still_waiting()
    {
        var (watcher, api, _, _, _) = Create();
        using (watcher)
        {
            var timer = Stopwatch.StartNew();
            watcher.Start();
            timer.Stop();

            Assert.True(timer.ElapsedMilliseconds < 200, $"Start blocked for {timer.ElapsedMilliseconds} ms");
            await Until(() => api.Asked.Count >= 2);
        }
    }

    [Fact]
    public async Task The_network_wait_never_runs_on_the_ui_thread()
    {
        var uiThread = Environment.CurrentManagedThreadId;
        var observed = new List<int>();
        var api = new FakeChangesApi();
        var watcher = new DomainChangeWatcher(
            new ThreadRecordingApi(api, observed), new FakeUi(), _ => Task.CompletedTask, new ManualDelay().Delay);
        using (watcher)
        {
            watcher.Start();
            await Until(() => observed.Count >= 2);

            Assert.DoesNotContain(uiThread, observed);
        }
    }

    private sealed class ThreadRecordingApi(IDomainChangesApi inner, List<int> threads) : IDomainChangesApi
    {
        public Task<FinanceResult<DomainChange>> WaitForChangeAsync(
            string domain, long? since, TimeSpan wait, CancellationToken ct = default)
        {
            lock (threads)
            {
                threads.Add(Environment.CurrentManagedThreadId);
            }

            return inner.WaitForChangeAsync(domain, since, wait, ct);
        }
    }

    [Fact]
    public async Task Failures_back_off_instead_of_hammering_core_and_recovery_resumes()
    {
        var (watcher, api, _, delay, _) = Create();
        for (var i = 0; i < 3; i++)
        {
            api.Failures.Enqueue(new FinanceError(FinanceErrorKind.Unavailable, "REVA Core is not reachable."));
        }

        using (watcher)
        {
            watcher.Start();
            for (var i = 0; i < 3; i++)
            {
                var expected = i + 1;
                await Until(() => delay.Requested.Count >= expected && delay.Pending.Count > 0);
                delay.ReleaseAll();
            }

            await Until(() => api.Asked.Count >= 5); // 3 failures, then a baseline, then a wait
            Assert.True(delay.Requested[0] < delay.Requested[1] && delay.Requested[1] < delay.Requested[2]);
            Assert.All(delay.Requested, d => Assert.True(d <= TimeSpan.FromSeconds(30)));
        }
    }

    [Fact]
    public async Task A_restarted_core_with_a_lower_counter_still_reloads()
    {
        var api = new RestartingApi();
        var ui = new FakeUi();
        var delay = new ManualDelay();
        var seen = new List<string>();
        using var watcher = new DomainChangeWatcher(api, ui, d =>
        {
            seen.Add(d);
            return Task.CompletedTask;
        }, delay.Delay);

        watcher.Start();
        await Until(() => api.Calls >= 2);
        await Until(() => delay.Pending.Count == 1);
        delay.ReleaseAll();
        await Until(() => ui.Pump() > 0 || seen.Count > 0);

        Assert.Single(seen);
    }

    private sealed class RestartingApi : IDomainChangesApi
    {
        public int Calls;

        public Task<FinanceResult<DomainChange>> WaitForChangeAsync(
            string domain, long? since, TimeSpan wait, CancellationToken ct = default)
        {
            var call = Interlocked.Increment(ref Calls);
            // 1: baseline at 57. 2: Core restarted, counter is 0, which differs from 57.
            return Task.FromResult(call switch
            {
                1 => FinanceResult<DomainChange>.Success(new DomainChange(domain, 57, true)),
                2 => FinanceResult<DomainChange>.Success(new DomainChange(domain, 0, true)),
                _ => FinanceResult<DomainChange>.Success(new DomainChange(domain, 0, false)),
            });
        }
    }

    [Fact]
    public async Task Disposing_stops_the_loop()
    {
        var (watcher, api, _, _, _) = Create();
        watcher.Start();
        await Until(() => api.Asked.Count >= 2);

        watcher.Dispose();
        var asked = api.Asked.Count;
        api.Commit();
        await Task.Delay(100);

        Assert.Equal(asked, api.Asked.Count);
    }
}

public class DomainChangesApiClientTests
{
    private static (FinanceApiClient Client, StubHandler Handler) Create()
    {
        var handler = new StubHandler();
        var http = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") };
        return (new FinanceApiClient(http, new StubTokens(), TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(5)), handler);
    }

    [Fact]
    public async Task The_wait_uses_the_changes_route_with_the_token_baseline_and_timeout()
    {
        var (client, handler) = Create();
        handler.Responder = (_, _) =>
            Task.FromResult(StubHandler.Json(HttpStatusCode.OK, """{"domain":"finance","counter":7,"changed":true}"""));

        var result = await client.WaitForChangeAsync("finance", 6, TimeSpan.FromSeconds(25));

        Assert.True(result.IsSuccess);
        Assert.Equal(new DomainChange("finance", 7, true), result.Value);
        var request = Assert.Single(handler.Requests);
        Assert.Equal("/v1/domains/changes?domain=finance&timeout=25&since=6", request.PathAndQuery);
        Assert.Equal("Bearer secret-token", request.Authorization);
    }

    [Fact]
    public async Task Without_a_baseline_no_since_is_sent()
    {
        var (client, handler) = Create();
        handler.Responder = (_, _) =>
            Task.FromResult(StubHandler.Json(HttpStatusCode.OK, """{"domain":"finance","counter":0,"changed":true}"""));

        await client.WaitForChangeAsync("finance", null, TimeSpan.FromSeconds(25));

        Assert.DoesNotContain("since=", handler.Requests[0].PathAndQuery);
    }

    [Fact]
    public async Task The_wait_is_never_longer_than_core_allows()
    {
        var (client, handler) = Create();
        handler.Responder = (_, _) =>
            Task.FromResult(StubHandler.Json(HttpStatusCode.OK, """{"domain":"finance","counter":0,"changed":false}"""));

        await client.WaitForChangeAsync("finance", 0, TimeSpan.FromMinutes(5));

        Assert.Contains("timeout=30", handler.Requests[0].PathAndQuery);
    }

    [Fact]
    public async Task A_refusal_is_a_safe_failure_not_an_exception()
    {
        var (client, handler) = Create();
        handler.Responder = (_, _) => Task.FromResult(StubHandler.Json(
            (HttpStatusCode)429, """{"error":"too_many_watchers"}"""));

        var result = await client.WaitForChangeAsync("finance", 0, TimeSpan.FromSeconds(25));

        Assert.False(result.IsSuccess);
        Assert.DoesNotContain("secret-token", result.Error!.SafeMessage);
    }

    [Fact]
    public async Task Without_a_token_nothing_is_sent()
    {
        var handler = new StubHandler();
        var tokens = new StubTokens { Available = false };
        var client = new FinanceApiClient(
            new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8756/") }, tokens);

        var result = await client.WaitForChangeAsync("finance", null, TimeSpan.FromSeconds(25));

        Assert.Equal(FinanceErrorKind.Unauthorized, result.Error!.Kind);
        Assert.Empty(handler.Requests);
    }
}
