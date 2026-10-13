using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class TodayCard : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(TodayViewModel), typeof(TodayCard),
        new PropertyMetadata(null, (d, _) => ((TodayCard)d).Bindings.Update()));

    public TodayCard()
    {
        InitializeComponent();
    }

    public TodayViewModel? ViewModel
    {
        get => (TodayViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }
}
