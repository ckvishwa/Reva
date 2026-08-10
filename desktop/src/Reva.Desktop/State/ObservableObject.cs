using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace Reva.Desktop.State;

/// <summary>
/// Minimal INotifyPropertyChanged base. REVA's desktop MVVM is deliberately
/// hand-written and small — no CommunityToolkit.Mvvm/source-generator
/// dependency for three properties.
/// </summary>
public abstract class ObservableObject : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return false;
        }

        field = value;
        RaisePropertyChanged(propertyName);
        return true;
    }

    protected void RaisePropertyChanged(string? propertyName) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
