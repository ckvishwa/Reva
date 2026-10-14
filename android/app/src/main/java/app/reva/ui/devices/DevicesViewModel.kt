package app.reva.ui.devices

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.reva.sync.PairPoll
import app.reva.sync.PairedPc
import app.reva.sync.SyncException
import app.reva.sync.SyncReport
import app.reva.sync.SyncService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class DevicesPhase { Idle, Contacting, WaitingForApproval, Syncing }

data class DevicesUiState(
    val loaded: Boolean = false,
    val pc: PairedPc? = null,
    val phase: DevicesPhase = DevicesPhase.Idle,
    /** The 6 digits to compare with the PC while waiting for approval. */
    val fingerprint: String? = null,
    val message: String? = null,
    /** True when [message] is bad news; false for a plain result such as "Synced". */
    val isError: Boolean = false,
    val lastSyncText: String? = null,
) {
    val isBusy: Boolean get() = phase != DevicesPhase.Idle
}

/**
 * The Devices screen. Pairing: [onPairingCode] contacts the PC, shows the fingerprint, then polls until the
 * user has approved (or refused) on the PC. All network and Kernel work happens inside [SyncService].
 */
class DevicesViewModel(
    private val service: SyncService,
    private val onSynced: () -> Unit = {},
    private val pollIntervalMillis: Long = 2_000,
    private val maxWaitMillis: Long = 150_000,
    private val nowSeconds: () -> Long = { System.currentTimeMillis() / 1000 },
) : ViewModel() {

    private val _state = MutableStateFlow(DevicesUiState())
    val state: StateFlow<DevicesUiState> = _state.asStateFlow()
    private var pairingJob: Job? = null

    fun load() {
        viewModelScope.launch {
            val pc = service.paired()
            _state.update { it.copy(loaded = true, pc = pc, lastSyncText = lastSync(pc)) }
        }
    }

    fun onPairingCode(text: String) {
        if (_state.value.isBusy) return
        pairingJob?.cancel()
        pairingJob = viewModelScope.launch {
            _state.update { it.copy(phase = DevicesPhase.Contacting, message = null, isError = false, fingerprint = null) }
            try {
                val start = service.startPairing(text)
                _state.update { it.copy(phase = DevicesPhase.WaitingForApproval, fingerprint = start.fingerprint) }
                waitForApproval()
            } catch (e: SyncException) {
                idle(e.message, error = true)
            }
        }
    }

    private suspend fun waitForApproval() {
        var waited = 0L
        while (waited <= maxWaitMillis) {
            when (val poll = try {
                service.pollPairing()
            } catch (e: SyncException) {
                return idle(e.message, error = true)
            }) {
                PairPoll.Pending -> {
                    delay(pollIntervalMillis)
                    waited += pollIntervalMillis
                }
                is PairPoll.Approved -> {
                    _state.update {
                        it.copy(
                            phase = DevicesPhase.Idle, fingerprint = null, pc = poll.pc, lastSyncText = lastSync(poll.pc),
                            message = "Paired with your PC. Syncing Finance now.", isError = false,
                        )
                    }
                    return syncNow()
                }
                PairPoll.Denied -> return idle("The PC said no, so nothing was paired.", error = true)
                PairPoll.Expired -> return idle("The pairing timed out. Open pairing again on the PC.", error = true)
            }
        }
        service.cancelPairing()
        idle("The PC did not approve in time. Open pairing again on the PC.", error = true)
    }

    fun cancelPairing() {
        pairingJob?.cancel()
        service.cancelPairing()
        _state.update { it.copy(phase = DevicesPhase.Idle, fingerprint = null, message = null, isError = false) }
    }

    fun syncNow() {
        if (_state.value.phase == DevicesPhase.Syncing || _state.value.phase == DevicesPhase.Contacting) return
        viewModelScope.launch {
            _state.update { it.copy(phase = DevicesPhase.Syncing, message = null, isError = false) }
            try {
                val report = service.syncNow()
                val pc = service.paired()
                _state.update {
                    it.copy(phase = DevicesPhase.Idle, pc = pc, lastSyncText = lastSync(pc), message = summary(report), isError = false)
                }
                onSynced()
            } catch (e: SyncException) {
                idle(e.message, error = true)
            }
        }
    }

    fun forget() {
        viewModelScope.launch {
            service.forget()
            _state.update {
                it.copy(pc = null, lastSyncText = null, phase = DevicesPhase.Idle, message = "This phone no longer syncs with that PC.", isError = false)
            }
        }
    }

    fun showMessage(text: String) = _state.update { it.copy(message = text, isError = true) }

    private fun idle(message: String?, error: Boolean) =
        _state.update { it.copy(phase = DevicesPhase.Idle, fingerprint = null, message = message, isError = error) }

    private fun lastSync(pc: PairedPc?): String? {
        val at = pc?.lastSyncAtSeconds ?: return if (pc == null) null else "Not synced yet"
        val minutes = (nowSeconds() - at).coerceAtLeast(0) / 60
        return when {
            minutes < 1 -> "Synced just now"
            minutes < 60 -> "Synced $minutes min ago"
            minutes < 24 * 60 -> "Synced ${minutes / 60} h ago"
            else -> "Synced ${minutes / (24 * 60)} d ago"
        }
    }

    private fun summary(report: SyncReport): String {
        val parts = mutableListOf<String>()
        if (report.sentEvents > 0) parts += "sent ${report.sentEvents}"
        if (report.applied > 0) parts += "received ${report.applied}"
        val base = if (parts.isEmpty()) "Already up to date." else "Synced: " + parts.joinToString(", ") + "."
        return if (report.conflicts > 0) "$base ${report.conflicts} amount(s) differ; see the Finance tab." else base
    }
}
