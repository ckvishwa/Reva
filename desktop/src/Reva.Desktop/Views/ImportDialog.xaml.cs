using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Reva.Desktop.ViewModels;
using Windows.Storage.Pickers;

namespace Reva.Desktop.Views;

/// <summary>
/// Import flow: choose a file, match CSV columns, "Check file" shows the dry-run row report, and
/// only the Import button (enabled after a successful check of exactly these choices) saves rows.
/// </summary>
public sealed partial class ImportDialog : ContentDialog
{
    private const string None = "(none)";

    private readonly Func<nint> _windowHandle;

    public ImportDialog(ImportViewModel vm, Func<nint> windowHandle)
    {
        Vm = vm;
        _windowHandle = windowHandle;
        InitializeComponent();
        Vm.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(ImportViewModel.ResultText) && Vm.ResultText is not null)
            {
                CloseButtonText = "Done";
            }
        };
    }

    public ImportViewModel Vm { get; }

    public static Brush StatusBrush(string status) => (Brush)Application.Current.Resources[status switch
    {
        "accepted" => "RevaSuccessBrush",
        "rejected" => "RevaErrorBrush",
        _ => "RevaMutedBrush",
    }];

    private async void Choose_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        WinRT.Interop.InitializeWithWindow.Initialize(picker, _windowHandle());
        foreach (var extension in new[] { ".csv", ".ofx", ".qfx", ".json" })
        {
            picker.FileTypeFilter.Add(extension);
        }

        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return;
        }

        try
        {
            var length = new FileInfo(file.Path).Length;
            if (length > ImportViewModel.MaxFileBytes)
            {
                Vm.RejectTooLarge(file.Name);
            }
            else
            {
                Vm.LoadFile(file.Name, await File.ReadAllBytesAsync(file.Path));
            }
        }
        catch (IOException)
        {
            Vm.RejectUnreadable(file.Name);
        }
        catch (UnauthorizedAccessException)
        {
            Vm.RejectUnreadable(file.Name);
        }

        BuildMapping();
    }

    private async void Check_Click(object sender, RoutedEventArgs e) => await Vm.CheckAsync();

    private async void Confirm_Click(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var deferral = args.GetDeferral();
        try
        {
            await Vm.ConfirmAsync();
            args.Cancel = true; // stay open to show the result; the person closes with "Done"
        }
        finally
        {
            deferral.Complete();
        }
    }

    private void BuildMapping()
    {
        MappingCombos.Children.Clear();
        if (!Vm.IsCsv)
        {
            return;
        }

        AddColumnPicker("Date column", () => Vm.DateColumn, v => Vm.DateColumn = v, "ImportDateColumn");
        AddColumnPicker("Description column", () => Vm.DescriptionColumn, v => Vm.DescriptionColumn = v, "ImportDescriptionColumn");
        AddColumnPicker("Amount column (one column with + and -)", () => Vm.AmountColumn, v => Vm.AmountColumn = v, "ImportAmountColumn");
        AddColumnPicker("Debit column (money out)", () => Vm.DebitColumn, v => Vm.DebitColumn = v, "ImportDebitColumn");
        AddColumnPicker("Credit column (money in)", () => Vm.CreditColumn, v => Vm.CreditColumn = v, "ImportCreditColumn");
        AddColumnPicker("Category column", () => Vm.CategoryColumn, v => Vm.CategoryColumn = v, "ImportCategoryColumn");
    }

    private void AddColumnPicker(string header, Func<string?> get, Action<string?> set, string automationId)
    {
        var box = new ComboBox
        {
            Header = header,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            MinHeight = 44,
        };
        box.Items.Add(None);
        foreach (var name in Vm.Headers)
        {
            box.Items.Add(name);
        }

        box.SelectedItem = get() ?? None;
        AutomationProperties.SetAutomationId(box, automationId);
        box.SelectionChanged += (_, _) =>
        {
            if (box.SelectedItem is string chosen)
            {
                set(chosen == None ? null : chosen);
            }
        };
        MappingCombos.Children.Add(box);
    }
}
