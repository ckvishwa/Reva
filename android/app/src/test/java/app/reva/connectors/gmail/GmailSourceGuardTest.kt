package app.reva.connectors.gmail

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * CON-1 guard rails, checked over the app's main sources on every unit-test build: read-only Gmail only, no client
 * secret, no logging in the Gmail connector, and Gmail code stays out of the brain, voice, sync and PC-request paths.
 */
class GmailSourceGuardTest {
    private val main: File = File(System.getProperty("reva.sourceManifest")).parentFile
    private val javaRoot = main.resolve("java/app/reva")
    private fun sources() = main.walkTopDown().filter { it.isFile && (it.extension == "kt" || it.extension == "xml") }.toList()

    @Test fun the_only_google_scope_requested_is_gmail_readonly() {
        val forbidden = listOf(
            "gmail.send", "gmail.modify", "gmail.compose", "gmail.insert", "gmail.labels", "gmail.settings",
            "gmail.metadata", "mail.google.com", "gmail.addons",
        )
        val hits = sources().flatMap { f -> forbidden.filter { f.readText().contains(it) }.map { "${f.name}: $it" } }
        assertEquals(emptyList<String>(), hits)
        assertEquals("https://www.googleapis.com/auth/gmail.readonly", GMAIL_READONLY)
    }

    @Test fun no_client_secret_or_web_client_is_in_the_app() {
        val hits = sources().filter { f -> f.readText().let { it.contains("client_secret") || it.contains("requestServerAuthCode") || it.contains("setServerClientId") } }
        assertEquals(emptyList<File>(), hits)
    }

    @Test fun the_gmail_connector_never_logs() {
        val dir = javaRoot.resolve("connectors/gmail")
        assertTrue(dir.isDirectory)
        val logging = dir.walkTopDown().filter { it.isFile }.filter { f ->
            val text = f.readText()
            text.contains("android.util.Log") || text.contains("Log.") || text.contains("println(") || text.contains("printStackTrace")
        }.map { it.name }.toList()
        assertEquals(emptyList<String>(), logging)
    }

    @Test fun nothing_outside_the_composition_root_and_connectors_imports_the_gmail_connector() {
        val allowed = setOf("RevaApp.kt", "GmailUiBridge.kt")
        val users = javaRoot.walkTopDown().filter { it.isFile && it.extension == "kt" }
            .filter { f -> f.readLines().any { it.trim().startsWith("import app.reva.connectors.gmail") } }
            .map { it.relativeTo(javaRoot).invariantSeparatorsPath }
            .filterNot { it.startsWith("connectors/") || it in allowed }
            .toList()
        assertEquals(emptyList<String>(), users)
    }
}
