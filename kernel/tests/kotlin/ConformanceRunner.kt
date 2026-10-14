// Runs kernel/tests/conformance/finance.json through the UniFFI Kotlin binding on the JVM.
// Same fixture and same expectations as the native Rust and Python runners.
//
// Run: python tools/kernel/run_kotlin_conformance.py

import java.io.File
import java.nio.file.Files
import java.util.Comparator
import kotlin.system.exitProcess
import org.json.JSONArray
import org.json.JSONObject
import uniffi.reva_kernel.*

class MemKeys : KeyProvider {
    val keys = HashMap<String, ByteArray>()
    override fun loadKey(domain: String): ByteArray? = keys[domain]
    override fun storeKey(domain: String, key: ByteArray) {
        keys[domain] = key.copyOf()
    }
}

class StepFailure(message: String) : Exception(message)

val FORBIDDEN = setOf(
    "pay", "payment", "transfer", "send", "withdraw", "purchase", "buy", "wire", "ach", "login", "credential",
    "password", "bank"
)
val VOLATILE = setOf("version", "created_at", "updated_at")

fun codeOf(e: Throwable): String = when (e) {
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

fun same(expected: Any?, actual: Any?): Boolean {
    val e = if (expected == JSONObject.NULL) null else expected
    val a = if (actual == JSONObject.NULL) null else actual
    if (e is Number && a is Number) {
        return if (e.toDouble() == e.toLong().toDouble() && a.toDouble() == a.toLong().toDouble()) e.toLong() == a.toLong()
        else e.toDouble() == a.toDouble()
    }
    return e == a
}

fun subset(expected: Any?, actual: Any?, path: String) {
    when (expected) {
        is JSONObject -> {
            if (actual !is JSONObject) throw StepFailure("$path: expected object, got $actual")
            for (key in expected.keySet()) {
                if (!actual.has(key)) throw StepFailure("$path.$key: missing in $actual")
                subset(expected.get(key), actual.get(key), "$path.$key")
            }
        }
        is JSONArray -> {
            if (actual !is JSONArray || actual.length() != expected.length()) {
                throw StepFailure("$path: expected ${expected.length()} items, got $actual")
            }
            for (i in 0 until expected.length()) subset(expected.get(i), actual.get(i), "$path[$i]")
        }
        else -> if (!same(expected, actual)) throw StepFailure("$path: expected $expected, got $actual")
    }
}

fun strip(value: Any?): Any? = when (value) {
    is JSONObject -> {
        val out = JSONObject()
        for (key in value.keySet().sorted()) if (key !in VOLATILE) out.put(key, strip(value.get(key)))
        out
    }
    is JSONArray -> {
        val out = JSONArray()
        for (i in 0 until value.length()) out.put(strip(value.get(i)))
        out
    }
    else -> value
}

class Runner {
    val dir: File = Files.createTempDirectory("reva-kernel-kt-").toFile()
    val keys = MemKeys()
    var handle: DomainHandle? = openDomain("finance", keys, dir.absolutePath)

    fun h(): DomainHandle = handle!!

    fun close() {
        handle?.close()
        handle = null
        dir.deleteRecursively()
    }

    private fun <T> attempt(block: () -> T): Pair<T?, Throwable?> =
        try { Pair(block(), null) } catch (e: DomainException) { Pair(null, e) }

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

    private fun listRows(handle: DomainHandle, name: String): Any? {
        val params = if (name == "list_transactions") """{"limit": 1000}""" else "{}"
        return strip(JSONArray(handle.query(name, params).rowsJson))
    }

    fun runStep(step: JSONObject, index: Int) {
        val op = step.getString("op")
        val label = "step $index ($op ${step.optString("kind", step.optString("name", ""))})"
        val handle = h()
        when (op) {
            "command" -> {
                val (result, error) = attempt { handle.command(step.getString("kind"), step.getJSONObject("payload").toString()) }
                if (expectError(step, label, error)) return
                if (step.has("expect")) {
                    val actual = JSONObject()
                        .put("event_id", result!!.eventId).put("aggregate_id", result.aggregateId).put("version", result.version)
                    subset(step.get("expect"), actual, label)
                }
            }
            "query" -> {
                val (result, error) = attempt { handle.query(step.getString("name"), step.getJSONObject("params").toString()) }
                if (expectError(step, label, error)) return
                if (step.has("expect_rows")) subset(step.get("expect_rows"), JSONArray(result!!.rowsJson), label)
                if (step.has("expect_source_ids_sorted")) {
                    val got = JSONArray(result!!.sourceIds.sorted())
                    subset(step.get("expect_source_ids_sorted"), got, label)
                }
            }
            "today" -> {
                val text = today(listOf(handle), if (step.has("as_of")) step.getString("as_of") else null)
                subset(step.get("expect"), JSONObject(text), label)
            }
            "import", "import_error" -> {
                val beforeEvents = handle.eventCount()
                val beforeDigest = handle.projectionDigest()
                val (result, error) = attempt {
                    handle.importData(step.getString("format"), step.getString("data").toByteArray(Charsets.UTF_8), step.getJSONObject("options").toString())
                }
                if (op == "import_error") {
                    if (!expectError(step, label, error)) throw StepFailure("$label: import_error needs expect_error")
                } else {
                    if (error != null) throw StepFailure("$label: $error")
                    val r = result!!
                    val rejected = JSONArray()
                    for (x in r.rejected) rejected.put(JSONObject().put("row", x.row.toLong()).put("reason", x.reason))
                    val actual = JSONObject().put("accepted", r.accepted.toLong()).put("duplicates", r.duplicates.toLong())
                        .put("dry_run", r.dryRun).put("rejected", rejected)
                    subset(step.get("expect"), actual, label)
                    val listed = JSONArray(r.rowsJson).length().toLong()
                    if (listed != r.accepted.toLong() + r.duplicates.toLong() + r.rejected.size) {
                        throw StepFailure("$label: row report incomplete")
                    }
                }
                if (step.optBoolean("check_unchanged", false) || op == "import_error") {
                    if (handle.eventCount() != beforeEvents || handle.projectionDigest() != beforeDigest) {
                        throw StepFailure("$label: state changed but must not have")
                    }
                }
            }
            "reopen" -> {
                val digest = handle.projectionDigest()
                val events = handle.eventCount()
                handle.close()
                this.handle = openDomain("finance", keys, dir.absolutePath)
                if (h().projectionDigest() != digest || h().eventCount() != events) throw StepFailure("$label: state differs after reopen")
            }
            "rebuild_equals_live" -> {
                val before = handle.projectionDigest()
                handle.rebuildProjections()
                if (handle.projectionDigest() != before) throw StepFailure("$label: rebuilt projections differ from live state")
                if (handle.integrityCheck() != "ok") throw StepFailure("$label: integrity_check is not ok")
            }
            "export_roundtrip" -> {
                val data = handle.export("json")
                val dirB = Files.createTempDirectory("reva-kernel-kt-b-").toFile()
                try {
                    val b = openDomain("finance", MemKeys(), dirB.absolutePath)
                    val report = b.importData("json", data, "{}")
                    if (report.rejected.isNotEmpty() || report.accepted == 0UL) throw StepFailure("$label: round trip import failed")
                    for (name in listOf("list_accounts", "list_categories", "list_budgets", "list_bills", "list_networth_snapshots", "list_transactions")) {
                        if (listRows(handle, name).toString() != listRows(b, name).toString()) throw StepFailure("$label: $name differs after round trip")
                    }
                    val again = b.importData("json", data, """{"dry_run": true}""")
                    if (again.accepted != 0UL || again.duplicates != report.accepted) throw StepFailure("$label: re-import must be all duplicates")
                    if (b.integrityCheck() != "ok") throw StepFailure("$label: integrity check on restored install")
                    b.close()
                } finally {
                    dirB.deleteRecursively()
                }
            }
            "export_csv_check" -> {
                val text = String(handle.export("csv"), Charsets.UTF_8)
                if (text.lines().first() != step.getString("expect_header")) throw StepFailure("$label: csv header differs")
                val needles = step.getJSONArray("expect_contains")
                for (i in 0 until needles.length()) if (!text.contains(needles.getString(i))) throw StepFailure("$label: csv missing ${needles.getString(i)}")
            }
            "no_money_movement" -> {
                for (name in handle.commandNames()) {
                    val tokens = name.replace('.', '_').split('_').toSet()
                    if (tokens.any { it in FORBIDDEN }) throw StepFailure("$label: $name looks like money movement")
                }
            }
            else -> throw StepFailure("$label: unknown op")
        }
    }
}

fun main(args: Array<String>) {
    val fixture = File(args[0])
    val steps = JSONObject(fixture.readText(Charsets.UTF_8)).getJSONArray("steps")
    val runner = Runner()
    val failures = ArrayList<String>()
    try {
        for (i in 0 until steps.length()) {
            try {
                runner.runStep(steps.getJSONObject(i), i)
            } catch (e: StepFailure) {
                failures.add(e.message ?: "failure")
            }
        }
    } finally {
        runner.close()
    }
    if (failures.isNotEmpty()) {
        System.err.println("${failures.size} of ${steps.length()} steps failed:\n" + failures.joinToString("\n"))
        exitProcess(1)
    }

    // Host key-vault behaviour through the Kotlin binding.
    hostChecks()
    println("kotlin conformance: ${steps.length()} steps passed; host checks passed")
}

fun hostChecks() {
    val dir = Files.createTempDirectory("reva-kernel-kt-host-").toFile()
    try {
        class Offline : KeyProvider {
            override fun loadKey(domain: String): ByteArray? = throw KeyProviderException.Unavailable("vault offline")
            override fun storeKey(domain: String, key: ByteArray) = throw KeyProviderException.Unavailable("vault offline")
        }
        try {
            openDomain("finance", Offline(), dir.absolutePath)
            throw StepFailure("an offline vault must give Locked")
        } catch (e: DomainException.Locked) {
        }
        val vault = MemKeys()
        val handle = openDomain("finance", vault, dir.absolutePath)
        handle.command("account.create", """{"id": "acct-main-1", "name": "Main", "currency": "USD"}""")
        handle.close()
        val good = vault.keys["finance"]!!
        vault.keys["finance"] = ByteArray(32) { 7 }
        try {
            openDomain("finance", vault, dir.absolutePath)
            throw StepFailure("a wrong key must be rejected")
        } catch (e: DomainException.WrongKey) {
        }
        vault.keys.remove("finance")
        try {
            openDomain("finance", vault, dir.absolutePath)
            throw StepFailure("a missing key must be rejected")
        } catch (e: DomainException.Locked) {
        }
        vault.keys["finance"] = good
        val again = openDomain("finance", vault, dir.absolutePath)
        if (again.eventCount() != 1L) throw StepFailure("data lost after failed opens")
        again.close()
    } finally {
        dir.deleteRecursively()
    }
}
