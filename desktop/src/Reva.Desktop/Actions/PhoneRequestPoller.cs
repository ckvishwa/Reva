using Reva.Desktop.Services;

namespace Reva.Desktop.Actions;

/// <summary>Brings what paired phones asked this PC to do to the executor and the confirm card.
///
/// It long-polls the Core's inbox (<c>GET /v1/devices/requests</c>, loopback, Core token). The Core hands an
/// order out once, so a poll never runs the same order twice; a card is shown again on every poll until it is
/// decided, and removed when the Core stops listing it (expired, denied here, or the phone was revoked).
/// It decides nothing and verifies nothing itself: the Core already authorized the request, a click on this
/// PC approves anything sensitive, and the executor checks the signed grant before it touches anything.</summary>
public sealed class PhoneRequestPoller
{
    public static readonly TimeSpan DefaultWait = TimeSpan.FromSeconds(20);
    private static readonly TimeSpan MinPause = TimeSpan.FromMilliseconds(250);
    private static readonly TimeSpan MaxBackoff = TimeSpan.FromSeconds(30);

    private readonly IActionsApi _api;
    private readonly ActionCoordinator _coordinator;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly TimeSpan _wait;
    private readonly HashSet<string> _cards = new(StringComparer.Ordinal);

    public PhoneRequestPoller(
        IActionsApi api,
        ActionCoordinator coordinator,
        TimeSpan? wait = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _api = api;
        _coordinator = coordinator;
        _wait = wait ?? DefaultWait;
        _delay = delay ?? Task.Delay;
    }

    /// <summary>One round: ask the Core, handle what came back. Returns the sequence to ask after next,
    /// or null when the Core could not be reached.</summary>
    public async Task<long?> PollOnceAsync(long after, CancellationToken ct = default)
    {
        var result = await _api.GetPhoneRequestsAsync(after, _wait, ct).ConfigureAwait(false);
        if (!result.IsSuccess || result.Value is null)
        {
            return null;
        }

        var waiting = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in result.Value.Items)
        {
            if (item.Order is null && item.Status == "awaiting_approval")
            {
                waiting.Add(item.ActionId);
                _cards.Add(item.ActionId);
            }

            await HandleAsync(item, ct).ConfigureAwait(false);
        }

        foreach (var gone in _cards.Where(id => !waiting.Contains(id)).ToList())
        {
            _cards.Remove(gone);
            _coordinator.CloseCard(gone);
        }

        return result.Value.Seq;
    }

    public async Task RunAsync(CancellationToken ct)
    {
        long seq = 0;
        var backoff = TimeSpan.FromSeconds(1);
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var next = await PollOnceAsync(seq, ct).ConfigureAwait(false);
                if (next is null)
                {
                    await _delay(backoff, ct).ConfigureAwait(false);
                    backoff = TimeSpan.FromSeconds(Math.Min(backoff.TotalSeconds * 2, MaxBackoff.TotalSeconds));
                    continue;
                }

                backoff = TimeSpan.FromSeconds(1);
                seq = next.Value;
                await _delay(MinPause, ct).ConfigureAwait(false); // never a hot loop if the Core answers at once
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return;
            }
        }
    }

    private async Task HandleAsync(PhoneRequest item, CancellationToken ct)
    {
        try
        {
            await _coordinator.OnPhoneRequestAsync(item, ct).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // One bad item must not stop the next: the Core still holds its state, and an order that
            // could not be run ends "unknown" when its grant expires.
            DesktopLogger.Info($"phone_request.handle_failed type={ex.GetType().Name}");
        }
    }
}
