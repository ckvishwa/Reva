package app.reva.avatar

import android.os.Looper
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AvatarBridgeThreadTest {
    @Test fun javascript_report_is_delivered_on_the_ui_thread() {
        val delivered = CountDownLatch(1)
        val onUiThread = AtomicBoolean(false)
        val bridge = AvatarHostBridge {
            onUiThread.set(Looper.myLooper() == Looper.getMainLooper())
            delivered.countDown()
        }

        Thread { bridge.postMessage("""{"type":"avatar.ready"}""") }.start()

        assertTrue("the bridge did not deliver the report", delivered.await(5, TimeUnit.SECONDS))
        assertTrue("the bridge delivered off the UI thread", onUiThread.get())
    }
}
