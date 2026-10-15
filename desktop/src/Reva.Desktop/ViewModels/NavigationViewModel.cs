using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

public enum NavGroup
{
    Domains,
    Tools,
}

public sealed record NavSection(string Id, string Title, NavGroup Group, bool IsBuilt)
{
    /// <summary>What Narrator reads for the item.</summary>
    public string AccessibleName => IsBuilt ? Title : $"{Title}, coming soon";

    public string Badge => IsBuilt ? string.Empty : "soon";
}

/// <summary>The left navigation. Every section from the design is listed; sections that are not
/// built yet stay selectable and open a "coming soon" page instead of pretending to work.</summary>
public sealed class NavigationViewModel : ObservableObject
{
    public const string TalkId = "talk";
    public const string FinanceId = "finance";
    public const string DevicesId = "devices";
    public const string SettingsId = "settings";
    public const string AppsId = "apps";
    public const string ActivityId = "activity";

    public static IReadOnlyList<NavSection> AllSections { get; } = new[]
    {
        new NavSection(TalkId, "Talk & Today", NavGroup.Domains, IsBuilt: true),
        new NavSection(FinanceId, "Finance", NavGroup.Domains, IsBuilt: true),
        new NavSection("health", "Health", NavGroup.Domains, IsBuilt: false),
        new NavSection("coach", "Coach", NavGroup.Domains, IsBuilt: false),
        new NavSection("career", "Career", NavGroup.Domains, IsBuilt: false),
        new NavSection("learn", "Learn", NavGroup.Domains, IsBuilt: false),
        new NavSection("cyber", "Cyber", NavGroup.Domains, IsBuilt: false),
        new NavSection("personal", "Personal", NavGroup.Domains, IsBuilt: false),
        new NavSection("memory", "Memory", NavGroup.Domains, IsBuilt: false),
        new NavSection(AppsId, "Apps & Actions", NavGroup.Tools, IsBuilt: true),
        new NavSection(ActivityId, "Activity", NavGroup.Tools, IsBuilt: true),
        new NavSection(DevicesId, "Devices", NavGroup.Tools, IsBuilt: true),
        new NavSection("persona", "Persona & Voice", NavGroup.Tools, IsBuilt: false),
        new NavSection(SettingsId, "Settings", NavGroup.Tools, IsBuilt: true),
    };

    public IReadOnlyList<NavSection> DomainSections { get; } = AllSections.Where(s => s.Group == NavGroup.Domains).ToList();

    public IReadOnlyList<NavSection> ToolSections { get; } = AllSections.Where(s => s.Group == NavGroup.Tools).ToList();

    private NavSection _selected = AllSections[0];

    public NavSection Selected
    {
        get => _selected;
        private set
        {
            if (SetProperty(ref _selected, value))
            {
                RaisePropertyChanged(nameof(ShowsTalk));
                RaisePropertyChanged(nameof(ShowsFinance));
                RaisePropertyChanged(nameof(ShowsDevices));
                RaisePropertyChanged(nameof(ShowsSettings));
                RaisePropertyChanged(nameof(ShowsApps));
                RaisePropertyChanged(nameof(ShowsActivity));
                RaisePropertyChanged(nameof(ShowsComingSoon));
                RaisePropertyChanged(nameof(ComingSoonTitle));
                RaisePropertyChanged(nameof(ComingSoonText));
            }
        }
    }

    public bool ShowsTalk => Selected.Id == TalkId;

    public bool ShowsFinance => Selected.Id == FinanceId;

    public bool ShowsDevices => Selected.Id == DevicesId;

    public bool ShowsSettings => Selected.Id == SettingsId;

    public bool ShowsApps => Selected.Id == AppsId;

    public bool ShowsActivity => Selected.Id == ActivityId;

    public bool ShowsComingSoon => !Selected.IsBuilt;

    public string ComingSoonTitle => Selected.Title;

    public string ComingSoonText => $"{Selected.Title} is coming soon. It isn't built yet.";

    /// <summary>Selects by id; unknown ids are ignored.</summary>
    public bool Select(string id)
    {
        var section = AllSections.FirstOrDefault(s => s.Id == id);
        if (section is null)
        {
            return false;
        }

        Selected = section;
        return true;
    }
}
