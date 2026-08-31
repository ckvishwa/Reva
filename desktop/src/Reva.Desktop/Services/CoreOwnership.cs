namespace Reva.Desktop.Services;

/// <summary>
/// Whether this Desktop instance launched the Core process it is talking
/// to (<see cref="Owned"/>) or found one already running and attached to
/// it (<see cref="External"/>). Decided once, at the single point
/// <see cref="RevaCoreLifecycle.StartAsync"/> either attaches or launches —
/// never re-derived or inferred elsewhere. Every stop/kill path must gate
/// on this: REVA must never kill a Core process it did not start.
/// </summary>
public enum CoreOwnership
{
    /// <summary>No Core process is owned or attached to yet (before
    /// <see cref="RevaCoreLifecycle.StartAsync"/> has decided). Treated the
    /// same as <see cref="External"/> by every stop/kill path — the safe
    /// default is to never assume ownership.</summary>
    External,

    /// <summary>This instance launched the Core process itself.</summary>
    Owned,
}
