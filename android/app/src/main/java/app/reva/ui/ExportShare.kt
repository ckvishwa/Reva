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
    fun fileName(format: String, today: LocalDate): String = "reva-finance-$today.${if (format == "json") "json" else "csv"}"

    fun mimeType(format: String): String = if (format == "json") "application/json" else "text/csv"

    fun write(context: Context, format: String, bytes: ByteArray, today: LocalDate = LocalDate.now()): File {
        val dir = File(context.cacheDir, "exports").also { it.mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
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
        context.startActivity(Intent.createChooser(send, "Share Finance export").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
