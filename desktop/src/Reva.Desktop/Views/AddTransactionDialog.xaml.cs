using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class AddTransactionDialog : ContentDialog
{
    public AddTransactionDialog(AddTransactionViewModel vm)
    {
        Vm = vm;
        InitializeComponent();
        DatePicker.Date = vm.Date;
        // The dialog moves focus to its first control after it opens; take it back once that has happened.
        Opened += async (_, _) =>
        {
            await Task.Delay(150);
            AmountBox.Focus(FocusState.Keyboard);
        };
    }

    public AddTransactionViewModel Vm { get; }

    private void DatePicker_DateChanged(CalendarDatePicker sender, CalendarDatePickerDateChangedEventArgs args)
    {
        if (args.NewDate is { } date)
        {
            Vm.Date = date;
        }
    }

    // Keep the dialog open until Core has accepted the transaction; errors stay next to the fields.
    private async void Save_Click(ContentDialog sender, ContentDialogButtonClickEventArgs args)
    {
        var deferral = args.GetDeferral();
        try
        {
            args.Cancel = !await Vm.SubmitAsync();
        }
        finally
        {
            deferral.Complete();
        }
    }
}
