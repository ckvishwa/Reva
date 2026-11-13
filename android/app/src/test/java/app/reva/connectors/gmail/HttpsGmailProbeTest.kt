package app.reva.connectors.gmail

import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** CON-1: the connection check's request shape and status handling, with no network. */
class HttpsGmailProbeTest {
    private class FakeConnection(url: URL, private val status: Int, private val failOnStatus: Boolean = false) : HttpURLConnection(url) {
        val headers = mutableMapOf<String, String>()
        var disconnected = false
        var bodyRead = false
        override fun setRequestProperty(key: String, value: String) { headers[key] = value }
        override fun getResponseCode(): Int = if (failOnStatus) throw IOException("offline") else status
        override fun getInputStream(): InputStream { bodyRead = true; return ByteArrayInputStream("""{"resultSizeEstimate":1}""".toByteArray()) }
        override fun getErrorStream(): InputStream = ByteArrayInputStream("""{"error":{}}""".toByteArray())
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun connect() = Unit
    }

    @Test fun it_lists_at_most_one_message_over_https_and_asks_for_no_message_ids() {
        val url = URL(HttpsGmailProbe.LIST_ONE_MESSAGE)
        assertEquals("https", url.protocol)
        assertEquals("gmail.googleapis.com", url.host)
        assertEquals("/gmail/v1/users/me/messages", url.path)
        assertEquals(setOf("maxResults=1", "fields=resultSizeEstimate"), url.query.split('&').toSet())
    }

    @Test fun it_sends_the_token_as_a_bearer_header_with_a_get_and_returns_only_the_status() = runTest {
        var opened: FakeConnection? = null
        val probe = HttpsGmailProbe { u -> FakeConnection(u, 200).also { opened = it } }
        assertEquals(ProbeResult.Http(200), probe.listOneMessage("tok"))
        val c = opened!!
        assertEquals("GET", c.requestMethod)
        assertEquals("Bearer tok", c.headers["Authorization"])
        assertFalse(c.instanceFollowRedirects)
        assertTrue(c.bodyRead)
        assertTrue(c.disconnected)
    }

    @Test fun error_statuses_are_reported_as_they_are() = runTest {
        for (status in listOf(401, 403, 429, 500)) {
            assertEquals(ProbeResult.Http(status), HttpsGmailProbe { u -> FakeConnection(u, status) }.listOneMessage("t"))
        }
    }

    @Test fun io_failures_are_a_network_error() = runTest {
        assertEquals(ProbeResult.NetworkError, HttpsGmailProbe { u -> FakeConnection(u, 0, failOnStatus = true) }.listOneMessage("t"))
        assertEquals(ProbeResult.NetworkError, HttpsGmailProbe { throw IOException("no route") }.listOneMessage("t"))
    }
}
