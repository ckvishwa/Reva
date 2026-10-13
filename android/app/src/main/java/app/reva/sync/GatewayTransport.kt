package app.reva.sync

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.URL
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** Where the PC's gateway is, and the TLS key it must have (SHA-256 of its public key, from the QR code). */
data class GatewayTarget(val host: String, val port: Int, val tlsSha256: String)

class HttpReply(val status: Int, val headers: Map<String, String>, val body: ByteArray)

/**
 * One HTTPS POST to the gateway. Blocking: callers use Dispatchers.IO. Throws [IOException] if the PC cannot
 * be reached (or presents the wrong key).
 */
interface GatewayTransport {
    fun post(target: GatewayTarget, path: String, headers: Map<String, String>, body: ByteArray): HttpReply
}

/**
 * HTTPS with the server key pinned. The gateway's certificate is self-signed on purpose; the only thing that
 * counts is that its public key hashes to the value in the QR code. A different key is refused during the
 * handshake, before any request bytes are sent. This is never a trust-all manager: it accepts exactly one key.
 */
class PinnedHttpsTransport(
    private val connectTimeoutMillis: Int = 10_000,
    private val readTimeoutMillis: Int = 30_000,
) : GatewayTransport {

    override fun post(target: GatewayTarget, path: String, headers: Map<String, String>, body: ByteArray): HttpReply {
        val context = SSLContext.getInstance("TLS").apply { init(null, arrayOf(PinnedTrustManager(target.tlsSha256)), null) }
        val connection = URL("https", target.host, target.port, path).openConnection() as HttpsURLConnection
        try {
            connection.sslSocketFactory = context.socketFactory
            // The certificate has no host name to match: its key, pinned above, is the identity.
            connection.hostnameVerifier = HostnameVerifier { _, _ -> true }
            connection.requestMethod = "POST"
            connection.connectTimeout = connectTimeoutMillis
            connection.readTimeout = readTimeoutMillis
            connection.useCaches = false
            connection.instanceFollowRedirects = false
            connection.doOutput = true
            connection.setFixedLengthStreamingMode(body.size)
            connection.setRequestProperty("Content-Type", "application/json")
            headers.forEach { (k, v) -> connection.setRequestProperty(k, v) }
            connection.outputStream.use { it.write(body) }
            val status = connection.responseCode
            val stream = if (status < 400) connection.inputStream else connection.errorStream
            val bytes = stream?.use { readLimited(it) } ?: ByteArray(0)
            val reply = connection.headerFields.filterKeys { it != null }.mapKeys { it.key.lowercase() }.mapValues { it.value.first() }
            return HttpReply(status, reply, bytes)
        } finally {
            connection.disconnect()
        }
    }

    private fun readLimited(stream: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(16 * 1024)
        while (true) {
            val read = stream.read(buffer)
            if (read < 0) break
            out.write(buffer, 0, read)
            if (out.size() > MAX_REPLY_BYTES) throw IOException("the PC's answer is too large")
        }
        return out.toByteArray()
    }

    private class PinnedTrustManager(private val pinSha256: String) : X509TrustManager {
        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val leaf = chain?.firstOrNull() ?: throw CertificateException("no certificate")
            val actual = GatewayProtocol.sha256(leaf.publicKey.encoded)
            if (!MessageDigest.isEqual(actual, GatewayProtocol.hexBytes(pinSha256))) {
                throw CertificateException("the gateway's key is not the one in the pairing code")
            }
        }

        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            throw CertificateException("client certificates are not used")
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    private companion object {
        const val MAX_REPLY_BYTES = 12 * 1024 * 1024
    }
}
