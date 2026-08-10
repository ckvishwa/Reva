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
        await Assistant.SendMessageAsync();
    }

    private async void ComposerBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter)
        {
            e.Handled = true;
            await Assistant.SendMessageAsync();
        }
    }
}
