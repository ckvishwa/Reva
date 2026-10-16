using System.Collections.ObjectModel;
using Reva.Desktop.Devices;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>Where the pairing gateway is, as far as the user can tell.</summary>
public enum GatewayPhase
{
    /// <summary>Nothing has been loaded from Core yet.</summary>
    Unknown,
    Off,
    Listening,
    /// <summary>It is switched on but not listening (no network address, port busy...).</summary>
    Failed,
}

/// <summary>Where the pairing in progress is. Terminal phases stay on screen until the user acts.</summary>
public enum PairingPhase
{
    None,
    /// <summary>A QR code is on screen, waiting for a phone to scan it.</summary>
    QrOpen,
    /// <summary>A phone scanned it; its six digits are on screen for the user to compare and approve.</summary>
    Pending,
    Approved,
    Denied,
    Expired,
    Locked,
}

/// <summary>
/// Backs the Devices page. Everything goes through <see cref="IDevicesApi"/> (REVA Core); no WinUI types, no
/// database. Core is the authority: after every action the state is re-read, and a newer refresh supersedes an
/// older one. The QR code (a one-time secret) lives only as image bytes while it is valid and is dropped the
/// moment pairing ends, expires or is cancelled.
/// </summary>
public sealed class DevicesViewModel : ObservableObject
{
    public const string RevokeExplanation = "A revoked phone can no longer sync. Its data already on this PC stays.";
    public const string ScopeNote = "A paired phone can sync Finance only, over your local network.";

    private readonly IDevicesApi _api;
    private readonly IQrEncoder _qr;
    private readonly Func<DateTimeOffset> _now;
    private int _refreshGeneration;

    private GatewayPhase _gateway = GatewayPhase.Unknown;
    private bool _enabled;
    private string _statusText = "Checking the pairing gateway…";
    private string? _keyText;
    private string? _errorMessage;
    private bool _isBusy;
    private PairingPhase _pairing = PairingPhase.None;
    private byte[]? _qrPng;
    private DateTimeOffset _deadline;
    private string _countdownText = string.Empty;
    private string? _pendingDigits;
    private string? _pendingName;
    private string? _pairingMessage;

    public DevicesViewModel(IDevicesApi api, IQrEncoder qr, Func<DateTimeOffset>? now = null)
    {
        _api = api;
        _qr = qr;
        _now = now ?? (() => DateTimeOffset.UtcNow);
    }

    public ObservableCollection<DeviceRowViewModel> Devices { get; } = new();

    public GatewayPhase Gateway
    {
        get => _gateway;
        private set
        {
            if (SetProperty(ref _gateway, value))
            {
                RaisePropertyChanged(nameof(IsListening));
                RaisePropertyChanged(nameof(CanPair));
                RaisePropertyChanged(nameof(PollDelay));
            }
        }
    }

    /// <summary>The state of the on/off switch: what Core says is enabled, not what was clicked.</summary>
    public bool GatewayEnabled
    {
        get => _enabled;
        private set => SetProperty(ref _enabled, value);
    }

    public bool IsListening => Gateway == GatewayPhase.Listening;

    public string StatusText
    {
        get => _statusText;
        private set => SetProperty(ref _statusText, value);
    }

    /// <summary>The gateway TLS key hash in short form, the value a phone pins. Null until the gateway has run.</summary>
    public string? KeyText
    {
        get => _keyText;
        private set
        {
            if (SetProperty(ref _keyText, value))
            {
                RaisePropertyChanged(nameof(HasKey));
            }
        }
    }

    public bool HasKey => KeyText is not null;

    public string? ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (SetProperty(ref _errorMessage, value))
            {
                RaisePropertyChanged(nameof(HasError));
            }
        }
    }

    public bool HasError => ErrorMessage is not null;

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanPair));
            }
        }
    }

    public PairingPhase Pairing
    {
        get => _pairing;
        private set
        {
            if (SetProperty(ref _pairing, value))
            {
                RaisePropertyChanged(nameof(ShowsQr));
                RaisePropertyChanged(nameof(ShowsPending));
                RaisePropertyChanged(nameof(IsPairingActive));
                RaisePropertyChanged(nameof(CanPair));
                RaisePropertyChanged(nameof(PollDelay));
            }
        }
    }

    public bool ShowsQr => Pairing == PairingPhase.QrOpen && QrPng is not null;

    public bool ShowsPending => Pairing == PairingPhase.Pending;

    public bool IsPairingActive => Pairing is PairingPhase.QrOpen or PairingPhase.Pending;

    public bool CanPair => IsListening && !IsBusy && !IsPairingActive;

    /// <summary>PNG bytes of the QR code while one is valid; null otherwise.</summary>
    public byte[]? QrPng
    {
        get => _qrPng;
        private set
        {
            if (!ReferenceEquals(_qrPng, value))
            {
                _qrPng = value;
                RaisePropertyChanged(nameof(QrPng));
                RaisePropertyChanged(nameof(ShowsQr));
            }
        }
    }

    public string CountdownText
    {
        get => _countdownText;
        private set => SetProperty(ref _countdownText, value);
    }

    /// <summary>The six digits to compare with the phone, spaced for reading: "123 456".</summary>
    public string? PendingFingerprintText => _pendingDigits is { Length: 6 } d ? $"{d[..3]} {d[3..]}" : _pendingDigits;

    public string? PendingDeviceName
    {
        get => _pendingName;
        private set => SetProperty(ref _pendingName, value);
    }

    public string? PairingMessage
    {
        get => _pairingMessage;
        private set
        {
            if (SetProperty(ref _pairingMessage, value))
            {
                RaisePropertyChanged(nameof(HasPairingMessage));
            }
        }
    }

    public bool HasPairingMessage => PairingMessage is not null;

    /// <summary>How long the page should wait before asking Core again: quickly while pairing, slowly otherwise.</summary>
    public TimeSpan PollDelay => IsPairingActive ? TimeSpan.FromSeconds(1) : TimeSpan.FromSeconds(5);

    // ------------------------------------------------------------------------------------ loading

    /// <summary>Re-reads the gateway, the pairing and the device list from Core. The newest call wins.</summary>
    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        var generation = Interlocked.Increment(ref _refreshGeneration);
        var result = await _api.GetAsync(cancellationToken).ConfigureAwait(true);
        if (generation != Volatile.Read(ref _refreshGeneration))
        {
            return;
        }

        if (!result.IsSuccess)
        {
            ErrorMessage = result.Error!.SafeMessage;
            return;
        }

        ErrorMessage = null;
        Apply(result.Value!);
    }

    private void Apply(DevicesSnapshot snapshot)
    {
        var status = snapshot.Gateway;
        GatewayEnabled = status.Enabled;
        KeyText = status.TlsSha256 is null ? null : "Gateway key " + DeviceRowViewModel.ShortFingerprint(status.TlsSha256);
        if (status.Listening)
        {
            Gateway = GatewayPhase.Listening;
            StatusText = $"Listening on {status.Host}:{status.Port}. Phones on your network can reach this PC to pair.";
        }
        else if (status.Enabled)
        {
            Gateway = GatewayPhase.Failed;
            StatusText = status.Error is null
                ? "Switched on, but not listening."
                : $"Switched on, but not listening: {status.Error}";
        }
        else
        {
            Gateway = GatewayPhase.Off;
            StatusText = status.Error is null
                ? "Off. No phone can reach this PC."
                : $"Off. The last attempt to start failed: {status.Error}";
        }

        var now = _now();
        Replace(Devices, snapshot.Devices.Select(d => new DeviceRowViewModel(d, now)));
        ApplyPairing(status.Pairing);
        Tick();
    }

    private void ApplyPairing(PairingView? view)
    {
        if (!IsListening || view is null)
        {
            // Core has no session (gateway off or restarted): a live QR or a waiting phone is gone.
            if (Pairing is PairingPhase.QrOpen or PairingPhase.Pending)
            {
                EndPairing(PairingPhase.None, "Pairing ended.");
            }

            return;
        }

        _deadline = _now().AddSeconds(view.ExpiresIn);
        switch (view.State)
        {
            case "open":
                if (Pairing != PairingPhase.QrOpen || QrPng is null)
                {
                    // Core has an open pairing whose QR this page never drew (the page was reopened).
                    // The code is only ever shown once, so it cannot be recovered: ask to start again.
                    EndPairing(PairingPhase.None, "A pairing was already open. Start a new one to see its QR code.");
                    _ = CancelStaleAsync();
                }

                break;
            case "pending":
                _pendingDigits = view.Fingerprint;
                PendingDeviceName = view.DeviceName;
                RaisePropertyChanged(nameof(PendingFingerprintText));
                if (Pairing != PairingPhase.Pending)
                {
                    QrPng = null;
                    PairingMessage = null;
                    Pairing = PairingPhase.Pending;
                }

                break;
            case "approved":
                if (Pairing is PairingPhase.Pending or PairingPhase.QrOpen)
                {
                    EndPairing(PairingPhase.Approved, ApprovedText(PendingDeviceName));
                }

                break;
            case "denied":
                if (Pairing is PairingPhase.Pending or PairingPhase.QrOpen)
                {
                    EndPairing(PairingPhase.Denied, "Pairing was denied. Nothing was shared.");
                }

                break;
            case "expired":
                if (Pairing is PairingPhase.Pending or PairingPhase.QrOpen)
                {
                    EndPairing(PairingPhase.Expired, "The pairing code expired. Start again for a new one.");
                }

                break;
            case "locked":
                if (Pairing is PairingPhase.Pending or PairingPhase.QrOpen)
                {
                    EndPairing(PairingPhase.Locked, "Too many wrong codes were tried, so this pairing was closed. Start again.");
                }

                break;
            default: // cancelled
                if (Pairing is PairingPhase.Pending or PairingPhase.QrOpen)
                {
                    EndPairing(PairingPhase.None, "Pairing was cancelled.");
                }

                break;
        }

    }

    private async Task CancelStaleAsync()
    {
        // Close the session whose QR we cannot show, so its code is not left valid for no reason.
        await _api.DenyPairingAsync().ConfigureAwait(true);
    }

    private static string ApprovedText(string? name) =>
        $"{(string.IsNullOrWhiteSpace(name) ? "The phone" : name)} is paired. It can sync Finance with this PC.";

    private void EndPairing(PairingPhase phase, string? message)
    {
        QrPng = null;
        _pendingDigits = null;
        RaisePropertyChanged(nameof(PendingFingerprintText));
        CountdownText = string.Empty;
        PairingMessage = message;
        Pairing = phase;
    }

    /// <summary>Updates the countdown. Call about once a second while pairing is active. A QR code that has
    /// run out is removed at once, without waiting for Core to say so.</summary>
    public void Tick()
    {
        if (!IsPairingActive)
        {
            return;
        }

        var remaining = _deadline - _now();
        if (remaining <= TimeSpan.Zero)
        {
            EndPairing(PairingPhase.Expired, "The pairing code expired. Start again for a new one.");
            return;
        }

        var seconds = (int)Math.Ceiling(remaining.TotalSeconds);
        CountdownText = Pairing == PairingPhase.QrOpen
            ? $"Code expires in {seconds / 60}:{seconds % 60:00}"
            : $"Approve within {seconds / 60}:{seconds % 60:00}";
    }

    // ------------------------------------------------------------------------------------ actions

    /// <summary>The switch was flipped. Core decides; the switch follows what Core reports.</summary>
    public async Task SetGatewayEnabledAsync(bool enabled, CancellationToken cancellationToken = default)
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _api.SetGatewayEnabledAsync(enabled, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                // Re-read so the switch shows the truth (a failed start leaves it off).
                await RefreshAsync(cancellationToken).ConfigureAwait(true);
                ErrorMessage = result.Error.SafeMessage;
                return;
            }

            ErrorMessage = null;
            if (!enabled)
            {
                EndPairing(PairingPhase.None, null);
            }

            await RefreshAsync(cancellationToken).ConfigureAwait(true);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task StartPairingAsync(CancellationToken cancellationToken = default)
    {
        if (!CanPair)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _api.OpenPairingAsync(cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                return;
            }

            byte[] png;
            try
            {
                png = _qr.EncodePng(result.Value!.QrText);
            }
            catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or NotSupportedException)
            {
                ErrorMessage = "REVA could not draw the pairing code.";
                await _api.DenyPairingAsync(cancellationToken).ConfigureAwait(true);
                return;
            }

            ErrorMessage = null;
            PairingMessage = null;
            _pendingDigits = null;
            PendingDeviceName = null;
            _deadline = DateTimeOffset.FromUnixTimeSeconds(result.Value.ExpiresAt);
            QrPng = png;
            Pairing = PairingPhase.QrOpen;
            Tick();
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Approve the phone whose six digits are on screen. The digits go back to Core, which refuses
    /// the approval unless they match the pairing it is holding.</summary>
    public async Task ApproveAsync(CancellationToken cancellationToken = default)
    {
        if (Pairing != PairingPhase.Pending || _pendingDigits is null || IsBusy)
        {
            return;
        }

        IsBusy = true;
        var name = PendingDeviceName;
        try
        {
            var result = await _api.ApprovePairingAsync(_pendingDigits, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                await RefreshAsync(cancellationToken).ConfigureAwait(true);
                ErrorMessage = result.Error.SafeMessage;
                return;
            }

            ErrorMessage = null;
            EndPairing(PairingPhase.Approved, ApprovedText(name));
            await RefreshAsync(cancellationToken).ConfigureAwait(true);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Deny the waiting phone, or cancel while the QR code is still on screen.</summary>
    public async Task DenyAsync(CancellationToken cancellationToken = default)
    {
        if (!IsPairingActive || IsBusy)
        {
            return;
        }

        IsBusy = true;
        var wasWaiting = Pairing == PairingPhase.Pending;
        try
        {
            var result = await _api.DenyPairingAsync(cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                return;
            }

            ErrorMessage = null;
            EndPairing(
                wasWaiting ? PairingPhase.Denied : PairingPhase.None,
                wasWaiting ? "Pairing was denied. Nothing was shared." : "Pairing cancelled.");
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Revoke a phone. The page asks the user to confirm first; this does not.</summary>
    public async Task RevokeAsync(DeviceRowViewModel device, CancellationToken cancellationToken = default)
    {
        if (!device.IsActive || IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _api.RevokeAsync(device.DeviceId, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                return;
            }

            ErrorMessage = null;
            PairingMessage = $"{device.Name} was revoked. It can no longer sync.";
            await RefreshAsync(cancellationToken).ConfigureAwait(true);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Let a paired phone ask this PC to open or close apps, or take that back. The choice is
    /// made here, on this PC, and nowhere else.</summary>
    public async Task SetPhoneAccessAsync(
        DeviceRowViewModel device, bool openApps, bool closeApps, CancellationToken cancellationToken = default)
    {
        if (!device.IsActive || IsBusy)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var result = await _api.SetPhoneAccessAsync(device.DeviceId, openApps, closeApps, cancellationToken).ConfigureAwait(true);
            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                return;
            }

            ErrorMessage = null;
            await RefreshAsync(cancellationToken).ConfigureAwait(true);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>Hides a finished pairing's message.</summary>
    public void DismissMessage()
    {
        if (!IsPairingActive)
        {
            PairingMessage = null;
            Pairing = PairingPhase.None;
        }
    }

    private static void Replace<T>(ObservableCollection<T> target, IEnumerable<T> items)
    {
        target.Clear();
        foreach (var item in items)
        {
            target.Add(item);
        }
    }
}
