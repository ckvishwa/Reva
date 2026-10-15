using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Reva.Desktop.ViewModels;
using Reva.Desktop.Voice;
using Windows.System;

namespace Reva.Desktop.Views;

public sealed partial class LiveVoicePanel : UserControl
{
    public static readonly DependencyProperty ViewModelProperty = DependencyProperty.Register(
        nameof(ViewModel), typeof(LiveVoiceViewModel), typeof(LiveVoicePanel),
        new PropertyMetadata(null, (d, _) => ((LiveVoicePanel)d).OnViewModelChanged()));

    private bool _keyHeld;

    public AvatarView AvatarSurface => Avatar;

    public LiveVoicePanel()
    {
        InitializeComponent();
        TalkButton.AddHandler(
            UIElement.PointerPressedEvent, new PointerEventHandler(Talk_PointerPressed), handledEventsToo: true);
        TalkButton.AddHandler(
            UIElement.PointerReleasedEvent, new PointerEventHandler(Talk_PointerEnd), handledEventsToo: true);
        TalkButton.AddHandler(
            UIElement.PointerCanceledEvent, new PointerEventHandler(Talk_PointerEnd), handledEventsToo: true);
        TalkButton.AddHandler(
            UIElement.PointerCaptureLostEvent, new PointerEventHandler(Talk_PointerEnd), handledEventsToo: true);
        // Keyboard users hold Space or Enter on the focused button.
        TalkButton.AddHandler(UIElement.KeyDownEvent, new KeyEventHandler(Talk_KeyDown), handledEventsToo: true);
        TalkButton.AddHandler(UIElement.KeyUpEvent, new KeyEventHandler(Talk_KeyUp), handledEventsToo: true);
    }

    public LiveVoiceViewModel? ViewModel
    {
        get => (LiveVoiceViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    private void OnViewModelChanged()
    {
        Bindings.Update();
        if (ViewModel is { } vm)
        {
            vm.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName == nameof(LiveVoiceViewModel.MicOpen))
                {
                    ApplyMicDot();
                }
            };
            ApplyMicDot();
        }
    }

    private void ApplyMicDot()
    {
        var open = ViewModel?.MicOpen == true;
        MicDot.Fill = Vis.Brush(open ? "RevaSuccessBrush" : "RevaMutedBrush");
    }

    private async void VoiceToggle_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is null)
        {
            return;
        }

        if (VoiceToggle.IsChecked == true)
        {
            ViewModel.RefreshMicrophones();
            await ViewModel.TurnOnAsync();
        }
        else
        {
            await ViewModel.TurnOffAsync();
        }
    }

    private async void Talk_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        e.Handled = true;
        TalkButton.CapturePointer(e.Pointer);
        if (ViewModel is not null)
        {
            await ViewModel.TalkPressedAsync();
        }
    }

    private async void Talk_PointerEnd(object sender, PointerRoutedEventArgs e)
    {
        e.Handled = true;
        TalkButton.ReleasePointerCaptures();
        if (ViewModel is not null)
        {
            await ViewModel.TalkReleasedAsync();
        }
    }

    private async void Talk_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (_keyHeld || e.Key is not (VirtualKey.Space or VirtualKey.Enter) || ViewModel is null)
        {
            return;
        }

        _keyHeld = true;
        await ViewModel.TalkPressedAsync();
    }

    private async void Talk_KeyUp(object sender, KeyRoutedEventArgs e)
    {
        if (!_keyHeld || e.Key is not (VirtualKey.Space or VirtualKey.Enter) || ViewModel is null)
        {
            return;
        }

        _keyHeld = false;
        await ViewModel.TalkReleasedAsync();
    }

    private async void MicMute_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.SetMicMutedAsync(MicMuteToggle.IsChecked == true);
        }
    }

    private async void SpeakerMute_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.SetSpeakerMutedAsync(SpeakerMuteToggle.IsChecked == true);
        }
    }

    private async void Stop_Click(object sender, RoutedEventArgs e)
    {
        if (ViewModel is not null)
        {
            await ViewModel.StopSpeakingAsync();
        }
    }

    private void MicrophonePicker_DropDownOpened(object? sender, object e) => ViewModel?.RefreshMicrophones();

    private void MicrophonePicker_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ViewModel is not null && MicrophonePicker.SelectedItem is AudioDeviceInfo device)
        {
            ViewModel.SelectedMicrophone = device;
        }
    }
}
