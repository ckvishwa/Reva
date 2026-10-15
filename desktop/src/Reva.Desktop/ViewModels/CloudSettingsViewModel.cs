using System.Collections.ObjectModel;
using Reva.Desktop.Settings;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public sealed class CloudDomainRow : ObservableObject
{
    private bool _isOn;

    public CloudDomainRow(string id, string label, bool isOn, bool startsOff)
    {
        Id = id;
        Label = label;
        _isOn = isOn;
        StartsOff = startsOff;
    }

    public string Id { get; }

    public string Label { get; }

    /// <summary>The sensitive four, which start off by design.</summary>
    public bool StartsOff { get; }

    public string Hint => StartsOff ? "Sensitive: off unless you switch it on." : "Off unless you switch it on.";

    public bool IsOn
    {
        get => _isOn;
        set => SetProperty(ref _isOn, value);
    }
}

/// <summary>
/// Settings > Cloud model. Shows exactly what is sent, lets the owner store a key, switch cloud on and
/// choose domain by domain. The key goes straight from the password box to Core and is never kept here.
/// </summary>
public sealed class CloudSettingsViewModel : ObservableObject
{
    private static readonly string[] Sensitive = { "memory", "finance", "health", "personal" };
    private static readonly string[] Order = { "memory", "finance", "health", "personal", "coach", "career", "learn", "cyber" };

    private readonly ICloudSettingsApi _api;
    private bool _enabled;
    private bool _keyConfigured;
    private bool _busy;
    private string? _message;
    private string? _error;
    private string _provider = string.Empty;
    private string _fallback = string.Empty;
    private string _model = string.Empty;

    public CloudSettingsViewModel(ICloudSettingsApi api) => _api = api;

    public ObservableCollection<CloudDomainRow> Domains { get; } = new();

    public ObservableCollection<string> SentWhenOn { get; } = new();

    public ObservableCollection<string> NeverSent { get; } = new();

    public bool Enabled
    {
        get => _enabled;
        private set => SetProperty(ref _enabled, value);
    }

    public bool KeyConfigured
    {
        get => _keyConfigured;
        private set
        {
            if (SetProperty(ref _keyConfigured, value))
            {
                RaisePropertyChanged(nameof(KeyStatus));
                RaisePropertyChanged(nameof(CanSwitchOn));
            }
        }
    }

    public string KeyStatus => KeyConfigured ? "A key is stored in Windows Credential Manager." : "No key stored.";

    /// <summary>Cloud can only be switched on while a key is stored.</summary>
    public bool CanSwitchOn => KeyConfigured && !Busy;

    public bool Busy
    {
        get => _busy;
        private set
        {
            if (SetProperty(ref _busy, value))
            {
                RaisePropertyChanged(nameof(CanSwitchOn));
            }
        }
    }

    public string Provider
    {
        get => _provider;
        private set => SetProperty(ref _provider, value);
    }

    public string Fallback
    {
        get => _fallback;
        private set => SetProperty(ref _fallback, value);
    }

    public string Model
    {
        get => _model;
        private set => SetProperty(ref _model, value);
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

    public Task LoadAsync() => RunAsync(() => _api.GetAsync(), null);

    public Task SetEnabledAsync(bool enabled) =>
        RunAsync(() => _api.SetEnabledAsync(enabled), enabled ? "Cloud model is on." : "Cloud model is off.");

    public Task SetDomainAsync(string domain, bool allowed) =>
        RunAsync(() => _api.SetDomainAsync(domain, allowed), null);

    public async Task StoreKeyAsync(string apiKey)
    {
        var trimmed = apiKey.Trim();
        if (trimmed.Length == 0)
        {
            Error = "Paste your Anthropic API key first.";
            return;
        }

        await RunAsync(() => _api.StoreKeyAsync(trimmed), "Key stored. Cloud is still off until you switch it on.");
    }

    public Task RemoveKeyAsync() =>
        RunAsync(() => _api.RemoveKeyAsync(), "Key removed. Cloud is off.");

    private async Task RunAsync(Func<Task<SettingsResult<CloudSettingsSnapshot>>> call, string? success)
    {
        Busy = true;
        Error = null;
        try
        {
            var result = await call();
            if (!result.IsSuccess)
            {
                Error = result.Error!.SafeMessage;
                await ResyncAsync();
                return;
            }

            Apply(result.Value!);
            Message = success;
        }
        finally
        {
            Busy = false;
        }
    }

    // After a refused change the switches must show what Core really holds, not what was clicked.
    private async Task ResyncAsync()
    {
        var fresh = await _api.GetAsync();
        if (fresh.IsSuccess)
        {
            Apply(fresh.Value!);
        }
    }

    private void Apply(CloudSettingsSnapshot snapshot)
    {
        Enabled = snapshot.Enabled;
        KeyConfigured = snapshot.KeyConfigured;
        Provider = snapshot.Disclosure.Provider;
        Fallback = snapshot.Disclosure.Fallback;
        Model = snapshot.Model;
        Replace(SentWhenOn, snapshot.Disclosure.SentWhenOn);
        Replace(NeverSent, snapshot.Disclosure.NeverSent);

        var byId = Domains.ToDictionary(d => d.Id);
        foreach (var id in Order.Concat(snapshot.Domains.Keys.Except(Order)))
        {
            if (!snapshot.Domains.TryGetValue(id, out var on))
            {
                continue;
            }

            if (byId.TryGetValue(id, out var row))
            {
                row.IsOn = on;
            }
            else
            {
                Domains.Add(new CloudDomainRow(id, char.ToUpperInvariant(id[0]) + id[1..], on, Sensitive.Contains(id)));
            }
        }
    }

    private static void Replace(ObservableCollection<string> target, IReadOnlyList<string> items)
    {
        if (target.SequenceEqual(items))
        {
            return;
        }

        target.Clear();
        foreach (var item in items)
        {
            target.Add(item);
        }
    }
}
