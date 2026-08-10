using Microsoft.UI.Xaml;

namespace Reva.Desktop;

/// <summary>Composition root. Grows in later slices to wire the service
/// layer (Core configuration, token provider, Core client) into the
/// window — see desktop/README.md for the slice plan.</summary>
public partial class App : Application
{
    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _window = new MainWindow();
        _window.Activate();
    }
}
