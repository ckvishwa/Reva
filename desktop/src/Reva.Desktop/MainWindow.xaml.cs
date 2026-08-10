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

    public MainWindow(IRevaCoreClient coreClient)
    {
        InitializeComponent();
        Shell = new ShellViewModel(coreClient);
        Assistant = new AssistantViewModel(coreClient);
        Shell.PropertyChanged += OnShellPropertyChanged;

        // Deliberately not gated on the Activated event: confirmed via
        // manual smoke test (real launch, real Core, real UI Automation
        // read-back) that Activated does not reliably fire for every
        // launch path, leaving the status stuck on "Checking REVA
        // Core..." even though Core was healthy and reachable the whole
        // time. The initial health check must run unconditionally.
        _ = Shell.RefreshCoreStatusAsync();
    }

    private void OnShellPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ShellViewModel.IsCoreConnected))
        {
            StatusDot.Fill = new SolidColorBrush(Shell.IsCoreConnected ? Colors.LimeGreen : Colors.Gray);
        }
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
}
