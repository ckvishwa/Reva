package app.reva.phone

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.Rule
import org.junit.rules.TemporaryFolder

class ApprovedAppsTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun store(): ApprovedApps = ApprovedApps(File(tmp.root, "apps.json"))

    @Test fun nothing_is_approved_until_the_owner_approves_it() {
        val apps = store()
        assertTrue(apps.all().isEmpty())
        assertNull(apps.resolve("calculator"))
    }

    @Test fun an_approved_app_resolves_by_its_label_and_its_aliases() {
        val apps = store()
        apps.approve(InstalledApp("com.example.calc", "Calculator"), listOf("calc"))

        assertEquals("com.example.calc", apps.resolve("calculator")?.packageName)
        assertEquals("com.example.calc", apps.resolve("the Calculator app")?.packageName)
        assertEquals("com.example.calc", apps.resolve("calc")?.packageName)
        assertNull(apps.resolve("notepad"))
    }

    @Test fun removing_an_app_makes_it_unresolvable() {
        val apps = store()
        apps.approve(InstalledApp("com.example.calc", "Calculator"))
        apps.remove("com.example.calc")

        assertNull(apps.resolve("calculator"))
        assertTrue(apps.all().isEmpty())
    }

    @Test fun approving_again_replaces_the_earlier_entry() {
        val apps = store()
        apps.approve(InstalledApp("com.example.calc", "Calculator"), listOf("calc"))
        apps.approve(InstalledApp("com.example.calc", "Calculator Pro"), listOf("calc pro"))

        assertEquals(1, apps.all().size)
        assertNull(apps.resolve("calc"))
        assertEquals("com.example.calc", apps.resolve("calc pro")?.packageName)
    }

    @Test fun two_approved_apps_sharing_a_name_resolve_to_neither() {
        val apps = store()
        apps.approve(InstalledApp("com.a.music", "Music"))
        apps.approve(InstalledApp("com.b.music", "Music"), listOf("music"))

        assertNull(apps.resolve("music"))
    }

    @Test fun approvals_survive_a_restart() {
        val file = File(tmp.root, "apps.json")
        ApprovedApps(file).approve(InstalledApp("com.example.calc", "Calculator"))

        val reopened = ApprovedApps(file)

        assertEquals("com.example.calc", reopened.resolve("calculator")?.packageName)
    }

    @Test fun a_damaged_file_means_nothing_is_approved_not_a_crash() {
        val file = File(tmp.root, "apps.json")
        file.writeText("not json")

        assertTrue(ApprovedApps(file).all().isEmpty())
    }

    @Test fun no_file_is_the_same_as_no_approvals_and_approving_without_a_file_does_not_crash() {
        val apps = ApprovedApps(null)
        apps.approve(InstalledApp("com.example.calc", "Calculator"))

        assertEquals("com.example.calc", apps.resolve("calculator")?.packageName)
    }
}
