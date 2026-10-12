using Reva.Desktop.Contracts;

namespace Reva.Desktop.Services;

public interface IReasoningSettingsClient
{
    Task<CoreResult<ReasoningSettings>> GetReasoningSettingsAsync(
        CancellationToken cancellationToken = default);
    Task<CoreResult<ReasoningSettings>> SetReasoningSettingsAsync(
        bool enabled, CancellationToken cancellationToken = default);
    Task<CoreResult<KeySavedResponse>> SaveAnthropicKeyAsync(
        string key, CancellationToken cancellationToken = default);
}
