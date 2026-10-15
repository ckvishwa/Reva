using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class ActivityPage : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(ActivityViewModel), typeof(ActivityPage),
        new PropertyMetadata(null, (d, _) => ((ActivityPage)d).Bindings.Update()));

    public ActivityPage()
    {
        InitializeComponent();
    }

    public ActivityViewModel? ViewModel
    {
        get => (ActivityViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public Task LoadAsync() => ViewModel?.LoadAsync() ?? Task.CompletedTask;

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await LoadAsync();
}
