using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;
using Windows.System;

namespace Reva.Desktop;

public sealed partial class MainWindow : Window
{
    public ShellViewModel Shell { get; }

    public AssistantViewModel Assistant { get; }

    public MemoryViewModel Memory { get; }

    public WakeWordCoordinator? WakeWord { get; }

    public NavigationViewModel Navigation { get; }

    public FinanceViewModel Finance { get; }

    public TodayViewModel Today { get; }

    public DevicesViewModel Devices { get; }

    public MainWindow(
        ShellViewModel shell,
        AssistantViewModel assistant,
        MemoryViewModel memory,
        NavigationViewModel navigation,
        FinanceViewModel finance,
        TodayViewModel today,
        DevicesViewModel devices,
        WakeWordCoordinator? wakeWord = null)
    {
        // Set before InitializeComponent: x:Bind reads these while the tree is built.
        Shell = shell;
        Assistant = assistant;
        Memory = memory;
        Navigation = navigation;
        Finance = finance;
        Today = today;
        Devices = devices;
        WakeWord = wakeWord;
        InitializeComponent();
        Title = "REVA";
        ApplyDarkTitleBar();
        Nav.Attach(Navigation);
        FinancePanel.WindowHandle = () => WinRT.Interop.WindowNative.GetWindowHandle(this);
        Navigation.PropertyChanged += OnNavigationPropertyChanged;
        ComingSoonPanel.Show(Navigation.ComingSoonTitle, Navigation.ComingSoonText);
        Shell.PropertyChanged += OnShellPropertyChanged;
        ApplyStatusDotColor();
        RegisterVoicePointerHandlers();
        Closed += MainWindow_Closed;
    }

    private void ApplyDarkTitleBar()
    {
        var bar = AppWindow.TitleBar;
        var ground = Windows.UI.Color.FromArgb(255, 0x0E, 0x10, 0x13);
        var text = Windows.UI.Color.FromArgb(255, 0xEC, 0xEE, 0xF1);
        var muted = Windows.UI.Color.FromArgb(255, 0x9A, 0xA3, 0xAE);
        var hover = Windows.UI.Color.FromArgb(255, 0x23, 0x28, 0x2F);
        bar.BackgroundColor = ground;
        bar.ForegroundColor = text;
        bar.InactiveBackgroundColor = ground;
        bar.InactiveForegroundColor = muted;
        bar.ButtonBackgroundColor = ground;
        bar.ButtonForegroundColor = text;
        bar.ButtonInactiveBackgroundColor = ground;
        bar.ButtonInactiveForegroundColor = muted;
        bar.ButtonHoverBackgroundColor = hover;
        bar.ButtonHoverForegroundColor = text;
        bar.ButtonPressedBackgroundColor = hover;
        bar.ButtonPressedForegroundColor = text;
    }

    // Opening a page always reloads it from Core, so it never shows stale numbers. Both calls are
    // awaited inside the view models; nothing here blocks the UI thread.
    private async void OnNavigationPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName != nameof(NavigationViewModel.Selected))
        {
            return;
        }

        ComingSoonPanel.Show(Navigation.ComingSoonTitle, Navigation.ComingSoonText);
        // Pages poll Core only while they are the open section.
        FinancePanel.SetActive(Navigation.ShowsFinance);
        await DevicesPanel.SetActiveAsync(Navigation.ShowsDevices);
        if (Navigation.ShowsFinance)
        {
            await FinancePanel.RefreshAsync();
        }
        else if (Navigation.ShowsTalk)
        {
            await Today.RefreshAsync();
        }
    }

    private bool _shutdownComplete;

    private async void MainWindow_Closed(object sender, WindowEventArgs args)
    {
        // Slice 8A, Task 6 root cause: for an unpackaged WinUI app, the
        // process's message loop exits as soon as this handler returns —
        // and `async void` returns at its first `await`, long before the
        // awaited cleanup (wake-word disposal, Core shutdown) actually
        // finishes. Every previous version of this handler was fire-and-
        // forget in practice: the process was gone before ShutdownAsync's
        // Stop() call ever ran, confirmed by a real launch/close/tasklist
        // repro that still showed the orphan even after ShutdownAsync
        // itself was correct in isolation. `Handled = true` cancels this
        // close so the async work can run to completion; the explicit
        // Close() below re-fires this handler once, past the `if`, to let
        // the window actually go away.
        if (_shutdownComplete)
        {
            return;
        }

        args.Handled = true;

        Assistant.DetachLifecycle();
        await RunShutdownSequenceAsync(
            () => Shell.ShutdownAsync(),
            () => WakeWord is not null ? WakeWord.DisposeAsync().AsTask() : Task.CompletedTask);

        _shutdownComplete = true;
        Close();
    }

    /// <summary>Core stop before wake-word disposal, not after — Core stop
    /// runs in ~tens of milliseconds; wake-word disposal's latency (mic
    /// lease release, native detector teardown) is unbounded by anything
    /// this class controls. Ordering it first means anyone who kills REVA
    /// from Task Manager during that window still finds the owned Core
    /// process already stopped, rather than exposed for however long
    /// wake-word teardown takes. Extracted as a static, WinUI-free method
    /// so the ordering itself is unit-testable without a live Window.</summary>
    internal static async Task RunShutdownSequenceAsync(Func<Task> stopCoreAsync, Func<Task> disposeWakeWordAsync)
    {
        await stopCoreAsync().ConfigureAwait(true);
        await disposeWakeWordAsync().ConfigureAwait(true);
    }

    private void OnShellPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ShellViewModel.LifecycleState))
        {
            ApplyStatusDotColor();
        }
    }

    private void ApplyStatusDotColor()
    {
        var color = Shell.LifecycleState switch
        {
            CoreLifecycleState.Connected => Colors.LimeGreen,
            CoreLifecycleState.Starting => Colors.Gold,
            CoreLifecycleState.AuthorizationUnavailable => Colors.OrangeRed,
            _ => Colors.Gray,
        };
        StatusDot.Fill = new SolidColorBrush(color);
    }

    private async void SendButton_Click(object sender, RoutedEventArgs e)
    {
        SyncComposerTextFromTextBox();
        await Assistant.SendMessageAsync();
    }

    private async void ComposerBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter)
        {
            e.Handled = true;
            SyncComposerTextFromTextBox();
            await Assistant.SendMessageAsync();
        }
    }

    /// <summary>
    /// x:Bind's TwoWay binding for TextBox.Text only commits to the
    /// ViewModel on LostFocus, not on every keystroke. Neither send path
    /// reliably causes that: pressing Enter never blurs the box at all,
    /// and a real click's focus shift happens on a timeline that isn't
    /// guaranteed to land before this handler runs. Reading ComposerBox.Text
    /// directly here (code-behind is allowed to touch WinUI types;
    /// ViewModels are not) guarantees Assistant.ComposerText reflects
    /// exactly what's on screen before Send acts on it — confirmed via
    /// manual UI-Automation reproduction that omitting this silently
    /// drops the last-typed content often enough to matter.
    /// </summary>
    private void SyncComposerTextFromTextBox()
    {
        Assistant.ComposerText = ComposerBox.Text;
    }

    private void RegisterVoicePointerHandlers()
    {
        VoiceButton.AddHandler(
            UIElement.PointerPressedEvent,
            new PointerEventHandler(VoiceButton_PointerPressed),
            handledEventsToo: true);
        VoiceButton.AddHandler(
            UIElement.PointerReleasedEvent,
            new PointerEventHandler(VoiceButton_PointerReleased),
            handledEventsToo: true);
        VoiceButton.AddHandler(
            UIElement.PointerCanceledEvent,
            new PointerEventHandler(VoiceButton_PointerCanceled),
            handledEventsToo: true);
        VoiceButton.AddHandler(
            UIElement.PointerCaptureLostEvent,
            new PointerEventHandler(VoiceButton_PointerCaptureLost),
            handledEventsToo: true);
    }

    private async void Root_Loaded(object sender, RoutedEventArgs e)
    {
        await Assistant.RefreshVoiceAvailabilityAsync();
    }

    private async void VoiceButton_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer pressed handler reached");
        e.Handled = true;
        VoiceButton.CapturePointer(e.Pointer);
        if (WakeWord is not null)
        {
            await WakeWord.SuspendForHoldToTalkAsync();
        }

        await Assistant.StartVoiceInputAsync();
    }

    private async void VoiceButton_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer released handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await FinishVoiceInputAndResumeWakeAsync();
    }

    private async void VoiceButton_PointerCanceled(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer canceled handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await FinishVoiceInputAndResumeWakeAsync();
    }

    private async void VoiceButton_PointerCaptureLost(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer capture lost handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await FinishVoiceInputAndResumeWakeAsync();
    }

    private async Task FinishVoiceInputAndResumeWakeAsync()
    {
        try
        {
            await Assistant.FinishVoiceInputAsync();
        }
        finally
        {
            if (WakeWord is not null)
            {
                await WakeWord.ResumeAfterHoldToTalkAsync();
            }
        }
    }

    private void StopSpeakingButton_Click(object sender, RoutedEventArgs e)
    {
        Assistant.StopSpeaking();
    }

    private async void MicrophoneSettingsButton_Click(object sender, RoutedEventArgs e)
    {
        await Launcher.LaunchUriAsync(new Uri("ms-settings:privacy-microphone"));

        // There's no reliable "user came back from Settings" event for this
        // simple deep-link, so re-probe immediately: it clears a stale
        // PermissionDenied/NoMicrophone status right away if the OS already
        // reflects the grant, and otherwise gives the user an obvious,
        // discoverable retry (click the button again after fixing the
        // setting) instead of a permanently dead Hold-to-Talk button.
        await Assistant.RefreshVoiceAvailabilityAsync();
    }

    private async void RememberButton_Click(object sender, RoutedEventArgs e)
    {
        // Same LostFocus-commit gap as ComposerBox — read the live control
        // value directly rather than trusting the TwoWay-bound property.
        Memory.MemoryText = MemoryBox.Text;
        await Memory.RememberAsync();
    }

    private async void SearchButton_Click(object sender, RoutedEventArgs e)
    {
        await Memory.SearchAsync(MemoryBox.Text);
    }
}
