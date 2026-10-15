package app.reva.phone

import app.reva.pcrequests.PcPhrases
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

/** An app on this phone the owner has approved REVA to open, and the words that name it. */
data class ApprovedApp(val packageName: String, val label: String, val aliases: List<String>)

/** What the phone says is installed and launchable (the Android implementation lists launcher activities). */
data class InstalledApp(val packageName: String, val label: String)

fun interface LaunchableApps {
    fun list(): List<InstalledApp>
}

/**
 * The apps the owner approved, by their own aliases (AR-AND: no QUERY_ALL_PACKAGES; the phone sees only apps
 * that have a launcher icon, and REVA opens only the ones approved here). Saved in one small JSON file.
 */
class ApprovedApps(private val file: File?) {
    private var apps: List<ApprovedApp> = load()

    fun all(): List<ApprovedApp> = apps

    /** Approve [app] under its label and any extra [aliases]; replaces an earlier approval of the same package. */
    fun approve(app: InstalledApp, aliases: List<String> = emptyList()) {
        val names = (listOf(app.label) + aliases).map(::normalise).filter { it.isNotEmpty() }.distinct().take(MAX_ALIASES)
        require(names.isNotEmpty()) { "an app needs at least one name" }
        apps = apps.filter { it.packageName != app.packageName } + ApprovedApp(app.packageName, app.label.take(80), names)
        save()
    }

    fun remove(packageName: String) {
        apps = apps.filter { it.packageName != packageName }
        save()
    }

    /**
     * The package for what the owner said, or null. Only an exact alias (same meaningful words) counts, and a
     * name two approved apps share is refused rather than guessed.
     */
    fun resolve(phrase: String): ApprovedApp? {
        val wanted = normalise(phrase)
        if (wanted.isEmpty()) return null
        val hits = apps.filter { app -> app.aliases.any { it == wanted } }
        return hits.singleOrNull()
    }

    private fun normalise(text: String) = PcPhrases.contentTokens(text).joinToString(" ")

    private fun load(): List<ApprovedApp> = try {
        val array = JSONArray(file!!.readText())
        (0 until array.length()).map {
            val o = array.getJSONObject(it)
            ApprovedApp(
                o.getString("package"),
                o.getString("label"),
                o.getJSONArray("aliases").let { a -> (0 until a.length()).map(a::getString) },
            )
        }
    } catch (e: Exception) {
        emptyList() // missing or damaged: nothing is approved
    }

    private fun save() {
        val target = file ?: return
        val array = JSONArray()
        apps.forEach {
            array.put(JSONObject().put("package", it.packageName).put("label", it.label).put("aliases", JSONArray(it.aliases)))
        }
        target.parentFile?.mkdirs()
        val temp = File(target.parentFile, target.name + ".tmp")
        temp.writeText(array.toString())
        if (!temp.renameTo(target)) {
            target.delete()
            check(temp.renameTo(target)) { "could not save the approved apps" }
        }
    }

    private companion object {
        const val MAX_ALIASES = 6
    }
}
