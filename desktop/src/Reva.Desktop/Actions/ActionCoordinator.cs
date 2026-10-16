using Reva.Desktop.Services;
using Reva.Desktop.Voice;

namespace Reva.Desktop.Actions;

/// <summary>A confirm card waiting for a click. The sentence is the Core's, not ours.</summary>
public sealed record ApprovalCard(string ActionId, string Prompt, DateTimeOffset? Deadline, string? From = null);

/// <summary>Joins the live session to the executor. It never decides anything:
///
///  * <c>action.proposed</c> carries a signed order for something safe (an app to open): run it;
///  * <c>action.approval_required</c> carries a sentence for a card: show it;
///  * a click on the card goes to the Core as a click (the only approval that counts); if the Core
///    answers with a signed order (closing an app), run it;
///  * whatever the executor saw goes back to the Core as a report. The Core turns it into the
///    sentence REVA speaks and sends it back as <c>action.outcome</c>.</summary>
public sealed class ActionCoordinator
{
    private readonly IActionsApi _api;
    private readonly Func<AppActionExecutor?> _executorFactory;
    private AppActionExecutor? _executor;
    private readonly HashSet<string> _running = new(StringComparer.Ordinal);
    private readonly object _lock = new();

    /// <param name="executorFactory">Called until it returns an executor: the Core writes the public half
    /// of its grant key when it starts, which can be after this app did, so the executor is built the
    /// first time an order arrives and again on later orders until it works.</param>
    public ActionCoordinator(IActionsApi api, Func<AppActionExecutor?> executorFactory)
    {
        _api = api;
        _executorFactory = executorFactory;
    }

    public ActionCoordinator(IActionsApi api, AppActionExecutor? executor)
        : this(api, () => executor)
    {
    }

    /// <summary>A card to show (or replace). Raised on a background thread.</summary>
    public event Action<ApprovalCard>? CardRequested;

    /// <summary>The card for this action is finished (decided, expired, or answered by the Core).</summary>
    public event Action<string>? CardClosed;

    /// <summary>The sentence the Core said about an action, once it is final.</summary>
    public event Action<string, string>? Outcome;

    /// <summary>Hook this to <see cref="VoiceLoopController.CoreEvent"/>.</summary>
    public void OnCoreEvent(VoiceEvent e)
    {
        switch (e.Kind)
        {
            case "action.proposed":
                if (ActionsApi.ParseOrder(e.Payload) is { } order)
                {
                    _ = RunAsync(order);
                }

                break;
            case "action.approval_required":
                var state = ActionsApi.ParseAction(e.Payload);
                if (state?.Prompt is { Length: > 0 } prompt)
                {
                    CardRequested?.Invoke(new ApprovalCard(state.ActionId, prompt, state.Deadline));
                }

                break;
            case "action.outcome":
                var outcome = ActionsApi.ParseAction(e.Payload);
                if (outcome is not null)
                {
                    CardClosed?.Invoke(outcome.ActionId);
                    Outcome?.Invoke(outcome.ActionId, outcome.Speak ?? string.Empty);
                }

                break;
        }
    }

    /// <summary>Something a paired phone asked this PC to do, from the Core's inbox. A request that
    /// waits for approval becomes a card (the click happens here, on this PC); an order for something
    /// safe is run, once. Nothing here decides: the Core already did, and the executor still verifies
    /// the signed grant before it touches anything.</summary>
    public async Task OnPhoneRequestAsync(PhoneRequest request, CancellationToken ct = default)
    {
        if (request.Order is { } order)
        {
            await RunAsync(order, ct).ConfigureAwait(false);
        }
        else if (request.Status == "awaiting_approval" && request.Prompt is { Length: > 0 } prompt)
        {
            CardRequested?.Invoke(new ApprovalCard(request.ActionId, prompt, request.Deadline, request.From));
        }
    }

    /// <summary>The Core no longer lists this card (expired, denied, or the phone was revoked).</summary>
    public void CloseCard(string actionId) => CardClosed?.Invoke(actionId);

    /// <summary>The Confirm / Not now buttons.</summary>
    public async Task DecideAsync(string actionId, bool approve, CancellationToken ct = default)
    {
        var result = await _api.DecideAsync(actionId, approve, ct).ConfigureAwait(false);
        if (!result.IsSuccess || result.Value is null)
        {
            return; // the card stays; the owner can try again or let it time out
        }

        if (approve && result.Value.Status == "awaiting_approval")
        {
            return; // the Core did not accept it as an approval
        }

        CardClosed?.Invoke(actionId);
        if (result.Value.Order is { } order)
        {
            await RunAsync(order, ct).ConfigureAwait(false);
        }
    }

    private async Task RunAsync(ActionOrder order, CancellationToken ct = default)
    {
        lock (_lock)
        {
            if (!_running.Add(order.Grant.GrantId))
            {
                return; // the same order twice runs once
            }
        }

        var executor = _executor ??= _executorFactory();
        var report = executor is null
            ? new ActionReport(ActionReport.Failed, null, "no executor")
            : await SafeExecuteAsync(executor, order, ct).ConfigureAwait(false);
        var sent = await _api.ReportAsync(order.Grant.ActionId, order.Grant.GrantId, report, ct).ConfigureAwait(false);
        if (!sent.IsSuccess)
        {
            DesktopLogger.Info($"executor.report_failed action={order.Grant.ActionId}");
        }
    }

    private static async Task<ActionReport> SafeExecuteAsync(AppActionExecutor executor, ActionOrder order, CancellationToken ct)
    {
        try
        {
            return await executor.ExecuteAsync(order, ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return new ActionReport(ActionReport.Unknown, null, "cancelled");
        }
        catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception or IOException)
        {
            DesktopLogger.Info($"executor.crashed type={ex.GetType().Name}");
            return new ActionReport(ActionReport.Failed, null, "executor error");
        }
    }
}
