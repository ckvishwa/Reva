using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Reva.Desktop.Services;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop;

public sealed partial class MainWindow : Window
{
    public ShellViewModel ViewModel { get; }

    public MainWindow(IRevaCoreClient coreClient)
    {
        InitializeComponent();
        ViewModel = new ShellViewModel(coreClient);
        ViewModel.PropertyChanged += OnViewModelPropertyChanged;
        Activated += OnActivatedAsync;
    }

    private async void OnActivatedAsync(object sender, WindowActivatedEventArgs args)
    {
        Activated -= OnActivatedAsync;
        await ViewModel.RefreshCoreStatusAsync();
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ShellViewModel.IsCoreConnected))
        {
            StatusDot.Fill = new SolidColorBrush(ViewModel.IsCoreConnected ? Colors.LimeGreen : Colors.Gray);
        }
    }
}
