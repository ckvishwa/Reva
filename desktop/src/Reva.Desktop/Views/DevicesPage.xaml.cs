using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Reva.Desktop.ViewModels;
using Windows.Storage.Streams;

namespace Reva.Desktop.Views;

/// <summary>
/// The Devices page. All state comes from <see cref="DevicesViewModel"/> (which talks to Core's /v1/devices
/// API); this class draws the QR image, runs the poll timer, and opens the revoke confirmation. Core is only
/// asked while the page is the active section, and about once a second while a pairing is on screen.
/// </summary>
public sealed partial class DevicesPage : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(DevicesViewModel), typeof(DevicesPage),
        new PropertyMetadata(null, (d, e) => ((DevicesPage)d).OnViewModelChanged((DevicesViewModel?)e.OldValue)));

    private readonly DispatcherQueueTimer _timer;
    private bool _syncingToggle;
    private bool _active;
    private bool _refreshing;
    private double _sinceRefresh;
    private int _dialogOpen;

    public DevicesPage()
    {
        InitializeComponent();
        _timer = DispatcherQueue.GetForCurrentThread().CreateTimer();
        _timer.Interval = TimeSpan.FromSeconds(1);
        _timer.IsRepeating = true;
        _timer.Tick += async (_, _) => await OnTickAsync();
    }

    public static string ScopeNoteText => DevicesViewModel.ScopeNote;

    public static string RevokeNote => DevicesViewModel.RevokeExplanation;

    public DevicesViewModel? ViewModel
    {
        get => (DevicesViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public static string PendingTitle(string? name) =>
        string.IsNullOrWhiteSpace(name) ? "A phone wants to pair" : $"{name} wants to pair";

    /// <summary>Narrator reads the digits one by one.</summary>
    public static string DigitsName(string? digits) =>
        digits is null ? "Pairing digits" : "Pairing digits: " + string.Join(", ", digits.Where(char.IsDigit));

    /// <summary>Called by the window when this section is opened or left. Polling runs only while active.</summary>
    public async Task SetActiveAsync(bool active)
    {
        _active = active;
        if (!active)
        {
            _timer.Stop();
            return;
        }

        _sinceRefresh = 0;
        _timer.Start();
        await RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        if (ViewModel is not { } vm || _refreshing)
        {
            return;
        }

        _refreshing = true;
        try
        {
            await vm.RefreshAsync();
        }
        finally
        {
            _refreshing = false;
            _sinceRefresh = 0;
        }
    }

    private async Task OnTickAsync()
    {
        if (!_active || ViewModel is not { } vm)
        {
            return;
        }

        vm.Tick();
        _sinceRefresh += 1;
        if (_sinceRefresh >= vm.PollDelay.TotalSeconds)
        {
            await RefreshAsync();
        }
    }

    private void OnViewModelChanged(DevicesViewModel? old)
    {
        if (old is not null)
        {
            old.PropertyChanged -= OnViewModelPropertyChanged;
        }

        if (ViewModel is { } vm)
        {
            vm.PropertyChanged += OnViewModelPropertyChanged;
        }

        Bindings.Update();
        SyncToggle();
        _ = ShowQrAsync();
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        switch (e.PropertyName)
        {
            case nameof(DevicesViewModel.GatewayEnabled):
                SyncToggle();
                break;
            case nameof(DevicesViewModel.QrPng):
                _ = ShowQrAsync();
                break;
        }
    }

    private void SyncToggle()
    {
        if (ViewModel is not { } vm || GatewayToggle.IsOn == vm.GatewayEnabled)
        {
            return;
        }

        _syncingToggle = true;
        try
        {
            GatewayToggle.IsOn = vm.GatewayEnabled;
        }
        finally
        {
            _syncingToggle = false;
        }
    }

    // The QR is decoded from the in-memory PNG; it is never written to disk. When the view model drops it
    // (expired, cancelled, approved) the image is cleared too.
    private async Task ShowQrAsync()
    {
        var png = ViewModel?.QrPng;
        if (png is null)
        {
            QrImage.Source = null;
            return;
        }

        using var stream = new InMemoryRandomAccessStream();
        using (var writer = new DataWriter(stream.GetOutputStreamAt(0)))
        {
            writer.WriteBytes(png);
            await writer.StoreAsync();
            writer.DetachStream();
        }

        stream.Seek(0);
        var bitmap = new BitmapImage();
        await bitmap.SetSourceAsync(stream);
        if (ReferenceEquals(ViewModel?.QrPng, png))
        {
            QrImage.Source = bitmap;
        }
    }

    private async void GatewayToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (_syncingToggle || ViewModel is not { } vm || GatewayToggle.IsOn == vm.GatewayEnabled)
        {
            return;
        }

        await vm.SetGatewayEnabledAsync(GatewayToggle.IsOn);
        SyncToggle();
    }

    private async void Pair_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            await vm.StartPairingAsync();
        }
    }

    private async void Approve_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            await vm.ApproveAsync();
        }
    }

    private async void Deny_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            await vm.DenyAsync();
        }
    }

    private void Dismiss_Click(object sender, RoutedEventArgs e) => ViewModel?.DismissMessage();

    private async void PhoneOpenApps_Click(object sender, RoutedEventArgs e) => await ChangeAccessAsync(sender, open: true);

    private async void PhoneCloseApps_Click(object sender, RoutedEventArgs e) => await ChangeAccessAsync(sender, open: false);

    private async Task ChangeAccessAsync(object sender, bool open)
    {
        if (ViewModel is not { } vm
            || sender is not CheckBox box
            || box.DataContext is not DeviceRowViewModel device)
        {
            return;
        }

        var on = box.IsChecked == true;
        await vm.SetPhoneAccessAsync(
            device,
            open ? on : device.OpenAppsAllowed,
            open ? device.CloseAppsAllowed : on);
    }

    private async void Revoke_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm || (sender as FrameworkElement)?.DataContext is not DeviceRowViewModel device)
        {
            return;
        }

        var dialog = new ContentDialog
        {
            Title = $"Revoke {device.Name}?",
            Content = DevicesViewModel.RevokeExplanation + " To use it again you would pair it again.",
            PrimaryButtonText = "Revoke",
            CloseButtonText = "Keep",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await ShowDialogAsync(dialog) == ContentDialogResult.Primary)
        {
            await vm.RevokeAsync(device);
        }
    }

    private async Task<ContentDialogResult> ShowDialogAsync(ContentDialog dialog)
    {
        // WinUI allows one ContentDialog at a time; a second open throws.
        if (Interlocked.Exchange(ref _dialogOpen, 1) == 1)
        {
            return ContentDialogResult.None;
        }

        try
        {
            dialog.XamlRoot = XamlRoot;
            return await dialog.ShowAsync();
        }
        finally
        {
            _dialogOpen = 0;
        }
    }
}
