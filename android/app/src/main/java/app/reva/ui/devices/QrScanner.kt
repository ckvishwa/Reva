package app.reva.ui.devices

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Reads the pairing QR code with the camera. On-device only: CameraX shows the preview and ZXing (a plain
 * Java library, no Google Play services) decodes frames; nothing is recorded, saved or sent. The camera
 * permission is asked for here, when the user taps "Scan", and only then.
 */
@Composable
fun QrScanner(onCode: (String) -> Unit, onCancel: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    var asked by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) {
        if (!granted && !asked) {
            asked = true
            launcher.launch(Manifest.permission.CAMERA)
        }
    }
    Column(modifier.fillMaxSize().padding(16.dp).testTag("qr_scanner"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionTitle("Scan the code on your PC")
        if (granted) {
            MutedText("Point the camera at the QR code in REVA on your PC (Devices, then Pair a phone).")
            CameraPreview(onCode, Modifier.fillMaxWidth().height(360.dp))
        } else {
            MutedText("REVA needs the camera only to read the pairing code. It does not record or keep any picture.")
            PrimaryButton("Allow the camera", { launcher.launch(Manifest.permission.CAMERA) })
        }
        SecondaryButton("Cancel", onCancel, Modifier.testTag("qr_cancel"))
    }
}

@Composable
private fun CameraPreview(onCode: (String) -> Unit, modifier: Modifier) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val done = remember { AtomicBoolean(false) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val previewView = remember { PreviewView(context) }
    DisposableEffect(lifecycleOwner) {
        val providerFuture = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        providerFuture.addListener({
            val cameraProvider = providerFuture.get()
            provider = cameraProvider
            val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
            val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
            analysis.setAnalyzer(executor) { image ->
                val text = decode(image)
                if (text != null && done.compareAndSet(false, true)) {
                    previewView.post { onCode(text) }
                }
            }
            cameraProvider.unbindAll()
            cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            provider?.unbindAll()
            executor.shutdown()
        }
    }
    AndroidView(factory = { previewView }, modifier = modifier.testTag("camera_preview"))
}

private val reader = QRCodeReader()
private val hints = mapOf(DecodeHintType.TRY_HARDER to true, DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE))

/** Decodes one camera frame (luminance plane only). Null if there is no readable QR code in it. */
private fun decode(image: ImageProxy): String? = image.use { frame ->
    try {
        val plane = frame.planes[0]
        val buffer = plane.buffer
        val data = ByteArray(buffer.remaining()).also { buffer.get(it) }
        val rowStride = plane.rowStride
        val source = PlanarYUVLuminanceSource(data, rowStride, frame.height, 0, 0, frame.width, frame.height, false)
        reader.decode(BinaryBitmap(HybridBinarizer(source)), hints).text
    } catch (e: com.google.zxing.ReaderException) {
        null
    } catch (e: RuntimeException) {
        null
    } finally {
        reader.reset()
    }
}
