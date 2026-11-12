package app.reva

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * APK-01, AR-APK-002: the package import rules of ARD-210 section 5, checked over the import lines of every
 * main source file on each unit-test build. Packages are the module boundaries of this single-module app.
 *
 * Where today's code does not meet a rule yet, the file is named in an explicit exception list below. A new
 * violation fails the build; so does an exception that is no longer needed, so the lists can only shrink.
 */
class PackageBoundaryTest {
    private val root: File = File(System.getProperty("reva.sourceManifest")).parentFile.resolve("java/app/reva")

    private data class Source(val path: String, val pkg: String, val imports: List<String>)

    private val sources: List<Source> by lazy {
        assertTrue("missing $root", root.isDirectory)
        root.walkTopDown().filter { it.isFile && it.extension == "kt" }.map { file ->
            val rel = file.relativeTo(root).invariantSeparatorsPath
            val imports = file.readLines().map { it.trim() }.filter { it.startsWith("import ") }
                .map { it.removePrefix("import ").substringBefore(" as ").trim() }
            Source(rel, rel.substringBefore('/', missingDelimiterValue = ""), imports)
        }.toList()
    }

    private fun violations(inPackages: Set<String>, forbidden: (String) -> Boolean): Map<String, List<String>> =
        sources.filter { it.pkg in inPackages }
            .associate { it.path to it.imports.filter(forbidden) }
            .filterValues { it.isNotEmpty() }

    private fun String.isUnder(vararg prefixes: String) = prefixes.any { this == it || startsWith("$it.") }

    @Test fun the_source_tree_was_found_and_has_the_packages_the_rules_name() {
        val packages = sources.map { it.pkg }.toSet()
        for (name in listOf("core", "data", "brain", "policy", "language", "sync", "ui")) assertTrue("no $name package", name in packages)
        assertTrue(sources.size > 50)
    }

    @Test fun ui_never_imports_the_kernel_binding_or_a_connector() {
        assertEquals(emptyMap<String, List<String>>(), violations(setOf("ui")) { it.isUnder("uniffi", "app.reva.connectors") })
    }

    @Test fun ui_opens_no_sockets() {
        assertEquals(
            emptyMap<String, List<String>>(),
            violations(setOf("ui")) { it.isUnder("java.net", "javax.net", "okhttp3", "android.net.http") },
        )
    }

    @Test fun core_policy_and_language_are_pure_no_android_and_no_network() {
        assertEquals(
            emptyMap<String, List<String>>(),
            violations(setOf("core", "policy", "language")) {
                it.isUnder("android", "androidx", "java.net", "javax.net", "okhttp3", "uniffi")
            },
        )
    }

    @Test fun ingest_is_pure_once_it_exists() {
        assertEquals(
            emptyMap<String, List<String>>(),
            violations(setOf("ingest")) { it.isUnder("android", "androidx", "java.net", "javax.net", "okhttp3", "uniffi") },
        )
    }

    @Test fun connectors_and_brain_never_import_each_other_and_connectors_never_reach_voice() {
        assertEquals(emptyMap<String, List<String>>(), violations(setOf("brain")) { it.isUnder("app.reva.connectors") })
        assertEquals(
            emptyMap<String, List<String>>(),
            violations(setOf("connectors")) { it.isUnder("app.reva.brain", "app.reva.voice") },
        )
    }

    /**
     * ARD-210 says only `data` touches the UniFFI binding. Three files outside it do today: the composition root
     * opens the domain handles, and sync implements the Kernel's signer and feeds it batches. They are recorded
     * here, not hidden; moving them behind `data` is follow-up work, not part of APK-01.
     */
    @Test fun only_data_touches_the_kernel_binding_apart_from_the_recorded_exceptions() {
        val known = setOf("RevaApp.kt", "sync/KeystoreDeviceSigner.kt", "sync/SyncEngine.kt")
        val outside = sources.filter { it.pkg != "data" && it.imports.any { import -> import.isUnder("uniffi") } }.map { it.path }.toSet()
        assertEquals(known, outside)
    }
}
