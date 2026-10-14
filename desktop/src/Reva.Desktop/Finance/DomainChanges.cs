namespace Reva.Desktop.Finance;

/// <summary>Core's answer to "has this domain changed since counter N": the counter and a flag. It
/// carries no data; the screen reloads through the normal routes.</summary>
public sealed record DomainChange(string Domain, long Counter, bool Changed);

/// <summary>Waits on REVA Core's <c>/v1/domains/changes</c> long-poll (SYNC-1e).</summary>
public interface IDomainChangesApi
{
    /// <summary>Returns once the domain's counter differs from <paramref name="since"/>, or after
    /// <paramref name="wait"/> unchanged. With no baseline it answers at once with the current counter.</summary>
    Task<FinanceResult<DomainChange>> WaitForChangeAsync(
        string domain, long? since, TimeSpan wait, CancellationToken cancellationToken = default);
}

/// <summary>Runs an action on the UI thread. WinUI wraps a <c>DispatcherQueue</c>; tests pump by hand.</summary>
public interface IUiDispatcher
{
    bool TryEnqueue(Action action);
}

/// <summary>
/// Tells the open screen to reload when a phone sync (or any other commit) changes Finance.
/// The long-poll runs on a pool thread, so the UI thread is never blocked. Bursts are debounced
/// into one reload, which is handed to the UI thread. A failing Core is retried with back-off.
/// </summary>
public sealed class DomainChangeWatcher : IDisposable
{
    public const string FinanceDomain = "finance";

    public static readonly TimeSpan Wait = TimeSpan.FromSeconds(25);
    public static readonly TimeSpan Debounce = TimeSpan.FromMilliseconds(300);
    private static readonly TimeSpan FirstBackoff = TimeSpan.FromSeconds(1);
    private static readonly TimeSpan MaxBackoff = TimeSpan.FromSeconds(30);

    private readonly IDomainChangesApi _api;
    private readonly IUiDispatcher _ui;
    private readonly Func<string, Task> _onChanged;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly object _gate = new();
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _debounce;

    public DomainChangeWatcher(
        IDomainChangesApi api, IUiDispatcher ui, Func<string, Task> onChanged,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _api = api;
        _ui = ui;
        _onChanged = onChanged;
        _delay = delay ?? Task.Delay;
    }

    /// <summary>Begins watching and returns at once.</summary>
    public void Start()
    {
        lock (_gate)
        {
            if (_cts is not null)
            {
                return;
            }

            _cts = new CancellationTokenSource();
            var token = _cts.Token;
            _ = Task.Run(() => RunAsync(token), CancellationToken.None);
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            _cts?.Cancel();
            _debounce?.Cancel();
        }
    }

    private async Task RunAsync(CancellationToken ct)
    {
        long? since = null;
        var failures = 0;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var result = await _api.WaitForChangeAsync(FinanceDomain, since, Wait, ct).ConfigureAwait(false);
                if (!result.IsSuccess)
                {
                    failures++;
                    await _delay(BackoffFor(failures), ct).ConfigureAwait(false);
                    continue;
                }

                failures = 0;
                var baseline = since is null; // the first answer only says where the counter is
                since = result.Value!.Counter;
                if (result.Value.Changed && !baseline)
                {
                    RequestReload(ct);
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    internal static TimeSpan BackoffFor(int failures)
    {
        var seconds = FirstBackoff.TotalSeconds * Math.Pow(2, Math.Min(failures - 1, 6));
        return TimeSpan.FromSeconds(Math.Min(seconds, MaxBackoff.TotalSeconds));
    }

    private void RequestReload(CancellationToken ct)
    {
        CancellationTokenSource window;
        lock (_gate)
        {
            _debounce?.Cancel(); // a newer change restarts the window
            window = _debounce = CancellationTokenSource.CreateLinkedTokenSource(ct);
        }

        _ = ReloadAfterAsync(window.Token);
    }

    private async Task ReloadAfterAsync(CancellationToken token)
    {
        try
        {
            await _delay(Debounce, token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return;
        }

        _ui.TryEnqueue(() => _ = RunHandlerAsync());
    }

    private async Task RunHandlerAsync()
    {
        try
        {
            await _onChanged(FinanceDomain).ConfigureAwait(true);
        }
        catch (Exception)
        {
            // A failed reload must never take the app down; the next change tries again.
        }
    }
}

/// <summary>The WinUI <see cref="IUiDispatcher"/>: queues work on a window's UI thread.</summary>
public sealed class DispatcherQueueDispatcher(Microsoft.UI.Dispatching.DispatcherQueue queue) : IUiDispatcher
{
    public bool TryEnqueue(Action action) => queue.TryEnqueue(() => action());
}
