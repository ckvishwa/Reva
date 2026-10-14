package app.reva.sync

import android.content.SharedPreferences
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Whether the app syncs with the paired PC by itself while it is open. Default on. */
interface AutoSyncSettings {
    var enabled: Boolean
}

class SharedPrefsAutoSyncSettings(private val prefs: SharedPreferences) : AutoSyncSettings {
    override var enabled: Boolean
        get() = prefs.getBoolean(KEY, true)
        set(value) {
            prefs.edit().putBoolean(KEY, value).apply()
        }

    companion object {
        const val KEY = "auto_sync"
    }
}

/** What the screens say about syncing: "Synced just now", "Synced 3 min ago", "Not synced yet", or nothing when unpaired. */
data class SyncStatus(val text: String? = null, val lastSyncAtSeconds: Long? = null, val needsAttention: Boolean = false)

object SyncStatusText {
    fun format(pc: PairedPc?, nowSeconds: Long): String? {
        val at = pc?.lastSyncAtSeconds ?: return if (pc == null) null else "Not synced yet"
        val minutes = (nowSeconds - at).coerceAtLeast(0) / 60
        return when {
            minutes < 1 -> "Synced just now"
            minutes < 60 -> "Synced $minutes min ago"
            minutes < 24 * 60 -> "Synced ${minutes / 60} h ago"
            else -> "Synced ${minutes / (24 * 60)} d ago"
        }
    }
}

/**
 * Keeps the phone in step with the paired PC while the app is in front: one sync when it comes to the
 * foreground, then one every [intervalMillis]. Nothing happens when auto sync is off or no PC is paired.
 * A failed attempt (PC asleep, phone on mobile data, not on the same Wi-Fi) is quiet: it is remembered as
 * "needs attention" and tried again at the next interval. The manifest has no network-state permission
 * (INTERNET and CAMERA only), so "on Wi-Fi" simply means the PC's LAN address answers.
 *
 * The status text ticks every [tickMillis] so "Synced 2 min ago" stays true while a screen is open.
 */
class AutoSyncController(
    private val service: SyncService,
    private val settings: AutoSyncSettings,
    private val scope: CoroutineScope,
    private val intervalMillis: Long = 60_000,
    private val tickMillis: Long = 30_000,
    private val nowSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    private val statusFlow = MutableStateFlow(SyncStatus())
    private val enabledFlow = MutableStateFlow(settings.enabled)
    private var syncLoop: Job? = null
    private var tickLoop: Job? = null
    private var failed = false

    val status: StateFlow<SyncStatus> = statusFlow.asStateFlow()
    val enabled: StateFlow<Boolean> = enabledFlow.asStateFlow()

    fun setEnabled(value: Boolean) {
        settings.enabled = value
        enabledFlow.value = value
        if (value && syncLoop?.isActive == true) scope.launch { syncOnce() }
    }

    /** The app came to the front: sync now, then keep syncing while it stays there. */
    fun onForeground() {
        if (syncLoop?.isActive == true) return
        syncLoop = scope.launch {
            while (true) {
                syncOnce()
                delay(intervalMillis)
            }
        }
        tickLoop = scope.launch {
            while (true) {
                refreshStatus()
                delay(tickMillis)
            }
        }
    }

    fun onBackground() {
        syncLoop?.cancel()
        tickLoop?.cancel()
        syncLoop = null
        tickLoop = null
    }

    /** Re-read when the PC was last synced with (after a manual sync, for example). */
    suspend fun refreshStatus() {
        val pc = service.paired()
        statusFlow.value = SyncStatus(SyncStatusText.format(pc, nowSeconds()), pc?.lastSyncAtSeconds, failed)
    }

    private suspend fun syncOnce() {
        if (!settings.enabled || service.paired() == null) {
            refreshStatus()
            return
        }
        try {
            service.syncNow()
            failed = false
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            failed = true // quiet: the next interval tries again
        }
        refreshStatus()
    }
}
