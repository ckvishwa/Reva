package app.reva.avatar

import android.webkit.JavascriptInterface
import org.json.JSONException
import org.json.JSONObject

/** What the page may tell the app: it loaded, or it could not. Nothing else is ever acted on. */
sealed interface AvatarReport {
    data object Ready : AvatarReport
    data class Error(val detail: String) : AvatarReport

    companion object {
        const val MAX_DETAIL = 200

        /** Parses a page message; anything that is not exactly `avatar.ready` or `avatar.error` gives null. */
        fun parse(raw: String?): AvatarReport? {
            if (raw == null || raw.length > 1_000) return null
            val message = try {
                JSONObject(raw)
            } catch (_: JSONException) {
                return null
            }
            return when (message.optString("type")) {
                "avatar.ready" -> if (message.length() == 1) Ready else null
                "avatar.error" -> {
                    val keys = message.keys().asSequence().toSet()
                    if (!keys.all { it == "type" || it == "detail" }) return null
                    Error(message.optString("detail", "").take(MAX_DETAIL))
                }
                else -> null
            }
        }
    }
}

/**
 * The page's only way to reach the app (`window.RevaAvatarHost.postMessage`). It exposes one method, takes a string,
 * validates it with [AvatarReport.parse] and passes on only the two report kinds. It reads no files, starts nothing
 * and returns nothing.
 */
class AvatarHostBridge(private val onReport: (AvatarReport) -> Unit) {
    @JavascriptInterface
    fun postMessage(raw: String?) {
        AvatarReport.parse(raw)?.let(onReport)
    }
}
