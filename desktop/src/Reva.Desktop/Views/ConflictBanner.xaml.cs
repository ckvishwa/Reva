using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

/// <summary>
/// Shows one unresolved sync conflict and lets the person pick a side. It performs no I/O itself:
/// the host handles <see cref="Resolved"/> (true = keep this PC's value).
/// </summary>
public sealed partial class ConflictBanner : UserControl
{
    public static readonly DependencyProperty ConflictProperty = DependencyProperty.Register(
        nameof(Conflict), typeof(ConflictBannerViewModel), typeof(ConflictBanner),
        new PropertyMetadata(null, (d, _) => ((ConflictBanner)d).Render()));

    public ConflictBanner()
    {
        InitializeComponent();
        Render();
    }

    public event EventHandler<bool>? Resolved;

    public ConflictBannerViewModel? Conflict
    {
        get => (ConflictBannerViewModel?)GetValue(ConflictProperty);
        set => SetValue(ConflictProperty, value);
    }

    private void Render()
    {
        var conflict = Conflict;
        Visibility = conflict is null ? Visibility.Collapsed : Visibility.Visible;
        MessageText.Text = conflict?.Message ?? string.Empty;
        AutomationProperties.SetName(Panel, conflict is null ? string.Empty : "Sync conflict. " + conflict.Message);
    }

    private void KeepPc_Click(object sender, RoutedEventArgs e) => Resolved?.Invoke(this, true);

    private void KeepPhone_Click(object sender, RoutedEventArgs e) => Resolved?.Invoke(this, false);
}
