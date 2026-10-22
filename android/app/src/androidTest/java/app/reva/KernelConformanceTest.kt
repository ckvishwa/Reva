package app.reva

import android.content.Context
import android.net.ConnectivityManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.reva.data.AndroidKeystoreWrapper
import app.reva.data.KeystoreKeyProvider
import java.io.File
import java.security.KeyStore
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import uniffi.reva_kernel.DomainException
import uniffi.reva_kernel.DomainHandle
import uniffi.reva_kernel.KeyProviderException
import uniffi.reva_kernel.openDomain
import uniffi.reva_kernel.today

/**
 * The Domain Kernel's shared Finance conformance suite (the same kernel/tests/conformance/finance.json the
 * Rust, Python and JVM runners use), run through the Kotlin binding and libreva_kernel.so ON THE DEVICE with
 * the REAL Android Keystore key provider. Run it in airplane mode: [the_device_is_offline_when_the_suite_runs]
 * asserts that. (Since SYNC-1d the app holds INTERNET for LAN sync with the user's own PC, so the proof of
 * "nothing leaves the phone" is airplane mode plus the fact that the Kernel itself has no network code.)
 */
@RunWith(AndroidJUnit4::class)
class KernelConformanceTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private lateinit var root: File
    private val roots = mutableListOf<File>()

    @Before fun setUp() {
        deleteWrappingKey()
        root = newRoot()
    }

    @After fun tearDown() {
        roots.forEach { it.deleteRecursively() }
        deleteWrappingKey()
    }

    private fun newRoot(): File = File(context.noBackupFilesDir, "conformance-${System.nanoTime()}").also {
        it.mkdirs()
        roots += it
    }

    private fun deleteWrappingKey() {
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.apply {
            if (containsAlias("reva.domain.finance")) deleteEntry("reva.domain.finance")
        }
    }

    private fun open(dir: File): DomainHandle =
        openDomain("finance", KeystoreKeyProvider(File(dir, "keys"), AndroidKeystoreWrapper()), File(dir, "data").also { it.mkdirs() }.absolutePath)

    // ---- the suite --------------------------------------------------------------------------------

    private class StepFailure(message: String) : Exception(message)

    private val forbidden = setOf("pay", "payment", "transfer", "send", "withdraw", "purchase", "buy", "wire", "ach", "login", "credential", "password", "bank")
    private val volatile = setOf("version", "created_at", "updated_at")

    private fun codeOf(e: Throwable): String = when (e) {
        is DomainException.Locked -> "locked"
        is DomainException.WrongKey -> "wrong_key"
        is DomainException.Corrupt -> "corrupt"
        is DomainException.MigrationFailed -> "migration_failed"
        is DomainException.Validation -> "validation"
        is DomainException.Conflict -> "conflict"
        is DomainException.NotFound -> "not_found"
        is DomainException.Deleted -> "deleted"
        is DomainException.Internal -> "internal"
        else -> "unexpected:" + e::class.simpleName
    }

    private fun same(expected: Any?, actual: Any?): Boolean {
        val e = if (expected == JSONObject.NULL) null else expected
        val a = if (actual == JSONObject.NULL) null else actual
        if (e is Number && a is Number) {
            return if (e.toDouble() == e.toLong().toDouble() && a.toDouble() == a.toLong().toDouble()) e.toLong() == a.toLong() else e.toDouble() == a.toDouble()
        }
        return e == a
    }

    private fun subset(expected: Any?, actual: Any?, path: String) {
        when (expected) {
            is JSONObject -> {
                if (actual !is JSONObject) throw StepFailure("$path: expected object, got $actual")
                for (key in expected.keys()) {
                    if (!actual.has(key)) throw StepFailure("$path.$key: missing in $actual")
                    subset(expected.get(key), actual.get(key), "$path.$key")
                }
            }
            is JSONArray -> {
                if (actual !is JSONArray || actual.length() != expected.length()) throw StepFailure("$path: expected ${expected.length()} items, got $actual")
                for (i in 0 until expected.length()) subset(expected.get(i), actual.get(i), "$path[$i]")
            }
            else -> if (!same(expected, actual)) throw StepFailure("$path: expected $expected, got $actual")
        }
    }

    private fun strip(value: Any?): Any? = when (value) {
        is JSONObject -> JSONObject().also { out -> value.keys().asSequence().sorted().forEach { k -> if (k !in volatile) out.put(k, strip(value.get(k))) } }
        is JSONArray -> JSONArray().also { out -> for (i in 0 until value.length()) out.put(strip(value.get(i))) }
        else -> value
    }

    private inner class Runner {
        var handle: DomainHandle = open(root)

        private fun <T> attempt(block: () -> T): Pair<T?, Throwable?> = try { Pair(block(), null) } catch (e: DomainException) { Pair(null, e) }

        private fun expectError(step: JSONObject, label: String, error: Throwable?): Boolean {
            val want = step.optString("expect_error", "")
            if (want.isNotEmpty()) {
                if (error == null) throw StepFailure("$label: expected error $want, but it succeeded")
                val got = codeOf(error)
                if (got != want) throw StepFailure("$label: expected error $want, got $got ($error)")
                return true
            }
            if (error != null) throw StepFailure("$label: unexpected error $error")
            return false
        }

        private fun listRows(h: DomainHandle, name: String): Any? =
            strip(JSONArray(h.query(name, if (name == "list_transactions") """{"limit": 1000}""" else "{}").rowsJson))

        fun runStep(step: JSONObject, index: Int) {
            val op = step.getString("op")
            val label = "step $index ($op ${step.optString("kind", step.optString("name", ""))})"
            val h = handle
            when (op) {
                "command" -> {
                    val (result, error) = attempt { h.command(step.getString("kind"), step.getJSONObject("payload").toString()) }
                    if (expectError(step, label, error)) return
                    if (step.has("expect")) {
                        val actual = JSONObject().put("event_id", result!!.eventId).put("aggregate_id", result.aggregateId).put("version", result.version)
                        subset(step.get("expect"), actual, label)
                    }
                }
                "query" -> {
                    val (result, error) = attempt { h.query(step.getString("name"), step.getJSONObject("params").toString()) }
                    if (expectError(step, label, error)) return
                    if (step.has("expect_rows")) subset(step.get("expect_rows"), JSONArray(result!!.rowsJson), label)
                    if (step.has("expect_source_ids_sorted")) subset(step.get("expect_source_ids_sorted"), JSONArray(result!!.sourceIds.sorted()), label)
                }
                "today" -> subset(step.get("expect"), JSONObject(today(listOf(h), if (step.has("as_of")) step.getString("as_of") else null)), label)
                "import", "import_error" -> {
                    val beforeEvents = h.eventCount()
                    val beforeDigest = h.projectionDigest()
                    val (result, error) = attempt {
                        h.importData(step.getString("format"), step.getString("data").toByteArray(Charsets.UTF_8), step.getJSONObject("options").toString())
                    }
                    if (op == "import_error") {
                        if (!expectError(step, label, error)) throw StepFailure("$label: import_error needs expect_error")
                    } else {
                        if (error != null) throw StepFailure("$label: $error")
                        val r = result!!
                        val rejected = JSONArray()
                        for (x in r.rejected) rejected.put(JSONObject().put("row", x.row.toLong()).put("reason", x.reason))
                        val actual = JSONObject().put("accepted", r.accepted.toLong()).put("duplicates", r.duplicates.toLong()).put("dry_run", r.dryRun).put("rejected", rejected)
                        subset(step.get("expect"), actual, label)
                        if (JSONArray(r.rowsJson).length().toLong() != r.accepted.toLong() + r.duplicates.toLong() + r.rejected.size) throw StepFailure("$label: row report incomplete")
                    }
                    if (step.optBoolean("check_unchanged", false) || op == "import_error") {
                        if (h.eventCount() != beforeEvents || h.projectionDigest() != beforeDigest) throw StepFailure("$label: state changed but must not have")
                    }
                }
                "reopen" -> {
                    // A new key provider instance reads the wrapped key from disk and unwraps it with the Keystore.
                    val digest = h.projectionDigest()
                    val events = h.eventCount()
                    h.close()
                    handle = open(root)
                    if (handle.projectionDigest() != digest || handle.eventCount() != events) throw StepFailure("$label: state differs after reopen")
                }
                "rebuild_equals_live" -> {
                    val before = h.projectionDigest()
                    h.rebuildProjections()
                    if (h.projectionDigest() != before) throw StepFailure("$label: rebuilt projections differ from live state")
                    if (h.integrityCheck() != "ok") throw StepFailure("$label: integrity_check is not ok")
                }
                "export_roundtrip" -> {
                    val data = h.export("json")
                    val other = newRoot()
                    val b = open(other)
                    val report = b.importData("json", data, "{}")
                    if (report.rejected.isNotEmpty() || report.accepted == 0UL) throw StepFailure("$label: round trip import failed")
                    for (name in listOf("list_accounts", "list_categories", "list_budgets", "list_bills", "list_networth_snapshots", "list_transactions")) {
                        if (listRows(h, name).toString() != listRows(b, name).toString()) throw StepFailure("$label: $name differs after round trip")
                    }
                    val again = b.importData("json", data, """{"dry_run": true}""")
                    if (again.accepted != 0UL || again.duplicates != report.accepted) throw StepFailure("$label: re-import must be all duplicates")
                    if (b.integrityCheck() != "ok") throw StepFailure("$label: integrity check on restored install")
                    b.close()
                }
                "export_csv_check" -> {
                    val text = String(h.export("csv"), Charsets.UTF_8)
                    if (text.lines().first() != step.getString("expect_header")) throw StepFailure("$label: csv header differs")
                    val needles = step.getJSONArray("expect_contains")
                    for (i in 0 until needles.length()) if (!text.contains(needles.getString(i))) throw StepFailure("$label: csv missing ${needles.getString(i)}")
                }
                "no_money_movement" -> for (name in h.commandNames()) {
                    if (name.replace('.', '_').split('_').toSet().any { it in forbidden }) throw StepFailure("$label: $name looks like money movement")
                }
                else -> throw StepFailure("$label: unknown op")
            }
        }
    }

    @Test fun the_whole_finance_suite_passes_on_this_device_with_the_android_keystore() {
        val text = InstrumentationRegistry.getInstrumentation().context.assets.open("finance.json").bufferedReader().use { it.readText() }
        val steps = JSONObject(text).getJSONArray("steps")
        val runner = Runner()
        val failures = mutableListOf<String>()
        try {
            for (i in 0 until steps.length()) {
                try {
                    runner.runStep(steps.getJSONObject(i), i)
                } catch (e: StepFailure) {
                    failures += e.message ?: "step $i failed"
                }
            }
        } finally {
            runner.handle.close()
        }
        assertTrue("${failures.size} of ${steps.length()} steps failed:\n" + failures.joinToString("\n"), failures.isEmpty())
        assertTrue("the fixture has run its steps", steps.length() >= 90)
    }

    // ---- Android-specific behaviour ------------------------------------------------------------------

    @Test fun the_device_is_offline_when_the_suite_runs() {
        // The runner script puts the device in airplane mode first:  adb shell cmd connectivity airplane-mode enable
        if (InstrumentationRegistry.getArguments().getString("requireAirplane") != "true") return
        assertEquals(1, android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.AIRPLANE_MODE_ON, 0))
        // Ask Android whether any network is up, with the shell's permission (this app deliberately has none).
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.adoptShellPermissionIdentity("android.permission.ACCESS_NETWORK_STATE")
        try {
            val manager = context.getSystemService(ConnectivityManager::class.java)
            assertNull("airplane mode is on, so no network should be active", manager.activeNetwork)
            assertTrue(manager.allNetworks.none { manager.getNetworkCapabilities(it)?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET) == true && manager.getNetworkCapabilities(it)?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true })
        } finally {
            automation.dropShellPermissionIdentity()
        }
    }

    @Test fun the_app_holds_only_the_reviewed_permissions_at_runtime() {
        val info = context.packageManager.getPackageInfo(context.packageName, android.content.pm.PackageManager.GET_PERMISSIONS)
        val requested = info.requestedPermissions?.toList() ?: emptyList()
        assertEquals(
            setOf(
                "android.permission.INTERNET",
                "android.permission.CAMERA",
                "android.permission.RECORD_AUDIO",
                "android.permission.FOREGROUND_SERVICE",
                "android.permission.FOREGROUND_SERVICE_MICROPHONE",
                "android.permission.health.READ_STEPS",
                "android.permission.health.READ_HEART_RATE",
            ),
            requested.filter { it.startsWith("android.permission.") }.toSet(),
        )
        assertFalse(requested.contains("android.permission.QUERY_ALL_PACKAGES"))
        assertFalse(requested.any { it.contains("ACCESSIBILITY") })
    }

    @Test fun domain_files_and_wrapped_keys_live_in_the_no_backup_directory() {
        val app = context.applicationContext as RevaApp
        assertTrue(app.container.domainRoot.absolutePath.startsWith(context.noBackupFilesDir.absolutePath))
        assertTrue(app.container.keyRoot.absolutePath.startsWith(context.noBackupFilesDir.absolutePath))
        // The paired-PC record (public data only) is excluded from backups the same way.
        assertTrue(app.container.syncRoot.absolutePath.startsWith(context.noBackupFilesDir.absolutePath))
    }

    @Test fun the_wrapped_key_survives_a_restart_and_the_database_is_not_plain_sqlite() {
        val handle = open(root)
        handle.command("account.create", """{"name":"Main","kind":"checking","currency":"USD","opening_balance_minor":500}""")
        handle.close()

        val keyFile = File(root, "keys/finance.key")
        assertTrue(keyFile.exists())
        assertEquals(12 + 32 + 16, keyFile.length().toInt())

        val dbFiles = File(root, "data").walkTopDown().filter { it.isFile && !it.name.endsWith("-wal") && !it.name.endsWith("-shm") }.toList()
        assertTrue(dbFiles.isNotEmpty())
        for (file in dbFiles) {
            val header = ByteArray(16).also { buf -> file.inputStream().use { it.read(buf) } }
            assertFalse("${file.name} must not be a plain SQLite file", String(header, Charsets.ISO_8859_1).startsWith("SQLite format 3"))
        }

        val reopened = open(root)
        val rows = JSONArray(reopened.query("account_balances", "{}").rowsJson)
        assertEquals(1, rows.length())
        assertEquals(500, rows.getJSONObject(0).getInt("balance_minor"))
        reopened.close()
    }

    @Test fun losing_the_keystore_key_locks_the_data_instead_of_creating_a_new_one() {
        val handle = open(root)
        handle.command("account.create", """{"name":"Main","kind":"checking","currency":"USD","opening_balance_minor":500}""")
        handle.close()
        val before = File(root, "keys/finance.key").readBytes()

        deleteWrappingKey() // e.g. a security reset invalidated the key
        try {
            open(root)
            fail("opening must fail while the wrapping key is gone")
        } catch (_: KeyProviderException) {
        } catch (_: DomainException) {
        }
        assertTrue("the wrapped key file must not be replaced", before.contentEquals(File(root, "keys/finance.key").readBytes()))
        assertNotNull(File(root, "data").list())
    }
}
