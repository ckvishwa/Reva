using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;

namespace Reva.Desktop.Views;

/// <summary>
/// Static helpers for x:Bind function bindings. They exist because a Window root cannot use
/// IValueConverter in x:Bind (see MainWindow.xaml), and because the view models hold no WinUI types.
/// </summary>
public static class Vis
{
    public static Visibility Show(bool value) => value ? Visibility.Visible : Visibility.Collapsed;

    public static Visibility Hide(bool value) => value ? Visibility.Collapsed : Visibility.Visible;

    public static Visibility ShowWhenZero(int count) => count == 0 ? Visibility.Visible : Visibility.Collapsed;

    public static Visibility ShowText(string? value) =>
        string.IsNullOrEmpty(value) ? Visibility.Collapsed : Visibility.Visible;

    public static bool Not(bool value) => !value;

    public static Brush Brush(string key) => (Brush)Application.Current.Resources[key];

    public static Brush AmountBrush(bool isIncome) => Brush(isIncome ? "RevaSuccessBrush" : "RevaTextBrush");

    public static Brush SourceBrush(bool isVoice) => Brush(isVoice ? "RevaSuccessBrush" : "RevaMutedBrush");

    public static Brush DueBrush(bool isSoon) => Brush(isSoon ? "RevaAccentBrush" : "RevaMutedBrush");

    public static Brush StatusBrush(bool isActive) => Brush(isActive ? "RevaSuccessBrush" : "RevaMutedBrush");

    public static Brush BarBrush(bool nearLimit) => Brush(nearLimit ? "RevaAccentLightBrush" : "RevaAccentBrush");
}
