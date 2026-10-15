using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Reva.Desktop.Actions;

/// <summary>The signed permission an executor acts on. Mirrors <c>reva_core/policy/grants.py</c>.</summary>
public sealed record Grant(
    string GrantId,
    string ActionId,
    string Capability,
    string ArgsHash,
    string TargetDevice,
    string Actor,
    string IssuedAt,
    string ExpiresAt,
    string IdempotencyKey,
    string Version);

public readonly record struct GrantCheck(bool Ok, string Reason)
{
    public static GrantCheck Pass { get; } = new(true, "OK");

    public static GrantCheck Fail(string reason) => new(false, reason);
}

/// <summary>What an executor runs before it does anything (AR-WIN-008): the signature, then expiry,
/// then that the grant is for exactly this capability, these arguments, this device and this
/// owner, then that its idempotency key has not been used. Reasons are the Core's stable codes.</summary>
public sealed class GrantVerifier : IDisposable
{
    public const string SupportedVersion = "1";
    private static readonly TimeSpan ClockSkew = TimeSpan.FromSeconds(5);
    private const int ReplayCapacity = 4096;

    private static readonly string[] FieldNames =
    {
        "action_id", "actor", "args_hash", "capability", "expires_at", "grant_id", "idempotency_key",
        "issued_at", "target_device", "version",
    };

    private readonly ECDsa _key;
    private readonly object _lock = new();
    private readonly HashSet<string> _seen = new(StringComparer.Ordinal);
    private readonly Queue<string> _order = new();

    public GrantVerifier(string publicKeyPem)
    {
        _key = ECDsa.Create();
        _key.ImportFromPem(publicKeyPem);
        if (_key.KeySize != 256)
        {
            _key.Dispose();
            throw new CryptographicException("the grant key must be an ECDSA P-256 key");
        }
    }

    public void Dispose() => _key.Dispose();

    public static string ArgsHash(JsonElement args) =>
        Convert.ToHexString(SHA256.HashData(CanonicalJson.Bytes(args, ensureAscii: false))).ToLowerInvariant();

    public static bool TryParseGrant(JsonElement element, out Grant grant)
    {
        grant = null!;
        if (element.ValueKind != JsonValueKind.Object)
        {
            return false;
        }

        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (property.Value.ValueKind != JsonValueKind.String || !FieldNames.Contains(property.Name))
            {
                return false;
            }

            values[property.Name] = property.Value.GetString() ?? string.Empty;
        }

        if (values.Count != FieldNames.Length)
        {
            return false;
        }

        grant = new Grant(
            values["grant_id"], values["action_id"], values["capability"], values["args_hash"],
            values["target_device"], values["actor"], values["issued_at"], values["expires_at"],
            values["idempotency_key"], values["version"]);
        return true;
    }

    /// <summary>Exactly the bytes the Core signed: all ten text fields, sorted keys, no spaces.</summary>
    public static byte[] SigningBytes(Grant g)
    {
        var builder = new StringBuilder("{");
        var fields = new (string Name, string Value)[]
        {
            ("action_id", g.ActionId), ("actor", g.Actor), ("args_hash", g.ArgsHash),
            ("capability", g.Capability), ("expires_at", g.ExpiresAt), ("grant_id", g.GrantId),
            ("idempotency_key", g.IdempotencyKey), ("issued_at", g.IssuedAt),
            ("target_device", g.TargetDevice), ("version", g.Version),
        };
        for (var i = 0; i < fields.Length; i++)
        {
            if (i > 0)
            {
                builder.Append(',');
            }

            builder.Append(CanonicalJson.WriteString(fields[i].Name, true));
            builder.Append(':');
            builder.Append(CanonicalJson.WriteString(fields[i].Value, true));
        }

        builder.Append('}');
        return Encoding.UTF8.GetBytes(builder.ToString());
    }

    public GrantCheck Verify(
        Grant grant,
        string signature,
        DateTimeOffset now,
        string capability,
        string argsHash,
        string targetDevice,
        string actor)
    {
        byte[] raw;
        try
        {
            raw = DecodeBase64Url(signature);
        }
        catch (FormatException)
        {
            return GrantCheck.Fail("MALFORMED");
        }

        if (raw.Length != 64 || grant.Version != SupportedVersion)
        {
            return GrantCheck.Fail("MALFORMED");
        }

        bool valid;
        lock (_lock)
        {
            valid = _key.VerifyData(
                SigningBytes(grant), raw, HashAlgorithmName.SHA256,
                DSASignatureFormat.IeeeP1363FixedFieldConcatenation);
        }

        if (!valid)
        {
            return GrantCheck.Fail("BAD_SIGNATURE");
        }

        if (!DateTimeOffset.TryParse(grant.IssuedAt, null, System.Globalization.DateTimeStyles.RoundtripKind, out var issued)
            || !DateTimeOffset.TryParse(grant.ExpiresAt, null, System.Globalization.DateTimeStyles.RoundtripKind, out var expires))
        {
            return GrantCheck.Fail("MALFORMED");
        }

        if (now >= expires)
        {
            return GrantCheck.Fail("EXPIRED");
        }

        if (issued - ClockSkew > now)
        {
            return GrantCheck.Fail("NOT_YET_VALID");
        }

        if (!string.Equals(grant.Capability, capability, StringComparison.Ordinal))
        {
            return GrantCheck.Fail("CAPABILITY_MISMATCH");
        }

        if (!string.Equals(grant.ArgsHash, argsHash, StringComparison.Ordinal))
        {
            return GrantCheck.Fail("ARGS_MISMATCH");
        }

        if (!string.Equals(grant.TargetDevice, targetDevice, StringComparison.Ordinal))
        {
            return GrantCheck.Fail("WRONG_TARGET");
        }

        if (!string.Equals(grant.Actor, actor, StringComparison.Ordinal))
        {
            return GrantCheck.Fail("WRONG_ACTOR");
        }

        lock (_lock)
        {
            if (!_seen.Add(grant.IdempotencyKey))
            {
                return GrantCheck.Fail("REPLAYED");
            }

            _order.Enqueue(grant.IdempotencyKey);
            while (_order.Count > ReplayCapacity)
            {
                _seen.Remove(_order.Dequeue());
            }
        }

        return GrantCheck.Pass;
    }

    private static byte[] DecodeBase64Url(string text)
    {
        var padded = text.Replace('-', '+').Replace('_', '/');
        padded = padded.PadRight(padded.Length + ((4 - (padded.Length % 4)) % 4), '=');
        return Convert.FromBase64String(padded);
    }
}
