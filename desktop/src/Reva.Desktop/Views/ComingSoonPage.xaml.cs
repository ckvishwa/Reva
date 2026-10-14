using Microsoft.UI.Xaml.Controls;

namespace Reva.Desktop.Views;

/// <summary>Shown for every section that is listed in the nav but not built yet. It never fakes content.</summary>
public sealed partial class ComingSoonPage : UserControl
{
    public ComingSoonPage()
    {
        InitializeComponent();
    }

    public void Show(string title, string text)
    {
        TitleText.Text = title;
        BodyText.Text = text;
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(Card, "Coming soon. " + text);
    }
}
