using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

/// <summary>
/// Left navigation. Every section from the design is listed; the ones that are not built show
/// "soon" and open a coming-soon page. Built in code so selection can restyle one button without
/// converters (see the Window-root note in MainWindow.xaml).
/// </summary>
public sealed partial class NavPane : UserControl
{
    private readonly Dictionary<string, (Button Button, TextBlock Title, NavSection Section)> _items = new();
    private NavigationViewModel? _nav;

    public NavPane()
    {
        InitializeComponent();
    }

    public void Attach(NavigationViewModel nav)
    {
        _nav = nav;
        foreach (var section in nav.DomainSections)
        {
            AddItem(section);
        }

        Items.Children.Add(new Border
        {
            Height = 1,
            Margin = new Thickness(6, 10, 6, 10),
            Background = (Brush)Application.Current.Resources["RevaBorderBrush"],
            IsHitTestVisible = false,
        });
        foreach (var section in nav.ToolSections)
        {
            AddItem(section);
        }

        nav.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(NavigationViewModel.Selected))
            {
                ApplySelection();
            }
        };
        ApplySelection();
    }

    private void AddItem(NavSection section)
    {
        var title = new TextBlock
        {
            Text = section.Title,
            VerticalAlignment = VerticalAlignment.Center,
            FontFamily = (FontFamily)Application.Current.Resources["RevaSans"],
        };
        var grid = new Grid { ColumnDefinitions = { new ColumnDefinition(), new ColumnDefinition { Width = GridLength.Auto } } };
        grid.Children.Add(title);
        if (!section.IsBuilt)
        {
            var badge = new TextBlock
            {
                Text = section.Badge,
                FontSize = 11,
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = (Brush)Application.Current.Resources["RevaMutedBrush"],
            };
            Grid.SetColumn(badge, 1);
            grid.Children.Add(badge);
        }

        var button = new Button
        {
            Content = grid,
            Style = (Style)Application.Current.Resources["RevaNavButton"],
        };
        AutomationProperties.SetAutomationId(button, "Nav_" + section.Id);
        button.Click += (_, _) => _nav?.Select(section.Id);
        Items.Children.Add(button);
        _items[section.Id] = (button, title, section);
    }

    private void ApplySelection()
    {
        if (_nav is null)
        {
            return;
        }

        foreach (var (id, item) in _items)
        {
            var selected = id == _nav.Selected.Id;
            var resources = Application.Current.Resources;
            item.Button.Background = selected ? (Brush)resources["RevaAccentBrush"] : new SolidColorBrush(Microsoft.UI.Colors.Transparent);
            item.Button.Foreground = (Brush)resources[selected ? "RevaGroundBrush" : "RevaSecondaryBrush"];
            item.Title.FontFamily = (FontFamily)resources[selected ? "RevaSansSemiBold" : "RevaSans"];
            AutomationProperties.SetName(item.Button, selected ? item.Section.AccessibleName + ", current page" : item.Section.AccessibleName);
        }
    }
}
