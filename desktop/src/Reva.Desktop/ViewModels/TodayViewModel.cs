using Reva.Desktop.Finance;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>The Finance part of the Today column: budget left this month and bills in the next 7
/// days. Read-only, from Core's /v1/today; other Today cards arrive with their domains.</summary>
public sealed class TodayViewModel : ObservableObject
{
    private readonly IFinanceApi _api;
    private readonly Func<DateOnly> _today;
    private int _generation;
    private bool _isLoading;
    private string? _errorMessage;
    private bool _hasBudget;
    private string _budgetLeftText = "…";
    private string _budgetOfText = string.Empty;
    private double _budgetFraction;
    private bool _budgetNearLimit;
    private string _otherCurrenciesText = string.Empty;
    private string _billsText = string.Empty;

    public TodayViewModel(IFinanceApi api, Func<DateOnly>? today = null)
    {
        _api = api;
        _today = today ?? (() => DateOnly.FromDateTime(DateTime.Now));
    }

    public bool IsLoading { get => _isLoading; private set => SetProperty(ref _isLoading, value); }

    public string? ErrorMessage
    {
        get => _errorMessage;
        private set
        {
            if (SetProperty(ref _errorMessage, value))
            {
                RaisePropertyChanged(nameof(HasError));
            }
        }
    }

    public bool HasError => !string.IsNullOrEmpty(ErrorMessage);

    public bool HasBudget { get => _hasBudget; private set => SetProperty(ref _hasBudget, value); }

    public string BudgetLeftText { get => _budgetLeftText; private set => SetProperty(ref _budgetLeftText, value); }

    public string BudgetOfText { get => _budgetOfText; private set => SetProperty(ref _budgetOfText, value); }

    /// <summary>Share of the month's budget already spent, 0 to 1.</summary>
    public double BudgetFraction { get => _budgetFraction; private set => SetProperty(ref _budgetFraction, value); }

    public bool BudgetNearLimit { get => _budgetNearLimit; private set => SetProperty(ref _budgetNearLimit, value); }

    /// <summary>Budgets in other currencies, one short line each. Empty when there is only one currency.</summary>
    public string OtherCurrenciesText { get => _otherCurrenciesText; private set => SetProperty(ref _otherCurrenciesText, value); }

    public string BillsText { get => _billsText; private set => SetProperty(ref _billsText, value); }

    public string AccessibleSummary =>
        HasError ? ErrorMessage! : $"Budget left this month: {BudgetLeftText} {BudgetOfText}. {BillsText}";

    public async Task RefreshAsync(CancellationToken cancellationToken = default, bool showLoading = true)
    {
        var generation = Interlocked.Increment(ref _generation);
        IsLoading = showLoading;
        try
        {
            var result = await _api.GetTodayAsync(cancellationToken).ConfigureAwait(true);
            if (generation != Volatile.Read(ref _generation))
            {
                return;
            }

            if (!result.IsSuccess)
            {
                ErrorMessage = result.Error!.SafeMessage;
                HasBudget = false;
                BudgetLeftText = "—";
                BudgetOfText = string.Empty;
                BillsText = string.Empty;
                RaisePropertyChanged(nameof(AccessibleSummary));
                return;
            }

            ErrorMessage = null;
            Apply(result.Value!.Domains.Finance);
        }
        finally
        {
            if (generation == Volatile.Read(ref _generation))
            {
                IsLoading = false;
            }
        }
    }

    private void Apply(TodayFinance? finance)
    {
        var today = _today();
        var budgets = finance?.BudgetLeft ?? Array.Empty<TodayBudgetLeft>();
        if (budgets.Count == 0)
        {
            HasBudget = false;
            BudgetLeftText = "No budgets set";
            BudgetOfText = string.Empty;
            BudgetFraction = 0;
            BudgetNearLimit = false;
            OtherCurrenciesText = string.Empty;
        }
        else
        {
            var main = budgets.OrderByDescending(b => b.BudgetMinor).First();
            HasBudget = true;
            BudgetLeftText = MoneyFormat.Format(main.RemainingMinor, main.Currency);
            BudgetOfText = $"of {MoneyFormat.Format(main.BudgetMinor, main.Currency)}";
            var usedBp = main.BudgetMinor > 0 ? (long)(main.SpentMinor * 10_000m / main.BudgetMinor) : 0;
            BudgetFraction = FinanceDisplay.BarFraction(usedBp);
            BudgetNearLimit = FinanceDisplay.IsNearLimit(usedBp);
            OtherCurrenciesText = string.Join(
                " · ",
                budgets.Where(b => b != main)
                    .Select(b => $"{MoneyFormat.Format(b.RemainingMinor, b.Currency)} left of {MoneyFormat.Format(b.BudgetMinor, b.Currency)}"));
        }

        var bills = (finance?.BillsDue ?? Array.Empty<FinanceBill>())
            .Where(b => !string.Equals(b.Kind, "income", StringComparison.Ordinal))
            .ToList();
        BillsText = bills.Count == 0
            ? "No bills in the next 7 days"
            : "Bills in 7 days · " + string.Join(" · ", bills.Select(b => $"{b.Name} {FinanceDisplay.ShortDate(b.DueDate, today)}"));
        RaisePropertyChanged(nameof(AccessibleSummary));
    }
}
