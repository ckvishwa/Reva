package app.reva.brain

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject

data class HostedHttpResponse(val status: Int, val body: String)

fun interface HostedTransport {
    suspend fun send(key: String, body: String): HostedHttpResponse
}

/** Only the fixed Claude Messages endpoint is reachable. TLS uses the OS trust store; redirects are refused. */
class AnthropicTransport : HostedTransport {
    override suspend fun send(key: String, body: String): HostedHttpResponse = withContext(Dispatchers.IO) {
        val connection = URL("https://api.anthropic.com/v1/messages").openConnection() as HttpsURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = 8_000
            connection.readTimeout = 8_000
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("anthropic-version", "2023-06-01")
            connection.setRequestProperty("x-api-key", key)
            val bytes = body.toByteArray(Charsets.UTF_8)
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val output = ByteArrayOutputStream()
            stream?.use { input ->
                val buffer = ByteArray(4_096)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    output.write(buffer, 0, read)
                    if (output.size() > MAX_REPLY_BYTES) throw IOException("provider reply too large")
                }
            }
            HostedHttpResponse(status, output.toString(Charsets.UTF_8.name()))
        } finally {
            connection.disconnect()
        }
    }

    private companion object { const val MAX_REPLY_BYTES = 64 * 1024 }
}

/** Conservative local filter for the only data sent in C3b: a free-form question. Domain context, screen,
 * audio and Kernel rows are never placed in the payload. Ambiguous personal text stays local. */
object HostedTextGate {
    private val finance = Regex("(?i)\\b(bank|checking|savings|balance|credit|debt|loan|transfer|transaction|spent|spend|budget|money|dollars?|income|account|card|payment|invoice|rent|salary|expense)\\b|[\\$€£₹]\\s*\\d")
    private val memory = Regex("(?i)\\b(memory|remember|saved|private|note|sister|brother|wife|husband|family|address|password|secret|birthday|name)\\b|[\\w.+-]+@[\\w.-]+\\.[a-zA-Z]{2,}")
    private val personal = Regex("(?i)\\b(i|my|mine|our|ours|me)\\b")

    fun allowed(text: String, config: ModeConfig): Boolean =
        (!personal.containsMatchIn(text) || (config.financeConsent && config.memoryConsent)) &&
            (!finance.containsMatchIn(text) || config.financeConsent) &&
            (!memory.containsMatchIn(text) || config.memoryConsent)
}

/** Hosted reasoning is text-only. It cannot grant, approve, execute or verify an action. */
class HostedPlanner(
    private val modes: ModeController,
    private val key: () -> String?,
    private val transport: HostedTransport,
    private val timeoutMillis: Long = 7_000,
) : PlannerClient {
    override suspend fun answer(text: String): BrainResult {
        val config = modes.config()
        if (modes.state.value.mode != RunMode.Standalone || !config.hostedEnabled ||
            !config.financeConsent || !config.memoryConsent) {
            return BrainResult.Unknown("Hosted reasoning is off. Nothing was sent.")
        }
        if (text.length !in 1..500 || !HostedTextGate.allowed(text, config)) {
            return BrainResult.Unknown("This question stays on your phone because its domain is not allowed for cloud processing.")
        }
        val secret = try { withContext(Dispatchers.IO) { key()?.trim().orEmpty() } } catch (_: Exception) { "" }
        if (secret.isEmpty()) return BrainResult.Failure("The hosted model key is unavailable. Nothing was sent.")
        if (modes.state.value.mode != RunMode.Standalone || !modes.config().hostedEnabled ||
            !modes.config().financeConsent || !modes.config().memoryConsent) {
            return BrainResult.Unknown("Hosted reasoning was turned off. Nothing was sent.")
        }
        val body = JSONObject()
            .put("model", config.model)
            .put("max_tokens", 256)
            .put("system", SYSTEM)
            .put("messages", org.json.JSONArray().put(JSONObject().put("role", "user").put("content", text)))
            .toString()
        val response = try {
            withTimeout(timeoutMillis) { transport.send(secret, body) }
        } catch (_: TimeoutCancellationException) {
            modes.hostedTimedOut()
            return BrainResult.Unknown("Hosted reasoning timed out. Advanced reasoning is unavailable offline.")
        } catch (_: IOException) {
            modes.hostedTimedOut()
            return BrainResult.Unknown("Hosted reasoning is unreachable. Advanced reasoning is unavailable offline.")
        }
        if (modes.state.value.mode != RunMode.Standalone || !modes.config().hostedEnabled ||
            !modes.config().financeConsent || !modes.config().memoryConsent) {
            return BrainResult.Unknown("Hosted reasoning was turned off. The received answer was discarded.")
        }
        if (response.status !in 200..299) return BrainResult.Failure("The hosted model could not answer.")
        return try {
            val json = JSONObject(response.body)
            if (json.optString("stop_reason") != "end_turn") return BrainResult.Unknown("The hosted answer was incomplete.")
            val content = json.getJSONArray("content")
            if (content.length() != 1 || content.getJSONObject(0).optString("type") != "text") {
                return BrainResult.Unknown("The hosted answer was not plain text.")
            }
            val answer = content.getJSONObject(0).getString("text").trim()
            if (answer.isEmpty() || answer.length > 2_000 || ACTION_CLAIM.containsMatchIn(answer)) {
                BrainResult.Unknown("The hosted answer could not be verified. Nothing was changed.")
            } else BrainResult.Answer(answer, "Anthropic")
        } catch (_: Exception) {
            BrainResult.Unknown("The hosted answer could not be read.")
        }
    }

    private companion object {
        const val SYSTEM = "You are REVA. Answer in one to three short plain sentences. You cannot take actions, change data, or confirm an action succeeded. Say when you do not know."
        val ACTION_CLAIM = Regex("(?i)\\b(?:i|we)\\s+(?:have\\s+)?(?:opened|closed|saved|sent|paid|deleted|created|set|changed|completed)\\b|\\bdone[,!.]|\\b(?:is|has been)\\s+(?:open|closed|saved|sent|paid|deleted|created|set|changed|completed)\\b")
    }
}
