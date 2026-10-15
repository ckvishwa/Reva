using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class ApprovalCardView : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(ApprovalCardViewModel), typeof(ApprovalCardView),
        new PropertyMetadata(null, (d, _) => ((ApprovalCardView)d).Bindings.Update()));

    public ApprovalCardView()
    {
        InitializeComponent();
    }

    public ApprovalCardViewModel? ViewModel
    {
        get => (ApprovalCardViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    private async void Confirm_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.ConfirmAsync();
        }
    }

    private async void Deny_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.DenyAsync();
        }
    }
}
