package app.reva.pcrequests

import app.reva.sync.GatewayProtocol
import app.reva.sync.GatewayTarget
import app.reva.sync.GatewayTransport
import app.reva.sync.PairedPc
import java.io.IOException
import java.security.SecureRandom
import org.json.JSONException
import org.json.JSONObject

/**
 * Signs a request to the PC. Only the signing operation, not the Kernel's `DeviceSigner` type itself: this
 * package must not import the Kernel binding directly (`tests/security/test_import_graph.py`), so `RevaApp.kt`,
 * which is already allowed to, adapts the phone's real `KeystoreDeviceSigner` to this. Throws [SigningUnavailable]
 * when the key cannot be used.
 */
fun interface RequestSigner {
    fun sign(message: ByteArray): ByteArray
}

class SigningUnavailable(message: String) : Exception(message)

/** What the PC says about one request. Words in [speak] and [prompt] are the PC's templates. */
data class PcReply(
    val requestId: String,
    val capability: String,
    val tier: String,
    /** awaiting_approval, granted, attempted, observed, verified, failed, unknown, denied, expired, refused. */
    val status: String,
    val reason: String,
    val speak: String?,
    val prompt: String?,
    val deadline: String?,
)

enum class PcFailure {
    /** The PC could not be reached, or the answer never arrived: the request may or may not have landed. */
    Unreachable,

    /** The PC no longer accepts this phone (revoked or removed). */
    Unauthorized,

    /** The owner has not allowed this phone to ask for that on the PC. */
    OutOfScope,

    /** The phone asked for something the PC never accepts from a phone. */
    NotAllowed,

    /** The request sat too long (over 120 seconds) and the PC refused to act late. */
    Expired,

    /** This phone already has too many requests open on the PC. */
    TooMany,

    /** The PC is up but not ready (the action broker is unavailable). */
    Unavailable,

    /** The answer was not signed by the paired PC, or was not understood. Nothing from it is believed. */
    BadAnswer,

    /** The PC does not know that request. */
    UnknownRequest,

    Other,
}

class PcException(val failure: PcFailure, override val message: String) : Exception(message)

/** Where requests go. The real one signs and checks answers; tests use a fake. Blocking: callers use IO. */
interface PcGateway {
    fun propose(pc: PairedPc, requestId: String, capability: String, args: Map<String, Any?>, issuedAt: Long): PcReply

    fun status(pc: PairedPc, requestId: String): PcReply
}

/**
 * Signed requests to the PC's gateway (`POST /actions/propose`, `POST /actions/status`), exactly like sync
 * requests: ECDSA over method, path, timestamp, nonce, body hash and the pinned gateway key, with the PC's answer
 * checked against the PC's signing key. An answer that is not signed by the paired PC is never believed.
 */
class SignedPcGateway(
    private val signer: RequestSigner,
    private val transport: GatewayTransport,
    private val clockSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) : PcGateway {
    private val random = SecureRandom()

    override fun propose(pc: PairedPc, requestId: String, capability: String, args: Map<String, Any?>, issuedAt: Long): PcReply {
        val body = JSONObject()
            .put("request_id", requestId)
            .put("capability", capability)
            .put("args", JSONObject(args))
            .put("issued_at", issuedAt)
        return reply(post(pc, "/actions/propose", body))
    }

    override fun status(pc: PairedPc, requestId: String): PcReply =
        reply(post(pc, "/actions/status", JSONObject().put("request_id", requestId)))

    private fun post(pc: PairedPc, path: String, json: JSONObject): JSONObject {
        val body = json.toString().toByteArray()
        val nonce = GatewayProtocol.b64u(ByteArray(16).also(random::nextBytes))
        val timestamp = clockSeconds()
        val signature = try {
            signer.sign(GatewayProtocol.requestMessage("POST", path, timestamp, nonce, body, pc.tlsSha256))
        } catch (e: SigningUnavailable) {
            throw PcException(PcFailure.Other, "This phone's device key is not available.")
        }
        val headers = mapOf(
            GatewayProtocol.HEADER_DEVICE to pc.deviceId,
            GatewayProtocol.HEADER_TIMESTAMP to timestamp.toString(),
            GatewayProtocol.HEADER_NONCE to nonce,
            GatewayProtocol.HEADER_SIGNATURE to GatewayProtocol.b64u(signature),
        )
        val answer = try {
            transport.post(GatewayTarget(pc.host, pc.port, pc.tlsSha256), path, headers, body)
        } catch (e: IOException) {
            throw PcException(PcFailure.Unreachable, "Could not reach your PC.")
        }
        if (answer.status != 200) throw refusal(answer.status, answer.body)
        val sent = answer.headers[GatewayProtocol.HEADER_RESPONSE_SIGNATURE.lowercase()]
        val genuine = sent != null && try {
            GatewayProtocol.verify(pc.pcSigningKey, GatewayProtocol.responseMessage(nonce, answer.status, answer.body), GatewayProtocol.b64uDecode(sent))
        } catch (e: IllegalArgumentException) {
            false
        }
        if (!genuine) throw PcException(PcFailure.BadAnswer, "The answer did not come from your paired PC. I did not believe it.")
        return try {
            JSONObject(String(answer.body, Charsets.UTF_8))
        } catch (e: JSONException) {
            throw PcException(PcFailure.BadAnswer, "The PC gave an answer I do not understand.")
        }
    }

    private fun refusal(status: Int, body: ByteArray): PcException {
        val code = try {
            JSONObject(String(body, Charsets.UTF_8)).optString("error")
        } catch (e: JSONException) {
            ""
        }
        return when {
            status == 401 -> PcException(PcFailure.Unauthorized, "Your PC no longer accepts this phone. Pair again.")
            code == "out_of_scope" -> PcException(PcFailure.OutOfScope, "Your PC has not allowed this phone to do that. Allow it on the PC, in Devices.")
            code == "capability_not_allowed" -> PcException(PcFailure.NotAllowed, "A phone may not ask your PC to do that.")
            code == "request_expired" || status == 410 -> PcException(PcFailure.Expired, "That request waited too long, so the PC did not do it.")
            code == "unknown_request" || status == 404 -> PcException(PcFailure.UnknownRequest, "Your PC does not know that request.")
            status == 429 -> PcException(PcFailure.TooMany, "Too many requests are waiting on your PC.")
            status == 503 -> PcException(PcFailure.Unavailable, "Your PC cannot take requests right now.")
            else -> PcException(PcFailure.Other, "Your PC could not take the request (code $status).")
        }
    }

    private fun reply(json: JSONObject): PcReply {
        fun text(name: String): String? = if (json.isNull(name)) null else json.optString(name).takeIf { it.isNotEmpty() }
        val id = text("request_id")
        val status = text("status")
        if (id == null || status == null) throw PcException(PcFailure.BadAnswer, "The PC gave an answer I do not understand.")
        return PcReply(id, text("capability").orEmpty(), text("tier").orEmpty(), status, text("reason").orEmpty(), text("speak"), text("prompt"), text("deadline"))
    }
}
