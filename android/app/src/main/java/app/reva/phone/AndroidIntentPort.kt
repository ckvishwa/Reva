package app.reva.phone

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri

/**
 * The Android side of [IntentPort] and [LaunchableApps]. Only public, documented intents (see [PhoneIntents]) and
 * only the visibility the manifest's `<queries>` grants: launcher apps, and the four intent kinds REVA hands off.
 * There is no QUERY_ALL_PACKAGES and no accessibility service.
 */
class AndroidIntentPort(private val context: Context) : IntentPort, LaunchableApps {
    private val packages: PackageManager get() = context.packageManager

    override fun resolve(spec: IntentSpec): String? {
        val intent = build(spec, wrap = false) ?: return null
        val info = packages.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY) ?: return null
        return if (spec.chooserTitle != null) "the share sheet" else info.loadLabel(packages).toString()
    }

    override fun start(spec: IntentSpec): Boolean {
        val intent = build(spec, wrap = true) ?: return false
        return try {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (e: ActivityNotFoundException) {
            false
        } catch (e: SecurityException) {
            false
        }
    }

    override fun list(): List<InstalledApp> {
        val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return packages.queryIntentActivities(launcher, 0)
            .map { InstalledApp(it.activityInfo.packageName, it.loadLabel(packages).toString()) }
            .filter { it.packageName != context.packageName }
            .distinctBy { it.packageName }
            .sortedBy { it.label.lowercase() }
    }

    private fun build(spec: IntentSpec, wrap: Boolean): Intent? {
        spec.launchPackage?.let { return packages.getLaunchIntentForPackage(it) }
        val intent = Intent(spec.action)
        spec.data?.let { intent.data = Uri.parse(it) }
        spec.type?.let { intent.type = it }
        for ((key, value) in spec.extras) {
            when (value) {
                is String -> intent.putExtra(key, value)
                is Int -> intent.putExtra(key, value)
                is Long -> intent.putExtra(key, value)
                is Boolean -> intent.putExtra(key, value)
                else -> return null // an extra of a kind no builder produces is never sent
            }
        }
        val title = spec.chooserTitle
        return if (title != null && wrap) Intent.createChooser(intent, title) else intent
    }
}
