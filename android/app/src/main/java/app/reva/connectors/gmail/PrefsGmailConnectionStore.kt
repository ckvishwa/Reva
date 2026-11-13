package app.reva.connectors.gmail

import android.content.SharedPreferences
import androidx.core.content.edit

/** One boolean in private preferences (excluded from Android backups like every other preference file). */
class PrefsGmailConnectionStore(private val prefs: SharedPreferences) : GmailConnectionStore {
    override var connected: Boolean
        get() = prefs.getBoolean(KEY, false)
        set(value) {
            prefs.edit { putBoolean(KEY, value) }
        }

    private companion object {
        const val KEY = "gmail_connected"
    }
}
