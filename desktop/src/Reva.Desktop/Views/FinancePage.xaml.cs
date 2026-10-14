using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Reva.Desktop.ViewModels;
using Windows.Storage.Pickers;
using VirtualKey = Windows.System.VirtualKey;

namespace Reva.Desktop.Views;

/// <summary>
/// The Finance page. All data comes from <see cref="FinanceViewModel"/> (which talks to Core's
/// /v1/domains/finance API); this class only opens dialogs and file pickers and forwards clicks.
/// Every call is awaited, so the UI thread never waits on Core (AR-WIN-003).
/// </summary>
public sealed partial class FinancePage : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(FinanceViewModel), typeof(FinancePage),
        new PropertyMetadata(null, (d, e) => ((FinancePage)d).OnViewModelChanged((FinanceViewModel?)e.OldValue)));

    private readonly System.Collections.ObjectModel.ObservableCollection<object> _strip = new();
    private readonly DispatcherQueueTimer _searchTimer;
    private int _dialogOpen;

    public FinancePage()
    {
        InitializeComponent();
        HeaderCaption.Text = FinanceViewModel.HeaderCaption;
        NoteText.Text = FinanceViewModel.NoMoneyMovementNote;
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(NotePanel, FinanceViewModel.NoMoneyMovementNote);
        Strip.ItemsSource = _strip;
        _searchTimer = DispatcherQueue.GetForCurrentThread().CreateTimer();
        _searchTimer.Interval = TimeSpan.FromMilliseconds(300);
        _searchTimer.IsRepeating = false;
        _searchTimer.Tick += async (_, _) =>
        {
            if (ViewModel is { } vm)
            {
                await vm.SearchAsync();
            }
        };
    }

    public FinanceViewModel? ViewModel
    {
        get => (FinanceViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    /// <summary>Set by the window; file pickers in an unpackaged app need the window handle.</summary>
    public Func<nint> WindowHandle { get; set; } = () => 0;

    public static string BudgetTitle(string period) =>
        period == FinanceViewModel.LastMonth ? "Budgets · last month" : "Budgets · this month";

    public static double NetWorthFontSize(bool hasSnapshot) => hasSnapshot ? 24 : 16;

    /// <summary>Loads (or reloads) everything from Core; called whenever the page is opened.</summary>
    public Task RefreshAsync() => ViewModel?.RefreshAsync() ?? Task.CompletedTask;

    /// <summary>Reloads without the progress ring; used when Core says a sync changed Finance.</summary>
    public Task RefreshQuietlyAsync() => ViewModel?.RefreshAsync(showLoading: false) ?? Task.CompletedTask;

    private DispatcherQueueTimer? _conflictTimer;

    /// <summary>While Finance is the open section, look for a sync conflict every 10 seconds, because a paired
    /// phone can sync while the page is open. Only the banner is re-read.</summary>
    public void SetActive(bool active)
    {
        if (!active)
        {
            _conflictTimer?.Stop();
            return;
        }

        if (_conflictTimer is null)
        {
            _conflictTimer = DispatcherQueue.GetForCurrentThread().CreateTimer();
            _conflictTimer.Interval = TimeSpan.FromSeconds(10);
            _conflictTimer.IsRepeating = true;
            _conflictTimer.Tick += async (_, _) =>
            {
                if (ViewModel is { } vm)
                {
                    await vm.RefreshConflictsAsync();
                }
            };
        }

        _conflictTimer.Start();
    }

    private void OnViewModelChanged(FinanceViewModel? old)
    {
        if (old is not null)
        {
            old.PropertyChanged -= OnViewModelPropertyChanged;
            old.Accounts.CollectionChanged -= OnAccountsChanged;
        }

        if (ViewModel is { } vm)
        {
            vm.PropertyChanged += OnViewModelPropertyChanged;
            vm.Accounts.CollectionChanged += OnAccountsChanged;
        }

        Bindings.Update();
        Banner.Conflict = ViewModel?.Conflict;
        RebuildStrip();
    }

    private void OnAccountsChanged(object? sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e) => RebuildStrip();

    // The accounts strip shows one card per account followed by the net worth card, wrapped in one grid.
    private void RebuildStrip()
    {
        _strip.Clear();
        if (ViewModel is not { } vm)
        {
            return;
        }

        foreach (var account in vm.Accounts)
        {
            _strip.Add(account);
        }

        _strip.Add(vm.NetWorth);
    }

    private void OnViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(FinanceViewModel.Conflict))
        {
            Banner.Conflict = ViewModel?.Conflict;
        }
        else if (e.PropertyName == nameof(FinanceViewModel.NetWorth))
        {
            RebuildStrip();
        }
    }

    private async Task<ContentDialogResult> ShowDialogAsync(ContentDialog dialog)
    {
        // WinUI allows one ContentDialog at a time; a second open throws.
        if (Interlocked.Exchange(ref _dialogOpen, 1) == 1)
        {
            return ContentDialogResult.None;
        }

        try
        {
            dialog.XamlRoot = XamlRoot;
            return await dialog.ShowAsync();
        }
        finally
        {
            _dialogOpen = 0;
        }
    }

    private async void AddTransaction_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm)
        {
            return;
        }

        if (await ShowDialogAsync(new AddTransactionDialog(vm.NewAddTransaction())) == ContentDialogResult.Primary)
        {
            await vm.RefreshAsync();
        }
    }

    private async void AddAccount_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not { } vm)
        {
            return;
        }

        if (await ShowDialogAsync(new AddAccountDialog(vm.NewAddAccount())) == ContentDialogResult.Primary)
        {
            await vm.RefreshAsync();
        }
    }

    private async void Import_Click(object sender, RoutedEventArgs e) => await OpenImportAsync();

    private async void ImportRestore_Click(object sender, RoutedEventArgs e) => await OpenImportAsync();

    private async Task OpenImportAsync()
    {
        if (ViewModel is not { } vm)
        {
            return;
        }

        await ShowDialogAsync(new ImportDialog(vm.NewImport(), WindowHandle));
        await vm.RefreshAsync(); // an import may have saved rows even if the dialog was closed afterwards
    }

    private async void Snapshot_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            await vm.TakeSnapshotAsync();
        }
    }

    private async void Retry_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is { } vm)
        {
            await vm.RefreshAsync();
        }
    }

    private async void Banner_Resolved(object? sender, bool keepThisPc)
    {
        if (ViewModel is { } vm)
        {
            await vm.ResolveConflictAsync(keepThisPc);
        }
    }

    private async void Period_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ViewModel is not { } vm)
        {
            return;
        }

        var period = PeriodBox.SelectedIndex == 1 ? FinanceViewModel.LastMonth : FinanceViewModel.ThisMonth;
        if (period != vm.BudgetPeriod)
        {
            await vm.SetBudgetPeriodAsync(period);
        }
    }

    private void Search_TextChanged(object sender, TextChangedEventArgs e)
    {
        _searchTimer.Stop();
        _searchTimer.Start();
    }

    private async void Search_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter && ViewModel is { } vm)
        {
            _searchTimer.Stop();
            await vm.SearchAsync();
            e.Handled = true;
        }
    }

    private async void ExportCsv_Click(object sender, RoutedEventArgs e) => await ExportAsync("csv", "Transactions (CSV)", ".csv");

    private async void ExportJson_Click(object sender, RoutedEventArgs e) => await ExportAsync("json", "REVA Finance backup (JSON)", ".json");

    private async Task ExportAsync(string format, string typeName, string extension)
    {
        if (ViewModel is not { } vm)
        {
            return;
        }

        var picker = new FileSavePicker { SuggestedFileName = "reva-finance-" + DateTime.Now.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture) };
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WindowHandle());
        picker.FileTypeChoices.Add(typeName, new List<string> { extension });
        var file = await picker.PickSaveFileAsync();
        if (file is null)
        {
            return;
        }

        var result = await vm.ExportAsync(format);
        if (!result.IsSuccess)
        {
            await ShowMessageAsync("Export failed", result.Error!.SafeMessage);
            return;
        }

        try
        {
            await File.WriteAllBytesAsync(file.Path, result.Value!);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            await ShowMessageAsync("Export failed", "REVA could not write that file.");
            return;
        }

        await ShowMessageAsync("Export saved", "Saved to " + file.Path + ". The file is not encrypted — keep it somewhere private.");
    }

    private Task<ContentDialogResult> ShowMessageAsync(string title, string message) => ShowDialogAsync(new ContentDialog
    {
        Title = title,
        Content = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, Style = (Style)Application.Current.Resources["RevaBodyText"] },
        CloseButtonText = "OK",
        CloseButtonStyle = (Style)Application.Current.Resources["RevaSecondaryButton"],
        Background = (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["RevaSurfaceBrush"],
    });
}
