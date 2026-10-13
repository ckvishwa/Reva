package app.reva.sync

import java.math.BigInteger
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import org.json.JSONObject

/**
 * The pairing gateway's wire format, byte for byte what reva_core/gateway/protocol.py does. Pure Kotlin (no
 * Android classes) so JVM tests can check it against vectors written by the Python reference
 * (tools/android/gen_protocol_vectors.py). Nothing here does I/O.
 */
object GatewayProtocol {
    const val PROTOCOL = "REVA-GW1"
    const val QR_PREFIX = "REVA-PAIR1:"

    const val HEADER_DEVICE = "X-Reva-Device"
    const val HEADER_TIMESTAMP = "X-Reva-Ts"
    const val HEADER_NONCE = "X-Reva-Nonce"
    const val HEADER_SIGNATURE = "X-Reva-Sig"
    const val HEADER_RESPONSE_SIGNATURE = "X-Reva-Resp-Sig"

    private val CODE = Regex("^[A-Za-z0-9_-]{22,43}$")
    private val GATEWAY_HASH = Regex("^[0-9a-f]{64}$")

    fun b64u(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)

    fun b64uDecode(text: String): ByteArray {
        require(text.length <= 8192) { "not base64url" }
        return try {
            Base64.getUrlDecoder().decode(text)
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("not base64url", e)
        }
    }

    fun sha256(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(data)

    fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

    fun hexBytes(text: String): ByteArray = ByteArray(text.length / 2) { text.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    /** The pin and the fingerprint input: SHA-256 of a public key's SubjectPublicKeyInfo DER, hex. */
    fun spkiSha256(spkiDer: ByteArray): String = hex(sha256(spkiDer))

    fun pairStartMessage(code: String, gatewaySha256: String): ByteArray =
        "$PROTOCOL\npair-start\n$code\n$gatewaySha256".toByteArray()

    fun pairCompleteMessage(sessionId: String, nonce: String, gatewaySha256: String): ByteArray =
        "$PROTOCOL\npair-complete\n$sessionId\n$nonce\n$gatewaySha256".toByteArray()

    fun requestMessage(
        method: String,
        path: String,
        timestamp: Long,
        nonce: String,
        body: ByteArray,
        gatewaySha256: String,
    ): ByteArray =
        "$PROTOCOL\nrequest\n${method.uppercase()}\n$path\n$timestamp\n$nonce\n${hex(sha256(body))}\n$gatewaySha256".toByteArray()

    fun responseMessage(nonce: String, status: Int, body: ByteArray): ByteArray =
        "$PROTOCOL\nresponse\n$nonce\n$status\n${hex(sha256(body))}".toByteArray()

    /** The 6 digits both screens show: binds the gateway key, this phone's key and the session. */
    fun fingerprint(gatewaySha256: String, phoneSpkiDer: ByteArray, sessionId: String): String {
        val digest = sha256(
            "$PROTOCOL\nsas\n".toByteArray() + hexBytes(gatewaySha256) + "\n".toByteArray() + phoneSpkiDer +
                "\n".toByteArray() + sessionId.toByteArray(Charsets.US_ASCII),
        )
        val value = BigInteger(1, digest.copyOfRange(0, 8)).mod(BigInteger.valueOf(1_000_000)).toInt()
        return "%06d".format(value)
    }

    /** ECDSA P-256 / SHA-256 (DER signature) check with an SPKI DER public key. False on any problem. */
    fun verify(spkiDer: ByteArray, message: ByteArray, signatureDer: ByteArray): Boolean = try {
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(spkiDer))
        Signature.getInstance("SHA256withECDSA").run {
            initVerify(key)
            update(message)
            verify(signatureDer)
        }
    } catch (e: java.security.GeneralSecurityException) {
        false
    }

    /**
     * True only for addresses on this phone's own network: loopback, private IPv4 (10/8, 172.16/12, 192.168/16),
     * link-local, IPv6 loopback / unique-local / link-local, "localhost" and ".local" names. A pairing code that
     * points anywhere else is refused before any connection is made, so a hostile QR code cannot make the
     * phone talk to a server on the internet.
     */
    fun isLocalNetworkHost(host: String): Boolean {
        val name = host.trim().lowercase()
        if (name == "localhost" || (name.endsWith(".local") && name.length > ".local".length && name.all { it.isLetterOrDigit() || it == '.' || it == '-' })) return true
        val v4 = Regex("^(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})$").matchEntire(name)
        if (v4 != null) {
            val p = v4.groupValues.drop(1).map { it.toInt() }
            if (p.any { it > 255 }) return false
            return p[0] == 10 || p[0] == 127 || (p[0] == 172 && p[1] in 16..31) || (p[0] == 192 && p[1] == 168) || (p[0] == 169 && p[1] == 254)
        }
        if (name.contains(':') && name.all { it.isDigit() || it in 'a'..'f' || it == ':' || it == '.' }) {
            return try {
                val bytes = java.net.InetAddress.getByName(name).address // a literal: no DNS lookup
                bytes.size == 16 && (name == "::1" || (bytes[0].toInt() and 0xfe) == 0xfc || (bytes[0].toInt() and 0xff) == 0xfe && (bytes[1].toInt() and 0xc0) == 0x80)
            } catch (e: java.net.UnknownHostException) {
                false
            }
        }
        return false
    }

    // ---- the QR code (contracts/pairing-qr.schema.json) ----------------------------------------------

    data class QrPayload(val host: String, val port: Int, val code: String, val gatewaySha256: String, val expiresAt: Long)

    class BadQr(message: String) : Exception(message)

    fun parseQr(text: String): QrPayload {
        if (!text.startsWith(QR_PREFIX)) throw BadQr("This is not a REVA pairing code.")
        val json = try {
            JSONObject(String(b64uDecode(text.removePrefix(QR_PREFIX)), Charsets.UTF_8))
        } catch (e: Exception) {
            throw BadQr("This is not a REVA pairing code.")
        }
        val keys = json.keys().asSequence().toSet()
        if (keys != setOf("v", "host", "port", "code", "gw", "exp") || json.opt("v") != 1) {
            throw BadQr("This pairing code is from a different version of REVA.")
        }
        val port = (json.opt("port") as? Int) ?: throw BadQr("The pairing code is damaged.")
        val host = json.opt("host") as? String
        val code = json.opt("code") as? String
        val gw = json.opt("gw") as? String
        val exp = (json.opt("exp") as? Number)?.toLong()
        if (host.isNullOrEmpty() || host.length > 253 || port !in 1..65535 || code == null || !CODE.matches(code) ||
            gw == null || !GATEWAY_HASH.matches(gw) || exp == null || exp < 0
        ) {
            throw BadQr("The pairing code is damaged.")
        }
        return QrPayload(host, port, code, gw, exp)
    }
}
