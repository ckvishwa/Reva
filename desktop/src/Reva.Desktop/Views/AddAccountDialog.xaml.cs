using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class AddAccountDialog : ContentDialog
{
    public AddAccountDialog(AddAccountViewModel vm)
    {
        Vm = vm;
        InitializeComponent();
        // The dialog moves focus to its first control after it opens; take it back once that has happened.
        Opened += async (_, _) =>
        {
            await Task.Delay(150);
            NameBox.Focus(FocusState.Keyboard);
        };
    }

    public static IReadOnlyList<string> Kinds => AddAccountViewModel.Kinds;

    public AddAccountViewModel Vm { get; }

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
