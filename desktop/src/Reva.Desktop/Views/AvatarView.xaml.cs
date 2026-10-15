using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.Web.WebView2.Core;
using Reva.Desktop.Avatar;
using Reva.Desktop.Services;

namespace Reva.Desktop.Views;

/// <summary>
/// The avatar in a WebView2, locked down (AR-WIN-006): the page is served from one virtual host that
/// maps to the local <c>avatar</c> folder, every request to anywhere else is answered with 403,
/// navigation and new windows are refused, and the browser's own menus, dev tools, dialogs and
/// shortcuts are off. If the files are missing or WebView2 is not installed the rest of the app
/// carries on and this view says so.
/// </summary>
public sealed partial class AvatarView : UserControl, IAvatarSink
{
    private readonly DispatcherQueue _ui = DispatcherQueue.GetForCurrentThread();
    private DispatcherQueueTimer? _pump;
    private bool _loaded;
    private bool _started;

    public AvatarView()
    {
        InitializeComponent();
        Loaded += async (_, _) => await StartAsync();
    }

    public event Action<PageMessage>? PageMessageReceived;

    public AvatarDirector? Director { get; set; }

    public string Status => StatusText.Text;

    public static string AvatarFolder => Path.Combine(AppContext.BaseDirectory, "avatar");

    public async Task StartAsync()
    {
        if (_started)
        {
            return;
        }

        _started = true;
        if (string.Equals(Environment.GetEnvironmentVariable("REVA_DESKTOP_AVATAR"), "off", StringComparison.OrdinalIgnoreCase))
        {
            // UI-automation test runs switch the web view off: walking a browser's accessibility tree
            // makes every UI automation search crawl. The avatar is checked separately (docs/avatar).
            Fail("Avatar is off for this run.");
            return;
        }

        DesktopLogger.Info("avatar.webview.starting");
        if (!File.Exists(Path.Combine(AvatarFolder, "index.html")))
        {
            Fail("Avatar files are missing.");
            return;
        }

        try
        {
            var userData = Path.Combine(RuntimePaths.GetDefaultDataDirectory(), "webview2");
            Environment.SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", userData);
            // The page is one canvas with nothing to read out, so the browser's accessibility tree is switched off:
            // it would otherwise be walked by every UI automation client that searches this window.
            var options = new CoreWebView2EnvironmentOptions { AdditionalBrowserArguments = "--disable-renderer-accessibility" };
            var environment = await CoreWebView2Environment.CreateWithOptionsAsync(null, userData, options);
            await Web.EnsureCoreWebView2Async(environment);
            DesktopLogger.Info("avatar.webview.core_ready");
            Harden(Web.CoreWebView2);
            Web.CoreWebView2.SetVirtualHostNameToFolderMapping(
                AvatarNavigationPolicy.VirtualHost, AvatarFolder, CoreWebView2HostResourceAccessKind.Deny);
            Web.CoreWebView2.Navigate(AvatarNavigationPolicy.StartUrl);
        }
        catch (Exception ex) when (ex is System.Runtime.InteropServices.COMException or InvalidOperationException
            or ArgumentException)
        {
            DesktopLogger.Info($"avatar.webview.start_failed {ex.GetType().Name} 0x{ex.HResult:X8} {ex.StackTrace}");
            Fail($"The avatar can't start: Microsoft Edge WebView2 isn't available ({ex.GetType().Name} 0x{ex.HResult:X8}).");
            return;
        }

        _pump = _ui.CreateTimer();
        _pump.Interval = TimeSpan.FromMilliseconds(8);
        _pump.Tick += (_, _) => Director?.Pump();
        _pump.Start();
    }

    public void Post(string json)
    {
        _ui.TryEnqueue(() =>
        {
            if (Web.CoreWebView2 is { } core && _loaded)
            {
                core.PostWebMessageAsJson(json);
            }
        });
    }

    private void Harden(CoreWebView2 core)
    {
        var settings = core.Settings;
        settings.AreDevToolsEnabled = false;
        settings.AreDefaultContextMenusEnabled = false;
        settings.AreDefaultScriptDialogsEnabled = false;
        settings.AreBrowserAcceleratorKeysEnabled = false;
        settings.IsStatusBarEnabled = false;
        settings.IsZoomControlEnabled = false;
        settings.IsGeneralAutofillEnabled = false;
        settings.IsPasswordAutosaveEnabled = false;
        settings.IsPinchZoomEnabled = false;
        settings.IsSwipeNavigationEnabled = false;

        core.NavigationStarting += (_, args) =>
        {
            if (!AvatarNavigationPolicy.IsAllowedNavigation(args.Uri, _loaded))
            {
                args.Cancel = true;
            }
        };
        core.NewWindowRequested += (_, args) => args.Handled = true;
        core.PermissionRequested += (_, args) => args.State = CoreWebView2PermissionState.Deny;
        core.DownloadStarting += (_, args) => args.Cancel = true;

        // Network blocked: only the avatar's own virtual host may be requested.
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, args) =>
        {
            if (!AvatarNavigationPolicy.IsAllowed(args.Request.Uri))
            {
                DesktopLogger.Info("avatar.webview.blocked " + (Uri.TryCreate(args.Request.Uri, UriKind.Absolute, out var blocked) ? blocked.Scheme + "://" + blocked.Host + blocked.AbsolutePath : "unparsable"));
                args.Response = core.Environment.CreateWebResourceResponse(null, 403, "Blocked", string.Empty);
            }
        };

        core.NavigationCompleted += (_, args) =>
        {
            DesktopLogger.Info($"avatar.webview.navigation_completed success={args.IsSuccess} status={args.WebErrorStatus}");
            if (args.IsSuccess)
            {
                _loaded = true;
            }
            else
            {
                Fail("The avatar page didn't load.");
            }
        };
        core.WebMessageReceived += (_, args) =>
        {
            var message = AvatarProtocol.ParsePageMessage(args.WebMessageAsJson);
            DesktopLogger.Info("avatar.webview.page_message " + message.Kind + (message.Detail is null ? string.Empty : " " + message.Detail));
            _ui.TryEnqueue(() =>
            {
                StatusText.Text = message.Kind switch
                {
                    PageMessageKind.Ready => "Avatar ready",
                    PageMessageKind.Error => "Avatar unavailable: " + (message.Detail ?? "it couldn't load"),
                    _ => StatusText.Text,
                };
                if (message.Kind == PageMessageKind.Ready)
                {
                    StatusText.Opacity = 0; // invisible, but still there for screen readers and UI tests
                }

                PageMessageReceived?.Invoke(message);
            });
        };
        core.ProcessFailed += (_, _) => _ui.TryEnqueue(() => Fail("The avatar stopped. Restart REVA to bring it back."));
    }

    private void Fail(string text)
    {
        StatusText.Text = text;
        StatusText.Opacity = 1;
    }
}
