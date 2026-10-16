package app.reva.ui.talk

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.webkit.WebViewAssetLoader
import app.reva.avatar.AvatarDriver
import app.reva.avatar.AvatarHostBridge
import app.reva.avatar.AvatarReport
import app.reva.avatar.AvatarSink
import app.reva.voice.VoiceController
import java.io.ByteArrayInputStream

private const val HOST = "appassets.androidplatform.net"
private const val PAGE = "https://$HOST/assets/avatar/index.html?model=placeholder.vrm"

/**
 * The avatar page in a WebView that can reach nothing but the app's own files:
 *  - the page and the model are served from the APK's assets through [WebViewAssetLoader] (no file:// access);
 *  - every other request, including any attempt to leave the page, is blocked;
 *  - the only JavaScript interface is [AvatarHostBridge]: one method that accepts the page's "ready" or "error"
 *    report and nothing else;
 *  - the WebView is paused when the app leaves the screen and destroyed when this view leaves the composition.
 * Messages go in only through [AvatarDriver], which builds them with [app.reva.avatar.AvatarProtocol].
 */
@SuppressLint("SetJavaScriptEnabled") // the avatar is a script; it is local, offline and has no bridge
@Composable
fun AvatarView(controller: VoiceController, enabled: Boolean, modifier: Modifier = Modifier, height: Dp = 220.dp) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    var loadFailed by remember { mutableStateOf(false) }
    // Messages sent before the page has loaded would be lost, so they wait here and go out in order on load.
    val pending = remember { ArrayList<String>() }
    var pageReady by remember { mutableStateOf(false) }
    val webView = remember { createAvatarWebView(context, onFailed = { loadFailed = true }, onLoaded = { pageReady = true }) }
    val ui by controller.ui.collectAsState()

    val driver = remember(webView) {
        AvatarDriver(
            AvatarSink { json ->
                if (pageReady) {
                    webView.evaluateJavascript("window.revaAvatar&&window.revaAvatar.handle($json)", null)
                } else if (!json.contains("avatar.mouth") && pending.size < 32) {
                    pending += json // a mouth reading is stale by the time the page is ready; the rest is not
                }
            },
        )
    }

    LaunchedEffect(pageReady) {
        if (pageReady) {
            pending.forEach { webView.evaluateJavascript("window.revaAvatar&&window.revaAvatar.handle($it)", null) }
            pending.clear()
        }
    }
    LaunchedEffect(driver, enabled) { driver.onSettings(enabled = enabled, reducedMotion = reducedMotion(context), quality = "medium") }
    LaunchedEffect(driver, ui) { driver.onUi(ui) }
    LaunchedEffect(driver, controller) { controller.levels.collect(driver::onLevel) }

    DisposableEffect(lifecycle, webView) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_PAUSE -> webView.onPause()
                Lifecycle.Event.ON_RESUME -> webView.onResume()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            webView.stopLoading()
            webView.loadUrl("about:blank")
            webView.removeAllViews()
            webView.destroy()
        }
    }

    if (enabled && !loadFailed) {
        AndroidView(
            factory = { webView },
            modifier = modifier.fillMaxWidth().height(height).testTag("talk_avatar")
                .semantics { contentDescription = "REVA avatar, ${AvatarDriver.stateFor(ui)}" },
        )
    }
}

private fun reducedMotion(context: Context): Boolean =
    android.provider.Settings.Global.getFloat(context.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f

@SuppressLint("SetJavaScriptEnabled")
private fun createAvatarWebView(context: Context, onFailed: () -> Unit, onLoaded: () -> Unit): WebView {
    val ui = Handler(Looper.getMainLooper())
    val loader = WebViewAssetLoader.Builder()
        .setDomain(HOST)
        .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(context))
        .build()
    return WebView(context).apply {
        setBackgroundColor(0)
        settings.apply {
            javaScriptEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            domStorageEnabled = false
            databaseEnabled = false
            blockNetworkLoads = true
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            mediaPlaybackRequiresUserGesture = true
            setGeolocationEnabled(false)
            cacheMode = WebSettings.LOAD_NO_CACHE
        }
        webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse {
                val local = loader.shouldInterceptRequest(request.url)
                if (local != null && request.url.host == HOST) return local
                if (request.isForMainFrame) ui.post { onFailed() }
                return WebResourceResponse("text/plain", "utf-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
            }

            override fun onPageFinished(view: WebView, url: String?) {
                if (url == PAGE) onLoaded()
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = true

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
                if (request.isForMainFrame) onFailed()
            }

            override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, errorResponse: WebResourceResponse) {
                if (request.isForMainFrame) onFailed() // the page is missing from this build
            }
        }
        addJavascriptInterface(
            AvatarHostBridge { report ->
                android.util.Log.i("RevaAvatar", report.toString())
                if (report is AvatarReport.Error) onFailed()
            },
            "RevaAvatarHost",
        )
        loadUrl(PAGE)
    }
}
