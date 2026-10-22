package app.reva.ui

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import java.time.LocalDate

/**
 * Export through the system share sheet. The bytes are written to one file in the app's cache, handed out as
 * a content:// URI with a one-time read grant, and older export files are removed first. The file is a plain,
 * unencrypted copy, which the confirmation dialog says before anything is shared.
 */
object ExportShare {
    /** Format of the Health backup (`reva-health-v2` JSON, gym training included); Finance uses `json` and `csv`. */
    const val HEALTH_JSON = "health_json"

    fun fileName(format: String, today: LocalDate): String = when (format) {
        HEALTH_JSON -> "reva-health-$today.json"
        "json" -> "reva-finance-$today.json"
        else -> "reva-finance-$today.csv"
    }

    fun mimeType(format: String): String = if (format == "json" || format == HEALTH_JSON) "application/json" else "text/csv"

    /** Removes every shared export from [cacheDir]. Called at every app start so a plain copy never lingers. */
    fun clear(cacheDir: File) {
        File(cacheDir, "exports").listFiles()?.forEach { it.delete() }
    }

    fun write(context: Context, format: String, bytes: ByteArray, today: LocalDate = LocalDate.now()): File {
        clear(context.cacheDir)
        val dir = File(context.cacheDir, "exports").also { it.mkdirs() }
        return File(dir, fileName(format, today)).also { it.writeBytes(bytes) }
    }

    fun share(context: Context, format: String, bytes: ByteArray) {
        val file = write(context, format, bytes)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.exports", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = mimeType(format)
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val title = if (format == HEALTH_JSON) "Share Health backup" else "Share Finance export"
        context.startActivity(Intent.createChooser(send, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
