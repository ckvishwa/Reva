using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Explicit "Remember"/"Search" actions against REVA Core's durable memory
/// store (Slice 4). No WinUI types — testable without the XAML build
/// pipeline. This is the ONLY path in the desktop that creates durable
/// memory, and it only fires when the user explicitly invokes
/// <see cref="RememberAsync"/> — never from ordinary chat (ADR-006).
/// </summary>
public sealed class MemoryViewModel : ObservableObject
{
    private readonly IRevaCoreClient _coreClient;
    private string _memoryText = string.Empty;
    private bool _isPending;
    private string? _statusMessage;
    private string? _searchResultText;

    public MemoryViewModel(IRevaCoreClient coreClient)
    {
        _coreClient = coreClient;
    }

    public string MemoryText
    {
        get => _memoryText;
        set => SetProperty(ref _memoryText, value);
    }

    public bool IsPending
    {
        get => _isPending;
        private set
        {
            if (SetProperty(ref _isPending, value))
            {
                RaisePropertyChanged(nameof(IsNotPending));
            }
        }
    }

    public bool IsNotPending => !IsPending;

    /// <summary>Safe, display-ready feedback for the last Remember action —
    /// either success ("Remembered.") or a safe error message. Never a raw
    /// exception, response body, or internal detail.</summary>
    public string? StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    /// <summary>Safe, display-ready feedback for the last Search action.</summary>
    public string? SearchResultText
    {
        get => _searchResultText;
        private set => SetProperty(ref _searchResultText, value);
    }

    /// <summary>The only durable-memory-creating call in this client. Fires
    /// only when explicitly invoked by the user (a button click) — never
    /// automatically, never from chat.</summary>
    public async Task RememberAsync(CancellationToken cancellationToken = default)
    {
        if (IsPending)
        {
            return;
        }

        var trimmed = MemoryText.Trim();
        if (trimmed.Length == 0)
        {
            StatusMessage = "Nothing to remember: enter some text first.";
            return;
        }

        StatusMessage = null;
        IsPending = true;

        try
        {
            var result = await _coreClient.CreateMemoryAsync(trimmed, cancellationToken);
            if (result.IsSuccess)
            {
                StatusMessage = "Remembered.";
                MemoryText = string.Empty;
            }
            else
            {
                StatusMessage = result.Error!.SafeMessage;
            }
        }
        finally
        {
            IsPending = false;
        }
    }

    public async Task SearchAsync(string query, CancellationToken cancellationToken = default)
    {
        if (IsPending)
        {
            return;
        }

        var trimmed = query.Trim();
        if (trimmed.Length == 0)
        {
            SearchResultText = "Enter search text first.";
            return;
        }

        SearchResultText = null;
        IsPending = true;

        try
        {
            var result = await _coreClient.QueryMemoriesAsync(trimmed, limit: 5, cancellationToken);
            if (result.IsSuccess)
            {
                SearchResultText = result.Value!.Results.Count == 0
                    ? "No matching memories found."
                    : string.Join(Environment.NewLine, result.Value.Results.Select(r => r.Content));
            }
            else
            {
                SearchResultText = result.Error!.SafeMessage;
            }
        }
        finally
        {
            IsPending = false;
        }
    }
}
