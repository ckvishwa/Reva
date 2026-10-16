using System.Collections.ObjectModel;
using Reva.Desktop.Actions;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>The confirm card: what REVA wants to do and two buttons. A click here is the only
/// approval for a sensitive action; saying "yes" out loud never reaches this.</summary>
public sealed class ApprovalCardViewModel : ObservableObject
{
    private readonly ActionCoordinator _coordinator;
    private readonly Action<Action> _post;
    private readonly List<ApprovalCard> _cards = new();
    private bool _busy;

    public ApprovalCardViewModel(ActionCoordinator coordinator, Action<Action> post)
    {
        _coordinator = coordinator;
        _post = post;
        coordinator.CardRequested += card => _post(() => Add(card));
        coordinator.CardClosed += id => _post(() => Remove(id));
    }

    public bool IsVisible => _cards.Count > 0;

    public string Prompt => _cards.Count > 0
        ? (_cards[0].From is { Length: > 0 } from ? $"{from} asks: {_cards[0].Prompt}" : _cards[0].Prompt)
        : string.Empty;

    public string? ActionId => _cards.Count > 0 ? _cards[0].ActionId : null;

    public bool Busy
    {
        get => _busy;
        private set
        {
            if (SetProperty(ref _busy, value))
            {
                RaisePropertyChanged(nameof(CanDecide));
            }
        }
    }

    public bool CanDecide => IsVisible && !_busy;

    public string Waiting => _cards.Count > 1 ? $"{_cards.Count - 1} more waiting" : string.Empty;

    public Task ConfirmAsync() => DecideAsync(true);

    public Task DenyAsync() => DecideAsync(false);

    public void Add(ApprovalCard card)
    {
        _cards.RemoveAll(c => c.ActionId == card.ActionId);
        _cards.Add(card);
        Changed();
    }

    public void Remove(string actionId)
    {
        if (_cards.RemoveAll(c => c.ActionId == actionId) > 0)
        {
            Changed();
        }
    }

    private async Task DecideAsync(bool approve)
    {
        if (ActionId is not { } id || _busy)
        {
            return;
        }

        Busy = true;
        try
        {
            await _coordinator.DecideAsync(id, approve).ConfigureAwait(false);
        }
        finally
        {
            _post(() => Busy = false);
        }
    }

    private void Changed()
    {
        RaisePropertyChanged(nameof(IsVisible));
        RaisePropertyChanged(nameof(Prompt));
        RaisePropertyChanged(nameof(ActionId));
        RaisePropertyChanged(nameof(Waiting));
        RaisePropertyChanged(nameof(CanDecide));
    }
}

public sealed class AllowedAppRow
{
    public AllowedAppRow(AppRow row)
    {
        Key = row.Key;
        DisplayName = row.DisplayName;
        Aliases = string.Join(", ", row.Aliases.Where(a => a != row.Key));
        CanRemove = !row.Builtin;
        Kind = row.Builtin ? "Built in" : "Approved by you";
    }

    public string Key { get; }

    public string DisplayName { get; }

    public string Aliases { get; }

    public bool CanRemove { get; }

    public string Kind { get; }
}

public sealed class WaitingAppRow : ObservableObject
{
    private string _aliases;

    public WaitingAppRow(WaitingApp app)
    {
        Key = app.Key;
        DisplayName = app.DisplayName;
        _aliases = string.Empty;
    }

    public string Key { get; }

    public string DisplayName { get; }

    /// <summary>What the owner will say, separated by commas. Optional: the app's own name always works.</summary>
    public string Aliases
    {
        get => _aliases;
        set => SetProperty(ref _aliases, value);
    }
}

/// <summary>Apps &amp; Actions: the apps REVA may open or close. Apps found in the Start Menu wait here
/// until the owner approves them and picks the names to say.</summary>
public sealed class AppsViewModel : ObservableObject
{
    private readonly IActionsApi _api;
    private readonly AppTargetStore _targets;
    private readonly Func<IReadOnlyList<DiscoveredApp>> _scan;
    private bool _busy;
    private string? _message;
    private string? _error;

    public AppsViewModel(IActionsApi api, AppTargetStore targets, Func<IReadOnlyList<DiscoveredApp>>? scan = null)
    {
        _api = api;
        _targets = targets;
        _scan = scan ?? (() => StartMenuScanner.Scan(StartMenuScanner.DefaultRoots()));
    }

    public ObservableCollection<AllowedAppRow> Allowed { get; } = new();

    public ObservableCollection<WaitingAppRow> Waiting { get; } = new();

    public bool Busy
    {
        get => _busy;
        private set => SetProperty(ref _busy, value);
    }

    public string? Message
    {
        get => _message;
        private set => SetProperty(ref _message, value);
    }

    public string? Error
    {
        get => _error;
        private set => SetProperty(ref _error, value);
    }

    public bool HasWaiting => Waiting.Count > 0;

    public async Task LoadAsync(CancellationToken ct = default)
    {
        Busy = true;
        Error = null;
        try
        {
            var found = await Task.Run(_scan, ct).ConfigureAwait(true);
            foreach (var app in found)
            {
                _targets.Remember(app.Key, app.DisplayName, app.Shortcut);
            }

            var result = found.Count > 0
                ? await _api.ReportDiscoveredAsync(found.Select(a => (a.Key, a.DisplayName)).ToList(), ct).ConfigureAwait(true)
                : await _api.GetAppsAsync(ct).ConfigureAwait(true);
            Apply(result);
        }
        finally
        {
            Busy = false;
        }
    }

    public async Task ApproveAsync(WaitingAppRow row, CancellationToken ct = default)
    {
        Busy = true;
        Error = null;
        try
        {
            var aliases = row.Aliases
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .ToList();
            var result = await _api.ApproveAppAsync(row.Key, row.DisplayName, aliases, ct).ConfigureAwait(true);
            Apply(result);
            if (result.IsSuccess)
            {
                Message = $"{row.DisplayName} is allowed. Say \"open {row.DisplayName.ToLowerInvariant()}\".";
            }
        }
        finally
        {
            Busy = false;
        }
    }

    public async Task RemoveAsync(AllowedAppRow row, CancellationToken ct = default)
    {
        Busy = true;
        Error = null;
        try
        {
            var result = await _api.RemoveAppAsync(row.Key, ct).ConfigureAwait(true);
            Apply(result);
            if (result.IsSuccess)
            {
                _targets.Forget(row.Key);
                Message = $"{row.DisplayName} is no longer allowed.";
            }
        }
        finally
        {
            Busy = false;
        }
    }

    private void Apply(Settings.SettingsResult<AppsSnapshot> result)
    {
        if (!result.IsSuccess || result.Value is null)
        {
            Error = result.Error?.SafeMessage ?? "REVA could not load the apps.";
            return;
        }

        Message = null;
        Allowed.Clear();
        foreach (var row in result.Value.Apps)
        {
            Allowed.Add(new AllowedAppRow(row));
        }

        Waiting.Clear();
        foreach (var app in result.Value.Waiting)
        {
            Waiting.Add(new WaitingAppRow(app));
        }

        RaisePropertyChanged(nameof(HasWaiting));
    }
}

public sealed class ActivityEntry
{
    public ActivityEntry(ActivityRow row)
    {
        Time = DateTimeOffset.TryParse(row.Time, out var parsed) ? parsed.ToLocalTime().ToString("MMM d, HH:mm:ss") : row.Time;
        Request = row.Request;
        From = row.From;
        Result = row.Result;
        Evidence = row.Evidence ?? "-";
    }

    public string Time { get; }

    public string Request { get; }

    public string From { get; }

    public string Result { get; }

    public string Evidence { get; }
}

/// <summary>Activity: everything REVA was asked to do, what happened and what proves it.</summary>
public sealed class ActivityViewModel : ObservableObject
{
    private readonly IActionsApi _api;
    private string? _error;

    public ActivityViewModel(IActionsApi api) => _api = api;

    public ObservableCollection<ActivityEntry> Items { get; } = new();

    public string? Error
    {
        get => _error;
        private set => SetProperty(ref _error, value);
    }

    public bool IsEmpty => Items.Count == 0;

    public async Task LoadAsync(CancellationToken ct = default)
    {
        var result = await _api.GetActivityAsync(50, ct).ConfigureAwait(true);
        if (!result.IsSuccess || result.Value is null)
        {
            Error = result.Error?.SafeMessage ?? "REVA could not load the activity.";
            return;
        }

        Error = null;
        Items.Clear();
        foreach (var row in result.Value)
        {
            Items.Add(new ActivityEntry(row));
        }

        RaisePropertyChanged(nameof(IsEmpty));
    }
}
