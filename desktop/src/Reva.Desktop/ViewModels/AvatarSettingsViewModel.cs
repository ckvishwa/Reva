using Reva.Desktop.Avatar;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>Settings > Avatar: show it or not, reduced motion, quality. Every change is saved and applied at once.</summary>
public sealed class AvatarSettingsViewModel : ObservableObject
{
    public static readonly string[] Qualities = AvatarProtocol.Qualities;
    public static readonly string[] MotionChoices = { "Follow Windows", "Reduce motion", "Full motion" };

    private readonly AvatarSettingsStore _store;
    private readonly Action<AvatarSettings> _apply;
    private bool _enabled;
    private int _motionIndex;
    private int _qualityIndex;
    private bool _loading;

    /// <summary>Raised after every saved change; the window applies it to the avatar.</summary>
    public event Action<AvatarSettings>? Applied;

    public AvatarSettingsViewModel(AvatarSettingsStore store, Action<AvatarSettings>? apply = null)
    {
        _store = store;
        _apply = apply ?? (_ => { });
        Load(store.Load());
    }

    public bool Enabled
    {
        get => _enabled;
        set => Change(ref _enabled, value);
    }

    /// <summary>0 follow Windows, 1 reduce motion, 2 full motion.</summary>
    public int MotionIndex
    {
        get => _motionIndex;
        set => Change(ref _motionIndex, Math.Clamp(value, 0, 2));
    }

    public int QualityIndex
    {
        get => _qualityIndex;
        set => Change(ref _qualityIndex, Math.Clamp(value, 0, Qualities.Length - 1));
    }

    public AvatarSettings Current => new(
        _enabled,
        _motionIndex switch { 1 => true, 2 => false, _ => null },
        Qualities[_qualityIndex]);

    private void Load(AvatarSettings settings)
    {
        _loading = true;
        Enabled = settings.Enabled;
        MotionIndex = settings.ReducedMotion switch { true => 1, false => 2, _ => 0 };
        QualityIndex = Math.Max(0, Array.IndexOf(Qualities, settings.Quality));
        _loading = false;
    }

    private void Change<T>(ref T field, T value)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return;
        }

        field = value;
        RaisePropertyChanged(null);
        if (!_loading)
        {
            var settings = Current;
            _store.Save(settings);
            _apply(settings);
            Applied?.Invoke(settings);
        }
    }
}
