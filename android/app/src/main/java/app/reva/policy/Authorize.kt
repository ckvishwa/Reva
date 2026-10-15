package app.reva.policy

import java.security.MessageDigest
import java.time.Instant

/**
 * `authorize(proposal, state) -> AuthorizationDecision`, ported from `reva_core/policy/authorize.py`
 * (ARD-450 3.6, AR-LANG-007, AR-AGT-003/4/6).
 *
 * Pure by construction: no model call, no I/O, no writes, no clock (the caller passes `now`), no randomness.
 * The same inputs always give the same decision with the same stable reason code, whether the proposal came from
 * the rule fast path or from a planner. The order of checks is part of the contract (and of
 * `tests/fixtures/authorize-cases.json`, which the Python implementation writes and this one replays):
 *
 *   1 forbidden capability   2 unknown capability   3 arguments fit the schema
 *   4 every entity has trustworthy evidence   5 no unresolved content words
 *   6 no competing candidate within the margin   7 an approval, if present, is bound to this proposal
 *   8 consent and device scope   9 tier (T3 denied; T2 needs a click or tap on the right screen)
 *
 * A spoken "yes" is not an approval for T2: only a click or tap is (CLAUDE.md safety invariants).
 */
const val AUTHORIZER_VERSION = "1.0.0"
const val AMBIGUITY_MARGIN = 0.15
const val MAX_OPTIONS = 3

enum class Resolution(val wire: String) {
    Exact("exact"), Alias("alias"), Confirmed("confirmed"), TypedValue("typed_value"),
    Lexical("lexical"), Fuzzy("fuzzy"), Vector("vector"), None("none");

    companion object {
        fun of(wire: String) = entries.first { it.wire == wire }
    }
}

val TRUSTED = setOf(Resolution.Exact, Resolution.Alias, Resolution.Confirmed, Resolution.TypedValue)

data class Entity(
    val slot: String,
    val phrase: String,
    val resolution: Resolution,
    val score: Double? = null,
    val margin: Double? = null,
    val candidates: List<String> = emptyList(),
)

data class Proposal(
    val proposalId: String,
    val capability: String,
    val args: Map<String, Any?>,
    val entities: List<Entity> = emptyList(),
    val unresolvedTerms: List<String> = emptyList(),
    val source: String = "rule",
    val originDevice: String = "local",
    val targetDevice: String = "local",
    val hostedOrigin: Boolean = false,
)

/** A click or tap on [targetDevice]'s screen. `via` of "speech" never counts. */
data class Approval(
    val proposalId: String,
    val argsHash: String,
    val targetDevice: String,
    val user: String,
    val via: String,
    val expiresAt: Instant,
)

data class AuthState(
    val now: Instant,
    val approval: Approval? = null,
    val user: String = "owner",
    val consent: Map<String, Boolean> = emptyMap(),
    /** null: local, unrestricted. */
    val deviceScopes: Set<String>? = null,
)

data class Decision(
    val proposalId: String,
    val allowed: Boolean,
    val reason: String,
    val tier: String? = null,
    val unresolved: List<String> = emptyList(),
    val clarification: Map<String, Any?>? = null,
    val problems: List<String> = emptyList(),
    val authorizerVersion: String = AUTHORIZER_VERSION,
)

/** One spelling for a set of arguments: sorted keys, no spaces, UTF-8 characters kept (same as the PC). */
fun canonicalArgs(args: Map<String, Any?>): String = canonicalValue(args)

private fun canonicalValue(v: Any?): String = when (v) {
    null -> "null"
    is Boolean -> v.toString()
    is String -> quote(v)
    is Int, is Long, is Short, is Byte -> v.toString()
    is Double -> canonicalDouble(v)
    is Float -> canonicalDouble(v.toDouble())
    is Map<*, *> -> v.entries.sortedBy { it.key as String }
        .joinToString(",", "{", "}") { quote(it.key as String) + ":" + canonicalValue(it.value) }
    is List<*> -> v.joinToString(",", "[", "]") { canonicalValue(it) }
    else -> throw IllegalArgumentException("unsupported argument value ${v::class.simpleName}")
}

/** Python's repr for the doubles that appear in arguments: whole numbers keep ".0", others the shortest digits. */
private fun canonicalDouble(d: Double): String {
    require(!d.isNaN() && !d.isInfinite()) { "non-finite number" }
    if (d == Math.rint(d) && Math.abs(d) < 1e16) return d.toLong().toString() + ".0"
    return d.toString()
}

private fun quote(s: String): String {
    val out = StringBuilder("\"")
    for (c in s) {
        when {
            c == '"' -> out.append("\\\"")
            c == '\\' -> out.append("\\\\")
            c == '\n' -> out.append("\\n")
            c == '\r' -> out.append("\\r")
            c == '\t' -> out.append("\\t")
            c == '\b' -> out.append("\\b")
            c == '\u000c' -> out.append("\\f")
            c.code < 0x20 -> out.append("\\u%04x".format(c.code))
            else -> out.append(c)
        }
    }
    return out.append('"').toString()
}

fun argsHash(args: Map<String, Any?>): String =
    MessageDigest.getInstance("SHA-256").digest(canonicalArgs(args).toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

fun authorize(proposal: Proposal, state: AuthState, registry: Registry): Decision {
    val pid = proposal.proposalId

    fun no(reason: String, tier: Tier? = null, unresolved: List<String> = emptyList(), clarification: Map<String, Any?>? = null, problems: List<String> = emptyList()) =
        Decision(pid, false, reason, tier?.name, unresolved, clarification, problems)

    if (registry.isForbidden(proposal.capability)) return no("FORBIDDEN_CAPABILITY")
    val capability = registry[proposal.capability] ?: return no("UNKNOWN_CAPABILITY")
    val tier = capability.tier

    val problems = registry.validateArgs(capability, proposal.args)
    if (problems.isNotEmpty()) return no("INVALID_ARGS", tier, problems = problems)

    for (entity in proposal.entities) {
        if (entity.resolution !in TRUSTED) {
            val reason = if (entity.resolution == Resolution.None) "UNRESOLVED_TERMS" else "LOW_EVIDENCE"
            return no(reason, tier, listOf(entity.phrase), clarification(entity))
        }
    }
    if (proposal.unresolvedTerms.isNotEmpty()) {
        return no("UNRESOLVED_TERMS", tier, proposal.unresolvedTerms, mapOf("question_template" to "unresolved_terms"))
    }
    for (entity in proposal.entities) {
        if (entity.candidates.size > 1 && (entity.margin == null || entity.margin < AMBIGUITY_MARGIN)) {
            return no(
                "AMBIGUOUS_ENTITY", tier, listOf(entity.phrase),
                mapOf("question_template" to "ambiguous_entity", "options" to entity.candidates.take(MAX_OPTIONS)),
            )
        }
    }

    val approval = state.approval
    if (approval != null && !bound(approval, proposal, state, capability.confirmOn)) return no("STATE_MISMATCH", tier)

    val domain = capability.domain
    if (proposal.hostedOrigin && domain != null && state.consent[domain] != true) return no("CONSENT_REQUIRED", tier)
    val scopes = state.deviceScopes
    if (scopes != null && !inScope(capability.device, domain, scopes)) return no("CONSENT_REQUIRED", tier)

    if (tier == Tier.T3) return no("DENIED_TIER", tier)
    if (tier == Tier.T2 && (approval == null || approval.via !in setOf("click", "tap") || !state.now.isBefore(approval.expiresAt))) {
        return no("APPROVAL_REQUIRED", tier)
    }
    return Decision(pid, true, "OK", tier.name)
}

/** An approval counts only for this proposal, these arguments, this user and device. */
private fun bound(approval: Approval, proposal: Proposal, state: AuthState, confirmOn: String?): Boolean {
    if (approval.proposalId != proposal.proposalId) return false
    if (approval.argsHash != argsHash(proposal.args)) return false
    if (approval.user != state.user) return false
    val expected = if (confirmOn == "target") proposal.targetDevice else proposal.originDevice
    return approval.targetDevice == expected
}

private fun inScope(device: String, domain: String?, scopes: Set<String>): Boolean =
    if (domain != null) domain in scopes else device in scopes || "any" in scopes

private fun clarification(entity: Entity): Map<String, Any?> {
    val out = linkedMapOf<String, Any?>("question_template" to "which_${entity.slot}")
    if (entity.candidates.isNotEmpty()) out["options"] = entity.candidates.take(MAX_OPTIONS)
    return out
}
