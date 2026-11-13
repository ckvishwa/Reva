@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package app.reva.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Favorite
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
import app.reva.data.GymRepository
import app.reva.data.HealthRepository
import app.reva.data.Outcome
import app.reva.ui.finance.AddAccountForm
import app.reva.ui.finance.AddAccountViewModel
import app.reva.ui.finance.AddTransactionForm
import app.reva.ui.finance.AddTransactionViewModel
import app.reva.ui.finance.FinanceScreen
import app.reva.ui.finance.FinanceManageForm
import app.reva.ui.gym.GymHost
import app.reva.ui.health.HealthConnectUi
import app.reva.ui.health.HealthScreen
import app.reva.ui.life.LifeArea
import app.reva.ui.life.LifeAreaBar
import app.reva.ui.life.LifePins
import app.reva.ui.life.LifeScreen
import app.reva.ui.life.SharedPrefsLifePinStore
import app.reva.ui.finance.FinanceViewModel
import app.reva.ui.finance.FormSheet
import app.reva.ui.finance.ImportForm
import app.reva.ui.finance.ImportViewModel
import app.reva.sync.AutoSyncController
import app.reva.sync.SyncService
import app.reva.ui.devices.MoreHost
import app.reva.ui.gmail.GmailConnectUi
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

/**
 * The five destinations of ARD-210 section 4. Finance, Health and Gym live inside Life. Plan is declared but
 * not [built] until the Kernel plan aggregate exists (slice PLAN-1); a tab that is not built is not shown.
 */
internal enum class Tab(val label: String, val icon: ImageVector, val tag: String, val built: Boolean = true) {
    Today("Today", Icons.Filled.Home, "tab_today"),
    Plan("Plan", Icons.Filled.DateRange, "tab_plan", built = false),
    Talk("Talk", Icons.Filled.Face, "tab_talk"),
    Life("Life", Icons.Filled.Favorite, "tab_life"),
    More("More", Icons.Filled.Menu, "tab_more");

    companion object {
        val visible: List<Tab> get() = entries.filter { it.built }

        /** A saved tab name from an older build, or one that is no longer shown, falls back to Today. */
        fun restore(name: String?): Tab = visible.firstOrNull { it.name == name } ?: Today
    }
}

private enum class Sheet { None, AddTransaction, AddAccount, Import, ManageFinance }

private class RootViewModels(private val repository: FinanceRepository) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T = when (modelClass) {
        TodayViewModel::class.java -> TodayViewModel(repository)
        FinanceViewModel::class.java -> FinanceViewModel(repository)
        else -> error("unknown view model $modelClass")
    } as T
}

/** The whole app below the activity: bottom navigation, the tabs, the Life hub and the Finance sheets. */
@Composable
fun RevaRoot(
    repository: FinanceRepository,
    versionName: String,
    onShare: (format: String, bytes: ByteArray) -> Unit,
    healthRepository: HealthRepository? = null,
    gymRepository: GymRepository? = null,
    healthConnect: HealthConnectUi? = null,
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
    gmail: GmailConnectUi? = null,
) {
    val factory = remember(repository) { RootViewModels(repository) }
    val today: TodayViewModel = viewModel(factory = factory)
    val finance: FinanceViewModel = viewModel(factory = factory)
    var tabName by rememberSaveable { mutableStateOf(Tab.Today.name) }
    val tab = Tab.restore(tabName)
    // Which domain is open inside Life; null is the hub. Kept across tab switches and rotation.
    var lifeAreaKey by rememberSaveable { mutableStateOf<String?>(null) }
    val lifeArea = LifeArea.fromKey(lifeAreaKey)
    val availableAreas = remember(healthRepository, gymRepository) {
        buildSet {
            add(LifeArea.Finance)
            if (healthRepository != null) add(LifeArea.Health)
            if (gymRepository != null) add(LifeArea.Gym)
        }
    }
    var sheet by rememberSaveable { mutableStateOf(Sheet.None) }
    var pendingExport by remember { mutableStateOf<String?>(null) }
    var exportError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifePins = remember {
        LifePins(SharedPrefsLifePinStore(context.getSharedPreferences("reva_life", android.content.Context.MODE_PRIVATE)))
    }
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
    LaunchedEffect(tab, lifeArea) {
        when {
            tab == Tab.Today -> today.refresh()
            tab == Tab.Life && lifeArea == LifeArea.Finance -> finance.refresh()
            else -> Unit
        }
    }

    // Back from a domain opened in Life returns to the hub instead of leaving the app.
    BackHandler(enabled = tab == Tab.Life && lifeArea != null) { lifeAreaKey = null }

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
                Tab.visible.forEach { entry ->
                    NavigationBarItem(
                        selected = tab == entry,
                        onClick = {
                            // Tapping Life while already on it returns to the hub; switching tabs keeps your place.
                            if (entry == Tab.Life && tab == Tab.Life) lifeAreaKey = null
                            tabName = entry.name
                        },
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
            when (tab) {
                Tab.Today -> TodayScreen(today, syncStatus = syncStatus, healthRepository = healthRepository)
                Tab.Plan -> Unit // not built: never selected, see Tab.restore
                Tab.Life -> when (lifeArea?.takeIf { it in availableAreas }) {
                    null -> LifeScreen(lifePins, availableAreas, onOpen = { lifeAreaKey = it.key })
                    LifeArea.Finance -> LifeAreaHost(LifeArea.Finance, onBack = { lifeAreaKey = null }) {
                        FinanceScreen(
                            vm = finance,
                            onAddTransaction = { sheet = Sheet.AddTransaction },
                            onAddAccount = { sheet = Sheet.AddAccount },
                            onImport = { sheet = Sheet.Import },
                            onManage = { sheet = Sheet.ManageFinance },
                            onExport = { pendingExport = it },
                            syncStatus = syncStatus,
                        )
                    }
                    LifeArea.Health -> LifeAreaHost(LifeArea.Health, onBack = { lifeAreaKey = null }) {
                        HealthScreen(healthRepository!!, healthConnect = healthConnect, onShareBackup = { bytes -> onShare(ExportShare.HEALTH_JSON, bytes) })
                    }
                    LifeArea.Gym -> LifeAreaHost(LifeArea.Gym, onBack = { lifeAreaKey = null }) {
                        GymHost(gymRepository!!)
                    }
                }
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
                    gmail = gmail,
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
        Sheet.ManageFinance -> FormSheet(onDismiss = { saved() }) {
            FinanceManageForm(repository)
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

@Composable
private fun LifeAreaHost(area: LifeArea, onBack: () -> Unit, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        LifeAreaBar(area, onBack)
        Box(Modifier.weight(1f)) { content() }
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
