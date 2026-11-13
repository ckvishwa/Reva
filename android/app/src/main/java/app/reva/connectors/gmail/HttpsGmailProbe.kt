package app.reva.connectors.gmail

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The connection check: one `users.messages.list` request with `maxResults=1`. `fields=resultSizeEstimate` asks Gmail
 * to leave message ids out of the answer, and the body is read only to free the connection and then dropped. Only
 * the HTTP status leaves this class. HTTPS to gmail.googleapis.com only; cleartext is refused app-wide.
 */
class HttpsGmailProbe(
    private val open: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
) : GmailProbe {
    override suspend fun listOneMessage(accessToken: String): ProbeResult = withContext(Dispatchers.IO) {
        val connection = try {
            open(URL(LIST_ONE_MESSAGE))
        } catch (_: IOException) {
            return@withContext ProbeResult.NetworkError
        }
        try {
            connection.requestMethod = "GET"
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            connection.setRequestProperty("Authorization", "Bearer $accessToken")
            connection.setRequestProperty("Accept", "application/json")
            val status = connection.responseCode
            drain(connection, status)
            ProbeResult.Http(status)
        } catch (_: IOException) {
            ProbeResult.NetworkError
        } finally {
            connection.disconnect()
        }
    }

    private fun drain(connection: HttpURLConnection, status: Int) {
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        stream?.use { input ->
            val buffer = ByteArray(1024)
            var total = 0
            while (total < MAX_DRAIN) {
                val read = input.read(buffer)
                if (read < 0) break
                total += read
            }
        }
    }

    companion object {
        const val LIST_ONE_MESSAGE =
            "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=1&fields=resultSizeEstimate"
        private const val TIMEOUT_MS = 15_000
        private const val MAX_DRAIN = 64 * 1024
    }
}
