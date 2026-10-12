package app.reva

import android.content.Context
import android.graphics.Bitmap
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.reva.data.AndroidKeystoreWrapper
import app.reva.data.KernelFinanceRepository
import app.reva.data.KeystoreKeyProvider
import app.reva.ui.RevaRoot
import app.reva.ui.theme.RevaTheme
import java.io.File
import java.io.FileOutputStream
import java.security.KeyStore
import java.time.LocalDate
import org.junit.After
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.openDomain

/**
 * Takes a screenshot of each screen with believable demo data, on a throw-away Finance file. Opt-in:
 *   ./gradlew :app:connectedDebugAndroidTest -Preva.uiTests=true -Pandroid.testInstrumentationRunnerArguments.screenshots=true
 *   adb pull /sdcard/Android/data/app.reva.android/files/screenshots
 * It never touches the Finance file you use: it has its own directory and key.
 */
@RunWith(AndroidJUnit4::class)
class ScreenshotTourTest {
    @get:Rule val rule = createComposeRule()
    private val context: Context = ApplicationProvider.getApplicationContext()
    private lateinit var root: File
    private lateinit var handle: DomainHandle

    private fun deleteKey() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.apply {
        if (containsAlias("reva.domain.finance")) deleteEntry("reva.domain.finance")
    }

    @Before fun setUp() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("screenshots") == "true")
        deleteKey()
        root = File(context.noBackupFilesDir, "tour-${System.nanoTime()}").also { it.mkdirs() }
        handle = openDomain("finance", KeystoreKeyProvider(File(root, "keys"), AndroidKeystoreWrapper()), File(root, "data").also { it.mkdirs() }.absolutePath)
    }

    @After fun tearDown() {
        if (::handle.isInitialized) handle.close()
        if (::root.isInitialized) root.deleteRecursively()
        deleteKey()
    }

    private fun seed() {
        val today = LocalDate.now()
        fun cmd(kind: String, json: String) = handle.command(kind, json)
        cmd("account.create", """{"id":"acct-checking","name":"Checking","kind":"checking","currency":"USD","opening_balance_minor":640500}""")
        cmd("account.create", """{"id":"acct-card-01","name":"Credit card","kind":"credit","currency":"USD","opening_balance_minor":-22849}""")
        cmd("account.create", """{"id":"acct-savings","name":"Savings","kind":"savings","currency":"USD","opening_balance_minor":1500000}""")
        for ((id, name, kind) in listOf(
            Triple("cat-dining-1", "Food · Dining", "expense"), Triple("cat-grocery", "Groceries", "expense"),
            Triple("cat-transport", "Transport", "expense"), Triple("cat-subs-01", "Subscriptions", "expense"),
            Triple("cat-fun-0001", "Fun", "expense"), Triple("cat-income-1", "Income", "income"),
        )) cmd("category.create", """{"id":"$id","name":"$name","kind":"$kind"}""")
        val first = today.withDayOfMonth(1).toString().substring(0, 7)
        for ((cat, amount) in listOf("cat-dining-1" to 40_000, "cat-grocery" to 60_000, "cat-transport" to 20_000, "cat-subs-01" to 15_000, "cat-fun-0001" to 8_000)) {
            cmd("budget.set", """{"id":"bud-$cat","category_id":"$cat","amount_minor":$amount,"currency":"USD","start_month":"$first"}""")
        }
        fun day(back: Long) = today.minusDays(back).let { if (it.month != today.month) today.withDayOfMonth(1) else it }.toString()
        for ((back, acct, amount, desc, cat) in listOf(
            listOf(0L, "acct-card-01", -1_200L, "Lunch", "cat-dining-1"), listOf(1L, "acct-card-01", -8_450L, "Corner Market", "cat-grocery"),
            listOf(2L, "acct-checking", -2_300L, "Metro card", "cat-transport"), listOf(3L, "acct-card-01", -14_000L, "Streaming + cloud", "cat-subs-01"),
            listOf(4L, "acct-card-01", -7_200L, "Cinema", "cat-fun-0001"), listOf(5L, "acct-card-01", -36_500L, "Dinner out", "cat-dining-1"),
            listOf(6L, "acct-checking", 300_000L, "Paycheck", "cat-income-1"),
        )) {
            cmd("transaction.create", """{"account_id":"$acct","date":"${day(back as Long)}","amount_minor":$amount,"description":"$desc","category":"$cat"}""")
        }
        for ((id, name, amount, plus, kind) in listOf(
            listOf("bill-rent-01", "Rent", 120_000, 2, "bill"), listOf("bill-phone-1", "Phone", 4_500, 6, "bill"),
            listOf("bill-net-001", "Internet", 6_000, 9, "bill"), listOf("bill-stream-1", "Streaming", 1_500, 20, "subscription"),
        )) {
            cmd("bill.create", """{"id":"$id","name":"$name","amount_minor":$amount,"currency":"USD","recurrence":"monthly","due_date":"${today.plusDays((plus as Int).toLong())}","kind":"$kind"}""")
        }
        cmd("networth_snapshot.create", """{"as_of":"$today"}""")
    }

    private fun shot(name: String) {
        InstrumentationRegistry.getInstrumentation().waitForIdleSync()
        Thread.sleep(700)
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
        val dir = File(context.getExternalFilesDir(null), "screenshots").also { it.mkdirs() }
        FileOutputStream(File(dir, "$name.png")).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun tour() {
        seed()
        val repository = KernelFinanceRepository(openHandle = { handle })
        rule.setContent { RevaTheme { RevaRoot(repository, "0.1.0", onShare = { _, _ -> }) } }
        rule.waitUntil(15_000) { rule.onAllNodesWithTag("today_budget_left", useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        shot("1-today")

        rule.onNodeWithTag("tab_finance").performClick()
        rule.waitUntil(15_000) { rule.onAllNodesWithTag("finance_list").fetchSemanticsNodes().isNotEmpty() }
        Thread.sleep(1_500)
        shot("2-finance-top")
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Budgets · this month"))
        shot("3-finance-budgets")
        rule.onNodeWithTag("finance_list").performScrollToNode(hasText("Recent transactions"))
        shot("4-finance-transactions")
        rule.onNodeWithTag("finance_list").performScrollToNode(hasTestTag("no_money_note"))
        shot("5-finance-note")

        rule.onNodeWithTag("finance_list").performScrollToNode(hasTestTag("add_transaction"))
        rule.onNodeWithTag("add_transaction").performClick()
        rule.waitUntil(10_000) { rule.onAllNodesWithTag("tx_amount").fetchSemanticsNodes().isNotEmpty() }
        shot("6-add-transaction")
        rule.onNodeWithTag("tx_cancel").performClick()

        rule.onNodeWithTag("tab_talk").performClick()
        shot("7-talk")
        rule.onNodeWithTag("tab_more").performClick()
        shot("8-more")
    }
}
