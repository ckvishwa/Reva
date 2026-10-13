using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Reva.Desktop.ViewModels;

namespace Reva.Desktop.Views;

/// <summary>Picks the card template for the accounts strip: account balances, then the net worth card.</summary>
public sealed class StripTemplateSelector : DataTemplateSelector
{
    public DataTemplate? Account { get; set; }

    public DataTemplate? NetWorth { get; set; }

    protected override DataTemplate? SelectTemplateCore(object item) => item is NetWorthCardViewModel ? NetWorth : Account;

    protected override DataTemplate? SelectTemplateCore(object item, DependencyObject container) => SelectTemplateCore(item);
}
