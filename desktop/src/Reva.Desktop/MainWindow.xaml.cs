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

    public MainWindow(
        IRevaCoreClient coreClient,
        IRevaCoreLifecycle lifecycle,
        IVoiceDevice? voiceDevice = null,
        ICommandRouter? commandRouter = null)
    {
        InitializeComponent();
        Shell = new ShellViewModel(lifecycle);
        Assistant = new AssistantViewModel(coreClient, voiceDevice, lifecycle, commandRouter);
        Memory = new MemoryViewModel(coreClient);
        Shell.PropertyChanged += OnShellPropertyChanged;
        ApplyStatusDotColor();
        RegisterVoicePointerHandlers();
        Closed += MainWindow_Closed;
    }

    private void MainWindow_Closed(object sender, WindowEventArgs args)
    {
        Assistant.DetachLifecycle();
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
        await Assistant.StartVoiceInputAsync();
    }

    private async void VoiceButton_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer released handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await Assistant.FinishVoiceInputAsync();
    }

    private async void VoiceButton_PointerCanceled(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer canceled handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await Assistant.FinishVoiceInputAsync();
    }

    private async void VoiceButton_PointerCaptureLost(object sender, PointerRoutedEventArgs e)
    {
        DesktopLogger.Info("voice pointer capture lost handler reached");
        e.Handled = true;
        VoiceButton.ReleasePointerCaptures();
        await Assistant.FinishVoiceInputAsync();
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
