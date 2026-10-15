using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

public sealed partial class SettingsPage : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(CloudSettingsViewModel), typeof(SettingsPage),
        new PropertyMetadata(null, (d, _) => ((SettingsPage)d).Bindings.Update()));

    public static readonly DependencyProperty AvatarViewModelProperty = DependencyProperty.Register(
        nameof(AvatarViewModel), typeof(AvatarSettingsViewModel), typeof(SettingsPage),
        new PropertyMetadata(null, (d, _) => ((SettingsPage)d).Bindings.Update()));

    private bool _syncing;

    public SettingsPage()
    {
        InitializeComponent();
    }

    public AvatarSettingsViewModel? AvatarViewModel
    {
        get => (AvatarSettingsViewModel?)GetValue(AvatarViewModelProperty);
        set => SetValue(AvatarViewModelProperty, value);
    }

    public CloudSettingsViewModel? ViewModel
    {
        get => (CloudSettingsViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public async Task LoadAsync()
    {
        if (ViewModel is null)
        {
            return;
        }

        _syncing = true;
        try
        {
            await ViewModel.LoadAsync();
        }
        finally
        {
            _syncing = false;
        }
    }

    private async void StoreKey_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is null)
        {
            return;
        }

        var key = KeyBox.Password;
        KeyBox.Password = string.Empty; // the key is not kept in the control after it is sent
        await ViewModel.StoreKeyAsync(key);
    }

    private async void RemoveKey_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.RemoveKeyAsync();
        }
    }

    private async void CloudSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (ViewModel is null || _syncing || CloudSwitch.IsOn == ViewModel.Enabled)
        {
            return;
        }

        await ViewModel.SetEnabledAsync(CloudSwitch.IsOn);
    }

    private async void DomainSwitch_Toggled(object sender, RoutedEventArgs e)
    {
        if (ViewModel is null || _syncing || sender is not ToggleSwitch toggle || toggle.Tag is not string id)
        {
            return;
        }

        var row = ViewModel.Domains.FirstOrDefault(d => d.Id == id);
        if (row is null || row.IsOn == toggle.IsOn)
        {
            return;
        }

        await ViewModel.SetDomainAsync(id, toggle.IsOn);
    }
}
