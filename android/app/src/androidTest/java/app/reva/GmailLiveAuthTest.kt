package app.reva

import android.content.Intent
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiScrollable
import androidx.test.uiautomator.UiSelector
import androidx.test.uiautomator.Until
import java.util.regex.Pattern
import org.junit.Assert.assertNotNull
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * CON-1 live check against real Google, opt-in only:
 *
 *   gradlew :app:connectedDebugAndroidTest -Preva.uiTests=true \
 *     -Pandroid.testInstrumentationRunnerArguments.class=app.reva.GmailLiveAuthTest \
 *     -Pandroid.testInstrumentationRunnerArguments.revaGmailLive=true
 *
 * Needs a device with Google Play services, network, and a Google account that is a test user of the REVA OAuth app.
 * It taps through Google's own account picker and consent screen, so it may need updating when Google changes them.
 * Runs in order: refuse consent, grant consent and reach Gmail (HTTP 200), then disconnect (revoke).
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class GmailLiveAuthTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val device = UiDevice.getInstance(instrumentation)
    private val pkg = "app.reva.android"

    @Before fun openGmailScreen() {
        assumeTrue("live Gmail test is opt-in", InstrumentationRegistry.getArguments().getString("revaGmailLive") == "true")
        val context = instrumentation.targetContext
        val launch = context.packageManager.getLaunchIntentForPackage(pkg)!!.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launch)
        assertNotNull(device.wait(Until.hasObject(By.pkg(pkg).depth(0)), 15_000))
        clickText("More")
        UiScrollable(UiSelector().scrollable(true)).scrollTextIntoView("Open Gmail")
        clickText("Open Gmail")
        assertNotNull("Gmail screen", device.wait(Until.findObject(By.textContains("read-only Gmail access")), 10_000))
    }

    @Test fun a_refusing_consent_reads_nothing_and_offers_connect_again() {
        disconnectIfConnected()
        clickText("Connect Gmail")
        chooseAccountIfAsked()
        // Google's consent screen: back out with Cancel.
        val cancel = waitAny(By.text(Pattern.compile("(?i)cancel")), 45_000)
        assertNotNull("Google's consent screen", cancel)
        cancel!!.click()
        assertNotNull(
            "denial is shown",
            device.wait(Until.findObject(By.text("Gmail access was not granted. Nothing was read.")), 20_000),
        )
    }

    @Test fun b_granting_consent_reaches_gmail_with_http_200() {
        if (device.findObject(By.text("Connect Gmail")) != null) clickText("Connect Gmail")
        chooseAccountIfAsked()
        val deadline = System.currentTimeMillis() + 90_000
        while (System.currentTimeMillis() < deadline) {
            if (device.findObject(By.text("Connected")) != null) break
            // Unverified-app notice, then the permission screen: each has a Continue or Allow button.
            device.findObject(By.text(Pattern.compile("(?i)continue|allow")))?.click()
            device.waitForIdle(1_000)
        }
        assertNotNull("Connected", device.wait(Until.findObject(By.text("Connected")), 10_000))
        assertNotNull(device.findObject(By.textContains("(HTTP 200)")))
    }

    @Test fun c_disconnect_revokes_and_shows_not_connected() {
        assumeTrue("needs the connection from b", device.wait(Until.findObject(By.text("Connected")), 30_000) != null)
        UiScrollable(UiSelector().scrollable(true)).scrollTextIntoView("Disconnect")
        clickText("Disconnect")
        assertNotNull(device.wait(Until.findObject(By.text("Not connected.")), 20_000))
    }

    private fun disconnectIfConnected() {
        if (device.wait(Until.findObject(By.text("Connected")), 8_000) != null) {
            UiScrollable(UiSelector().scrollable(true)).scrollTextIntoView("Disconnect")
            clickText("Disconnect")
            device.wait(Until.findObject(By.text("Not connected.")), 20_000)
        }
    }

    /** Google shows an account picker when the device has more than one account, or on first use. */
    private fun chooseAccountIfAsked() {
        val account = waitAny(By.textContains("@"), 15_000) ?: return
        if (account.applicationPackage != pkg) account.click()
    }

    private fun waitAny(selector: BySelector, timeoutMs: Long) = device.wait(Until.findObject(selector), timeoutMs)

    private fun clickText(text: String) {
        val node = device.wait(Until.findObject(By.text(text)), 10_000)
        assertNotNull("'$text' on screen", node)
        node!!.click()
        device.waitForIdle(1_000)
    }
}
