package app.reva

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Document
import org.w3c.dom.Element
import org.w3c.dom.NodeList

/**
 * Manifest checks for this slice, run on every unit-test build against the MERGED manifest (so permissions
 * and services pulled in by libraries count too): only INTERNET and CAMERA (for pairing with the user's own PC),
 * no cleartext, no QUERY_ALL_PACKAGES, no AccessibilityService,
 * and backup rules that exclude the domain files.
 */
class ManifestTest {
    private fun parse(path: String): Document {
        val file = File(path)
        assertTrue("missing $path", file.exists())
        val factory = DocumentBuilderFactory.newInstance()
        factory.isNamespaceAware = true // attributes below are looked up by namespace
        return factory.newDocumentBuilder().parse(file)
    }

    private fun merged() = parse(System.getProperty("reva.mergedManifest"))

    private val androidNs = "http://schemas.android.com/apk/res/android"

    private fun NodeList.elements(): List<Element> = (0 until length).map { item(it) as Element }

    private fun Document.permissions() = getElementsByTagName("uses-permission").elements().map { it.getAttributeNS(androidNs, "name") }

    @Test fun the_app_requests_exactly_internet_and_camera_plus_androidxs_internal_permission() {
        val permissions = merged().permissions().sorted()
        assertEquals(
            listOf("android.permission.CAMERA", "android.permission.INTERNET", "app.reva.android.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"),
            permissions,
        )
    }

    @Test fun internet_is_used_for_the_paired_pc_only_so_cleartext_is_refused_everywhere() {
        val doc = merged()
        val app = doc.getElementsByTagName("application").elements().single()
        assertEquals("false", app.getAttributeNS(androidNs, "usesCleartextTraffic"))
        assertEquals("@xml/network_security_config", app.getAttributeNS(androidNs, "networkSecurityConfig"))
        val config = File(System.getProperty("reva.resDir"), "xml/network_security_config.xml").readText()
        assertTrue(config.contains("cleartextTrafficPermitted=\"false\""))
        assertFalse("no domain may be allowed cleartext", config.contains("cleartextTrafficPermitted=\"true\""))
    }

    @Test fun the_camera_is_optional_hardware_and_no_other_hardware_or_network_permission_is_requested() {
        val doc = merged()
        val camera = doc.getElementsByTagName("uses-feature").elements().single { it.getAttributeNS(androidNs, "name") == "android.hardware.camera" }
        assertEquals("false", camera.getAttributeNS(androidNs, "required"))
        val permissions = doc.permissions()
        assertFalse(permissions.any { it.contains("RECORD_AUDIO") || it.contains("LOCATION") || it.contains("NETWORK") || it.contains("WIFI") })
    }

    @Test fun there_is_no_query_all_packages() {
        assertFalse(merged().permissions().any { it.contains("QUERY_ALL_PACKAGES") })
    }

    @Test fun there_is_no_accessibility_service() {
        val doc = merged()
        val services = doc.getElementsByTagName("service").elements()
        for (service in services) {
            assertTrue("service ${service.getAttributeNS(androidNs, "name")} must not be an accessibility service",
                service.getAttributeNS(androidNs, "permission") != "android.permission.BIND_ACCESSIBILITY_SERVICE")
        }
        val actions = doc.getElementsByTagName("action").elements().map { it.getAttributeNS(androidNs, "name") }
        assertFalse(actions.contains("android.accessibilityservice.AccessibilityService"))
        assertFalse(merged().permissions().any { it.contains("BIND_ACCESSIBILITY_SERVICE") })
    }

    @Test fun the_only_unguarded_exported_component_is_the_launcher_activity_and_the_provider_is_private() {
        val doc = merged()
        val exported = (doc.getElementsByTagName("activity").elements() + doc.getElementsByTagName("service").elements() +
            doc.getElementsByTagName("receiver").elements() + doc.getElementsByTagName("provider").elements())
            .filter { it.getAttributeNS(androidNs, "exported") == "true" }
        // AndroidX's profile installer receiver is exported on purpose, but only the system's DUMP permission may call it.
        val unguarded = exported.filter { it.getAttributeNS(androidNs, "permission") != "android.permission.DUMP" }
            .map { it.getAttributeNS(androidNs, "name") }
        // Builds made for Compose tests (-Preva.uiTests=true) add androidx's empty test activity; the build you sideload does not.
        val expected = if (System.getProperty("reva.uiTestsBuild") == "true") listOf("app.reva.MainActivity", "androidx.activity.ComponentActivity") else listOf("app.reva.MainActivity")
        assertEquals(expected, unguarded)
        val provider = doc.getElementsByTagName("provider").elements().single { it.getAttributeNS(androidNs, "name").endsWith("FileProvider") }
        assertEquals("false", provider.getAttributeNS(androidNs, "exported"))
    }

    @Test fun backups_are_explicitly_ruled_and_exclude_the_domain_files() {
        val app = parse(System.getProperty("reva.sourceManifest")).getElementsByTagName("application").elements().single()
        assertEquals("@xml/data_extraction_rules", app.getAttributeNS(androidNs, "dataExtractionRules"))
        assertEquals("@xml/backup_rules", app.getAttributeNS(androidNs, "fullBackupContent"))
        val res = System.getProperty("reva.resDir")
        for (name in listOf("data_extraction_rules.xml", "backup_rules.xml")) {
            val text = File(res, "xml/$name").readText()
            assertTrue("$name must exclude no_backup", text.contains("domain=\"root\" path=\"no_backup\""))
            for (domain in listOf("file", "database", "sharedpref", "external")) {
                assertTrue("$name must exclude the $domain domain", text.contains("domain=\"$domain\" path=\".\""))
            }
            assertFalse("$name must not include anything", text.contains("<include"))
        }
        val extraction = File(res, "xml/data_extraction_rules.xml").readText()
        assertTrue(extraction.contains("<cloud-backup>") && extraction.contains("<device-transfer>"))
    }

    @Test fun the_app_targets_android_16_and_needs_android_12() {
        val gradle = File(System.getProperty("reva.sourceManifest")).parentFile.parentFile.parentFile.resolve("build.gradle.kts").readText()
        assertTrue(gradle.contains("minSdk = 31"))
        assertTrue(gradle.contains("targetSdk = 36"))
        assertTrue(gradle.contains("compileSdk = 36"))
    }
}
