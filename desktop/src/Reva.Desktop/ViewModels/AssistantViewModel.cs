using System.Collections.ObjectModel;
using Reva.Desktop.Services;
using Reva.Desktop.State;

namespace Reva.Desktop.ViewModels;

/// <summary>
/// Typed assistant conversation for the current app session. No WinUI
/// types — testable without the XAML build pipeline. No persistence, no
/// history reload, no memory creation (that's Slice 4's "Remember this"
/// action, a deliberately separate, explicit code path — ADR-006).
/// </summary>
public sealed class AssistantViewModel : ObservableObject
{
    private readonly IRevaCoreClient _coreClient;
    private string _composerText = string.Empty;
    private bool _isPending;
    private string? _errorMessage;

    public AssistantViewModel(IRevaCoreClient coreClient)
    {
        _coreClient = coreClient;
    }

    public ObservableCollection<AssistantMessage> Messages { get; } = new();

    public string ComposerText
    {
        get => _composerText;
        set => SetProperty(ref _composerText, value);
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

    /// <summary>Plain bool (not a WinUI Visibility) so this stays bindable
    /// from XAML without a converter, and the ViewModel stays free of
    /// WinUI types.</summary>
    public bool IsNotPending => !IsPending;

    /// <summary>Safe, display-ready text only — never a raw exception,
    /// response body, or internal detail. Null when there is no error to
    /// show.</summary>
    public string? ErrorMessage
    {
        get => _errorMessage;
        private set => SetProperty(ref _errorMessage, value);
    }

    public async Task SendMessageAsync(CancellationToken cancellationToken = default)
    {
        if (IsPending)
        {
            // Duplicate submission while a request is already in flight —
            // ignored, not queued. Exactly one Core request per user click.
            return;
        }

        var trimmed = ComposerText.Trim();
        if (trimmed.Length == 0)
        {
            return;
        }

        ErrorMessage = null;
        IsPending = true;
        Messages.Add(AssistantMessage.FromUser(trimmed));
        ComposerText = string.Empty;

        try
        {
            var result = await _coreClient.SendMessageAsync(trimmed, cancellationToken);
            if (result.IsSuccess)
            {
                Messages.Add(AssistantMessage.FromAssistant(result.Value!.Reply));
            }
            else
            {
                ErrorMessage = result.Error!.SafeMessage;
            }
        }
        finally
        {
            IsPending = false;
        }
    }
}
