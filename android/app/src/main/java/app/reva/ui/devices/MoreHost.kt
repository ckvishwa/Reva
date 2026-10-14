package app.reva.ui.devices

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import app.reva.sync.SyncService
import app.reva.ui.more.MoreScreen

private enum class MorePage { More, Devices, Scan }

private class DevicesViewModelFactory(private val service: SyncService, private val onSynced: () -> Unit) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = DevicesViewModel(service, onSynced) as T
}

/** The More tab: the section list, with Devices (pair, sync, forget) and the QR scanner one tap away. */
@Composable
fun MoreHost(sync: SyncService?, versionName: String, onSynced: () -> Unit) {
    if (sync == null) {
        MoreScreen(versionName)
        return
    }
    val vm: DevicesViewModel = viewModel(factory = DevicesViewModelFactory(sync, onSynced))
    val state by vm.state.collectAsState()
    var page by rememberSaveable { mutableStateOf(MorePage.More) }
    LaunchedEffect(Unit) { vm.load() }
    when (page) {
        MorePage.Scan -> QrScanner(
            onCode = { text ->
                page = MorePage.Devices
                vm.onPairingCode(text)
            },
            onCancel = { page = MorePage.Devices },
        )
        MorePage.Devices -> DevicesScreen(vm, onScan = { page = MorePage.Scan }, onBack = { page = MorePage.More })
        MorePage.More -> MoreScreen(
            versionName,
            devicesSummary = state.pc?.let { "Paired with your PC. ${state.lastSyncText ?: ""}".trim() },
            onOpenDevices = { page = MorePage.Devices },
        )
    }
}
