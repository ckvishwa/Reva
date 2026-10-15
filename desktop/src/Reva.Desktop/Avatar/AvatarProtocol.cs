using System.Text.Json;
using System.Text.Json.Nodes;

namespace Reva.Desktop.Avatar;

/// <summary>
/// Host-to-page messages (contracts/avatar-events.schema.json 2.1) and the page's two replies. Every
/// outgoing message is built here and nowhere else, so nothing that breaks the schema can be sent:
/// a builder returns null for input that would be invalid.
/// </summary>
public static class AvatarProtocol
{
    public static readonly string[] States = { "idle", "listening", "thinking", "speaking", "approval", "error" };
    public static readonly string[] Expressions = { "neutral", "happy", "sad", "relaxed", "surprised" };
    public static readonly string[] Causes = { "verified_outcome", "greeting", "error", "idle_variation", "mood" };
    public static readonly string[] Qualities = { "low", "medium", "high" };

    public static string? State(string state, int turnEpoch) =>
        Array.IndexOf(States, state) < 0 || turnEpoch < 0
            ? null
            : new JsonObject { ["type"] = "avatar.state", ["state"] = state, ["turn_epoch"] = turnEpoch }.ToJsonString();

    public static string? Mouth(int tMs, double rms, int turnEpoch)
    {
        if (tMs < 0 || turnEpoch < 0 || double.IsNaN(rms) || double.IsInfinity(rms))
        {
            return null;
        }

        var clamped = Math.Clamp(rms, 0.0, 1.0);
        return new JsonObject
        {
            ["type"] = "avatar.mouth",
            ["t_ms"] = tMs,
            ["rms"] = Math.Round(clamped, 4),
            ["turn_epoch"] = turnEpoch,
        }.ToJsonString();
    }

    /// <summary>A face. A result face (<c>verified_outcome</c>) must name its action; anything else is refused.</summary>
    public static string? Expression(string name, string cause, string? actionId)
    {
        if (Array.IndexOf(Expressions, name) < 0 || Array.IndexOf(Causes, cause) < 0)
        {
            return null;
        }

        if (actionId is not null && (actionId.Length < 8 || actionId.Length > 64))
        {
            return null;
        }

        if (cause == "verified_outcome" && actionId is null)
        {
            return null;
        }

        var message = new JsonObject { ["type"] = "avatar.expression", ["name"] = name, ["cause"] = cause };
        if (actionId is not null)
        {
            message["action_id"] = actionId;
        }

        return message.ToJsonString();
    }

    public static string? Settings(bool enabled, bool? reducedMotion, string? quality)
    {
        if (quality is not null && Array.IndexOf(Qualities, quality) < 0)
        {
            return null;
        }

        var message = new JsonObject { ["type"] = "avatar.settings", ["enabled"] = enabled };
        if (reducedMotion is not null)
        {
            message["reduced_motion"] = reducedMotion;
        }

        if (quality is not null)
        {
            message["quality"] = quality;
        }

        return message.ToJsonString();
    }

    /// <summary>What the page said. Anything other than ready or error is invalid and ignored.</summary>
    public static PageMessage ParsePageMessage(string? json)
    {
        if (string.IsNullOrWhiteSpace(json) || json.Length > 2000)
        {
            return PageMessage.Invalid;
        }

        try
        {
            if (JsonNode.Parse(json) is not JsonObject node)
            {
                return PageMessage.Invalid;
            }

            var type = node["type"]?.GetValue<string>();
            var detail = node["detail"]?.GetValue<string>();
            return type switch
            {
                "avatar.ready" => new PageMessage(PageMessageKind.Ready, null),
                "avatar.error" => new PageMessage(PageMessageKind.Error, detail is null ? null : detail[..Math.Min(detail.Length, 200)]),
                _ => PageMessage.Invalid,
            };
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or FormatException)
        {
            return PageMessage.Invalid;
        }
    }
}

public enum PageMessageKind
{
    Invalid,
    Ready,
    Error,
}

public sealed record PageMessage(PageMessageKind Kind, string? Detail)
{
    public static readonly PageMessage Invalid = new(PageMessageKind.Invalid, null);
}
