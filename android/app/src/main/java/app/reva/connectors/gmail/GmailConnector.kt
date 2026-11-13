package app.reva.connectors.gmail

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * CON-1: read-only Gmail authorization on the phone.
 *
 * The only scope REVA ever asks for. It lets the app read the whole mailbox, which is why the Connect screen says so
 * before the user taps. No send, modify, compose, delete or full-mailbox scope exists in this code, and
 * GmailSourceGuardTest fails the build if one appears.
 */
const val GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"

/** What Google answered when asked for a token for [GMAIL_READONLY]. */
sealed interface AuthStep {
    /** The token is used for one request and then dropped; it is never stored, logged or shown. */
    class Granted(val accessToken: String, val grantedScopes: Set<String>) : AuthStep {
        override fun toString() = "Granted(token=<redacted>, scopes=$grantedScopes)"
    }

    /** Google needs the user: account choice or consent. [resolution] is Android's PendingIntent, opaque here. */
    class NeedsUser(val resolution: Any) : AuthStep

    data class Failed(val failure: GmailFailure) : AuthStep
}

/** Why Gmail is not connected, each with what the user can do about it. */
enum class GmailFailure(val message: String, val remedy: GmailRemedy) {
    Denied("Gmail access was not granted. Nothing was read.", GmailRemedy.Connect),
    ScopeNotGranted("Google did not grant read-only Gmail access. Try again and allow it.", GmailRemedy.Connect),
    ReconsentNeeded("Gmail access was removed or has expired. Connect again to allow it.", GmailRemedy.Connect),
    Unauthorized("Google refused the sign-in token twice. Connect again.", GmailRemedy.Connect),
    Forbidden("Gmail refused the request (403). This account may not be a test user of the REVA app.", GmailRemedy.Retry),
    RateLimited("Gmail is limiting requests right now. Try again in a minute.", GmailRemedy.Retry),
    ServerError("Gmail had a server problem. Try again.", GmailRemedy.Retry),
    Network("No connection to Google. Check the network and try again.", GmailRemedy.Retry),
    PlayServicesUnavailable("Google Play services is missing or out of date on this phone.", GmailRemedy.None),
    Unexpected("Something unexpected went wrong. Try again.", GmailRemedy.Retry),
}

enum class GmailRemedy { Connect, Retry, None }

/** Outcome of the single read the connection check makes. Carries a status code only, never mailbox content. */
sealed interface ProbeResult {
    data class Http(val status: Int) : ProbeResult
    data object NetworkError : ProbeResult
}

interface GmailAuthorizer {
    /** Asks Google for a token without showing anything; Google decides whether the user is needed. */
    suspend fun authorize(): AuthStep

    /** Reads the result Google's account/consent screen returned ([data] is the result Intent). */
    suspend fun fromConsentResult(data: Any?): AuthStep

    /** Tells Play services to forget a token the Gmail API rejected, so the next [authorize] gets a fresh one. */
    suspend fun clearToken(accessToken: String)

    /** Revokes REVA's Gmail grant at Google. Returns false when it could not be confirmed. */
    suspend fun revoke(): Boolean
}

interface GmailProbe {
    /** `users.messages.list` with `maxResults=1`. */
    suspend fun listOneMessage(accessToken: String): ProbeResult
}

/** Remembers only whether the user connected Gmail. No token, address or message is stored. */
interface GmailConnectionStore {
    var connected: Boolean
}

sealed interface GmailState {
    /** [revokeConfirmed] is false when the user disconnected but Google could not confirm the revoke. */
    data class Disconnected(val revokeConfirmed: Boolean = true) : GmailState
    data object Working : GmailState
    class NeedsUser(val resolution: Any) : GmailState
    /** The last check reached Gmail and got [httpStatus] (200). */
    data class Connected(val httpStatus: Int) : GmailState
    data class Failed(val failure: GmailFailure) : GmailState
}

/**
 * The connection state machine. Every run is user-initiated (Connect, Retry, opening the Gmail screen); nothing runs in
 * the background. A token rejected with 401 is cleared and fetched once more silently, which covers expiry; a
 * second 401, or Google asking for the user during a silent check, means access was revoked or must be granted again.
 */
class GmailConnector(
    private val authorizer: GmailAuthorizer,
    private val probe: GmailProbe,
    private val store: GmailConnectionStore,
) {
    private val mutex = Mutex()
    private val _state = MutableStateFlow<GmailState>(GmailState.Disconnected())
    val state: StateFlow<GmailState> = _state.asStateFlow()

    /** True when the user connected Gmail earlier and has not disconnected. */
    val wasConnected: Boolean get() = store.connected

    /** User tapped Connect (or Connect again). Google may ask the user to pick an account and consent. */
    suspend fun connect() = run(interactive = true) { authorizer.authorize() }

    /** The account/consent screen closed. [ok] is false when the user backed out or refused. */
    suspend fun onConsentResult(ok: Boolean, data: Any?) = mutex.withLock {
        if (!ok) {
            store.connected = false
            _state.value = GmailState.Failed(GmailFailure.Denied)
            return@withLock
        }
        _state.value = GmailState.Working
        handle(authorizer.fromConsentResult(data), interactive = true, retryOn401 = true)
    }

    /** Checks an earlier connection without showing Google's screens; used for Retry and when the screen opens. */
    suspend fun recheck() = run(interactive = false) { authorizer.authorize() }

    suspend fun disconnect() = mutex.withLock {
        _state.value = GmailState.Working
        val confirmed = runCatching { authorizer.revoke() }.getOrDefault(false)
        store.connected = false
        _state.value = GmailState.Disconnected(revokeConfirmed = confirmed)
    }

    private suspend fun run(interactive: Boolean, step: suspend () -> AuthStep) = mutex.withLock {
        _state.value = GmailState.Working
        handle(step(), interactive, retryOn401 = true)
    }

    private suspend fun handle(step: AuthStep, interactive: Boolean, retryOn401: Boolean) {
        when (step) {
            is AuthStep.Failed -> fail(step.failure)
            is AuthStep.NeedsUser ->
                if (interactive) _state.value = GmailState.NeedsUser(step.resolution) else fail(GmailFailure.ReconsentNeeded)
            is AuthStep.Granted ->
                if (GMAIL_READONLY !in step.grantedScopes) fail(GmailFailure.ScopeNotGranted)
                else probeWith(step.accessToken, interactive, retryOn401)
        }
    }

    private suspend fun probeWith(token: String, interactive: Boolean, retryOn401: Boolean) {
        when (val result = probe.listOneMessage(token)) {
            ProbeResult.NetworkError -> fail(GmailFailure.Network, keepConnected = true)
            is ProbeResult.Http -> when (val status = result.status) {
                200 -> {
                    store.connected = true
                    _state.value = GmailState.Connected(status)
                }
                401 -> {
                    runCatching { authorizer.clearToken(token) }
                    if (retryOn401) handle(authorizer.authorize(), interactive, retryOn401 = false)
                    else fail(GmailFailure.Unauthorized)
                }
                403 -> fail(GmailFailure.Forbidden, keepConnected = true)
                429 -> fail(GmailFailure.RateLimited, keepConnected = true)
                in 500..599 -> fail(GmailFailure.ServerError, keepConnected = true)
                else -> fail(GmailFailure.Unexpected, keepConnected = true)
            }
        }
    }

    /** Transient failures keep the "connected" flag so the screen offers Retry; grant failures clear it. */
    private fun fail(failure: GmailFailure, keepConnected: Boolean = false) {
        if (!keepConnected) store.connected = false
        _state.value = GmailState.Failed(failure)
    }
}
