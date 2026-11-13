package app.reva.connectors.gmail

import android.accounts.Account
import android.content.Context
import android.content.Intent
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.ClearTokenRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.auth.api.identity.RevokeAccessRequest
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.android.gms.common.api.ApiException
import com.google.android.gms.common.api.CommonStatusCodes
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Task
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * [GmailAuthorizer] on Google Identity Services' AuthorizationClient (play-services-auth). Android clients have no
 * client secret: Google matches the package name and signing certificate against the OAuth client in the REVA Cloud
 * project. Play services keeps the grant; REVA keeps only the account in memory, to be able to revoke it.
 */
class PlayServicesGmailAuthorizer(private val context: Context) : GmailAuthorizer {
    private val client get() = Identity.getAuthorizationClient(context)

    /** Set from the last granted result; used only for [revoke]. Never stored or logged. */
    @Volatile private var account: Account? = null

    private val request: AuthorizationRequest =
        AuthorizationRequest.builder().setRequestedScopes(listOf(Scope(GMAIL_READONLY))).build()

    override suspend fun authorize(): AuthStep {
        if (!playServicesReady()) return AuthStep.Failed(GmailFailure.PlayServicesUnavailable)
        return try {
            toStep(client.authorize(request).await())
        } catch (e: ApiException) {
            AuthStep.Failed(mapStatus(e.statusCode))
        }
    }

    override suspend fun fromConsentResult(data: Any?): AuthStep {
        val intent = data as? Intent ?: return AuthStep.Failed(GmailFailure.Denied)
        return try {
            toStep(client.getAuthorizationResultFromIntent(intent))
        } catch (e: ApiException) {
            AuthStep.Failed(mapStatus(e.statusCode))
        }
    }

    override suspend fun clearToken(accessToken: String) {
        client.clearToken(ClearTokenRequest.builder().setToken(accessToken).build()).await()
    }

    override suspend fun revoke(): Boolean {
        val target = account ?: (runCatching { authorize() }.getOrNull() as? AuthStep.Granted)?.let { account }
        if (target == null) return false
        val revoke = RevokeAccessRequest.builder().setAccount(target).setScopes(listOf(Scope(GMAIL_READONLY))).build()
        return runCatching { client.revokeAccess(revoke).await() }.isSuccess.also { if (it) account = null }
    }

    @Suppress("DEPRECATION") // toGoogleSignInAccount is the only way the result exposes the account to revoke.
    private fun toStep(result: AuthorizationResult): AuthStep {
        if (result.hasResolution()) {
            val pending = result.pendingIntent ?: return AuthStep.Failed(GmailFailure.Unexpected)
            return AuthStep.NeedsUser(pending)
        }
        val token = result.accessToken ?: return AuthStep.Failed(GmailFailure.Unexpected)
        result.toGoogleSignInAccount()?.account?.let { account = it }
        return AuthStep.Granted(token, result.grantedScopes.toSet())
    }

    private fun playServicesReady() =
        GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS

    private fun mapStatus(code: Int): GmailFailure = when (code) {
        CommonStatusCodes.NETWORK_ERROR, CommonStatusCodes.TIMEOUT -> GmailFailure.Network
        CommonStatusCodes.CANCELED -> GmailFailure.Denied
        CommonStatusCodes.SIGN_IN_REQUIRED, CommonStatusCodes.RESOLUTION_REQUIRED -> GmailFailure.ReconsentNeeded
        else -> GmailFailure.Unexpected
    }
}

private suspend fun <T> Task<T>.await(): T = suspendCancellableCoroutine { cont ->
    addOnSuccessListener { cont.resume(it) }
    addOnFailureListener { cont.resumeWithException(it) }
    addOnCanceledListener { cont.cancel() }
}
