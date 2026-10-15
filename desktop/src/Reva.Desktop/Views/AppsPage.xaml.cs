using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class AppsPage : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(AppsViewModel), typeof(AppsPage),
        new PropertyMetadata(null, (d, _) => ((AppsPage)d).Bindings.Update()));

    public AppsPage()
    {
        InitializeComponent();
    }

    public AppsViewModel? ViewModel
    {
        get => (AppsViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public Task LoadAsync() => ViewModel?.LoadAsync() ?? Task.CompletedTask;

    private async void Allow_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null && ((FrameworkElement)sender).Tag is WaitingAppRow row)
        {
            await ViewModel.ApproveAsync(row);
        }
    }

    private async void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null && ((FrameworkElement)sender).Tag is AllowedAppRow row)
        {
            await ViewModel.RemoveAsync(row);
        }
    }
}
