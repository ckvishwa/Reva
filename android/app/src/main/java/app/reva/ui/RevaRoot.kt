@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package app.reva.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import app.reva.data.FinanceRepository
import app.reva.data.Outcome
import app.reva.ui.finance.AddAccountForm
import app.reva.ui.finance.AddAccountViewModel
import app.reva.ui.finance.AddTransactionForm
import app.reva.ui.finance.AddTransactionViewModel
import app.reva.ui.finance.FinanceScreen
import app.reva.ui.finance.FinanceViewModel
import app.reva.ui.finance.FormSheet
import app.reva.ui.finance.ImportForm
import app.reva.ui.finance.ImportViewModel
import app.reva.sync.AutoSyncController
import app.reva.sync.SyncService
import app.reva.ui.devices.MoreHost
import app.reva.ui.more.TalkUnavailableScreen
import app.reva.ui.talk.TalkScreen
import app.reva.pcrequests.PcRequestTracker
import app.reva.phone.ApprovedApps
import app.reva.phone.LaunchableApps
import app.reva.phone.PhoneActions
import app.reva.voice.VoiceController
import app.reva.brain.ModeController
import app.reva.brain.HostedSecrets
import app.reva.ui.theme.RevaColors
import app.reva.ui.today.TodayScreen
import app.reva.ui.today.TodayViewModel
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private enum class Tab(val label: String, val icon: ImageVector, val tag: String) {
    Today("Today", Icons.Filled.Home, "tab_today"),
    Finance("Finance", Icons.AutoMirrored.Filled.List, "tab_finance"),
    Talk("Talk", Icons.Filled.Face, "tab_talk"),
    More("More", Icons.Filled.Menu, "tab_more"),
}

private enum class Sheet { None, AddTransaction, AddAccount, Import }

private class RootViewModels(private val repository: FinanceRepository) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = when (modelClass) {
        TodayViewModel::class.java -> TodayViewModel(repository)
        FinanceViewModel::class.java -> FinanceViewModel(repository)
        else -> error("unknown view model $modelClass")
    } as T
}

/** The whole app below the activity: bottom navigation, the four tabs, and the Finance sheets. */
@Composable
fun RevaRoot(
    repository: FinanceRepository,
    versionName: String,
    onShare: (format: String, bytes: ByteArray) -> Unit,
    sync: SyncService? = null,
    autoSync: AutoSyncController? = null,
    voice: VoiceController? = null,
    pcRequests: PcRequestTracker? = null,
    phoneActions: PhoneActions? = null,
    phoneApps: Pair<ApprovedApps, LaunchableApps>? = null,
    modes: ModeController? = null,
    hostedSecrets: HostedSecrets? = null,
    refreshModes: suspend () -> Unit = {},
    cancelBrainTurn: () -> Unit = {},
    onBeforeMicRequest: () -> Unit = {},
    onOpenAppSettings: () -> Unit = {},
) {
    val factory = remember(repository) { RootViewModels(repository) }
    val today: TodayViewModel = viewModel(factory = factory)
    val finance: FinanceViewModel = viewModel(factory = factory)
    var tab by rememberSaveable { mutableIntStateOf(Tab.Today.ordinal) }
    var sheet by rememberSaveable { mutableStateOf(Sheet.None) }
    var pendingExport by remember { mutableStateOf<String?>(null) }
    var exportError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val syncStatus = autoSync?.status?.collectAsState()?.value?.text

    LaunchedEffect(modes, autoSync) {
        if (modes != null) {
            while (true) {
                refreshModes()
                kotlinx.coroutines.delay(15_000)
            }
        }
    }
    LaunchedEffect(modes) {
        modes?.state?.collect { cancelBrainTurn() }
    }

    // Sync with the paired PC on its own while the app is in front (the setting is on the Devices screen).
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, autoSync) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> autoSync?.onForeground()
                Lifecycle.Event.ON_STOP -> autoSync?.onBackground()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            autoSync?.onBackground()
        }
    }

    // Opening a tab reloads it from the Kernel (off the main thread), so it never shows stale numbers.
    LaunchedEffect(tab) {
        when (Tab.entries[tab]) {
            Tab.Today -> today.refresh()
            Tab.Finance -> finance.refresh()
            else -> Unit
        }
    }

    fun saved() {
        sheet = Sheet.None
        finance.refresh()
        today.refresh()
    }

    Scaffold(
        containerColor = RevaColors.Ground,
        contentColor = RevaColors.Text,
        bottomBar = {
            NavigationBar(containerColor = RevaColors.Nav, contentColor = RevaColors.Secondary) {
                Tab.entries.forEach { entry ->
                    NavigationBarItem(
                        selected = tab == entry.ordinal,
                        onClick = { tab = entry.ordinal },
                        icon = { Icon(entry.icon, contentDescription = null) },
                        label = { Text(entry.label) },
                        modifier = Modifier.testTag(entry.tag),
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = RevaColors.Ground,
                            selectedTextColor = RevaColors.Accent,
                            indicatorColor = RevaColors.Accent,
                            unselectedIconColor = RevaColors.Secondary,
                            unselectedTextColor = RevaColors.Secondary,
                        ),
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when (Tab.entries[tab]) {
                Tab.Today -> TodayScreen(today, syncStatus = syncStatus)
                Tab.Finance -> FinanceScreen(
                    vm = finance,
                    onAddTransaction = { sheet = Sheet.AddTransaction },
                    onAddAccount = { sheet = Sheet.AddAccount },
                    onImport = { sheet = Sheet.Import },
                    onExport = { pendingExport = it },
                    syncStatus = syncStatus,
                )
                Tab.Talk ->
                    if (voice != null) TalkScreen(voice, onBeforeMicRequest, onOpenAppSettings, pcRequests, phoneActions, modes) else TalkUnavailableScreen()
                Tab.More -> MoreHost(
                    sync,
                    versionName,
                    onSynced = { finance.refresh(); today.refresh(); scope.launch { autoSync?.manualSyncSucceeded() } },
                    autoSync = autoSync,
                    phoneApps = phoneApps,
                    modes = modes,
                    saveHostedKey = { key ->
                        if (hostedSecrets == null) false else withContext(Dispatchers.IO) {
                            val stored = runCatching { hostedSecrets.save(key) }.isSuccess
                            refreshModes()
                            stored
                        }
                    },
                    clearHostedKey = {
                        withContext(Dispatchers.IO) { hostedSecrets?.clear(); refreshModes() }
                    },
                )
            }
        }
    }

    when (sheet) {
        Sheet.None -> Unit
        Sheet.AddTransaction -> FormSheet(onDismiss = { sheet = Sheet.None }) {
            val vm = remember { AddTransactionViewModel.create(repository, finance.accountsForForms, finance.categoriesForForms, LocalDate.now()) }
            AddTransactionForm(vm, onSaved = ::saved, onCancel = { sheet = Sheet.None })
        }
        Sheet.AddAccount -> FormSheet(onDismiss = { sheet = Sheet.None }) {
            val vm = remember { AddAccountViewModel(repository) }
            AddAccountForm(vm, onSaved = ::saved, onCancel = { sheet = Sheet.None })
        }
        Sheet.Import -> FormSheet(onDismiss = { saved() }) {
            val vm = remember { ImportViewModel.create(repository, finance.accountsForForms) }
            val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                if (uri != null) scope.launch { readPicked(context.contentResolver, uri, vm) }
            }
            // An import may have saved rows even if the sheet is closed afterwards, so closing always reloads.
            ImportForm(vm, onChooseFile = { picker.launch(arrayOf("*/*")) }, onClose = { saved() })
        }
    }

    pendingExport?.let { format ->
        AlertDialog(
            onDismissRequest = { pendingExport = null },
            title = { Text(if (format == "json") "Share a JSON backup?" else "Share transactions as CSV?") },
            text = { Text("The export is a plain, unencrypted file. Share it only with apps and people you trust.") },
            containerColor = RevaColors.Surface,
            confirmButton = {
                TextButton(
                    onClick = {
                        pendingExport = null
                        scope.launch {
                            when (val result = finance.export(format)) {
                                is Outcome.Ok -> onShare(format, result.value)
                                is Outcome.Failed -> exportError = result.error.message
                            }
                        }
                    },
                    modifier = Modifier.testTag("export_confirm"),
                ) { Text("Share") }
            },
            dismissButton = { TextButton(onClick = { pendingExport = null }) { Text("Cancel") } },
        )
    }
    exportError?.let {
        AlertDialog(
            onDismissRequest = { exportError = null },
            title = { Text("Export failed") },
            text = { Text(it) },
            containerColor = RevaColors.Surface,
            confirmButton = { TextButton(onClick = { exportError = null }) { Text("OK") } },
        )
    }
}

/** Reads the picked document off the main thread, refusing anything over the Kernel's 8 MB import limit. */
private suspend fun readPicked(resolver: android.content.ContentResolver, uri: Uri, vm: ImportViewModel) {
    val name = withContext(Dispatchers.IO) {
        runCatching {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                if (it.moveToFirst()) it.getString(0) else null
            }
        }.getOrNull()
    } ?: "file"
    val bytes = withContext(Dispatchers.IO) {
        runCatching {
            resolver.openInputStream(uri)?.use { readUpTo(it, ImportViewModel.MAX_FILE_BYTES + 1) }
        }.getOrNull()
    }
    when {
        bytes == null -> vm.rejectUnreadable(name)
        bytes.size > ImportViewModel.MAX_FILE_BYTES -> vm.rejectTooLarge(name)
        else -> vm.loadFile(name, bytes)
    }
}

/** Reads at most [limit] bytes. (InputStream.readNBytes needs Android 13; this app supports Android 12.) */
internal fun readUpTo(stream: java.io.InputStream, limit: Long): ByteArray {
    val out = java.io.ByteArrayOutputStream()
    val buffer = ByteArray(64 * 1024)
    var total = 0L
    while (total < limit) {
        val read = stream.read(buffer, 0, minOf(buffer.size.toLong(), limit - total).toInt())
        if (read < 0) break
        out.write(buffer, 0, read)
        total += read
    }
    return out.toByteArray()
}
