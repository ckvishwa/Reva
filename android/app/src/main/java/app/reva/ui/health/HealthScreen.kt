package app.reva.ui.health

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import app.reva.data.HealthDaily
import app.reva.data.HealthImportReport
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import app.reva.healthconnect.HealthConnectGateway
import app.reva.healthconnect.HealthConnectImporter
import app.reva.healthconnect.HealthConnectStatus
import app.reva.healthconnect.HealthConnectType
import app.reva.healthconnect.summary
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.RevaCard
import app.reva.ui.readUpTo
import app.reva.ui.theme.RevaColors
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** What the Health screen needs to offer Health Connect. Absent on phones or tests without it. */
class HealthConnectUi(
    val gateway: HealthConnectGateway,
    val permissionFor: (HealthConnectType) -> String,
    val requestContract: ActivityResultContract<Set<String>, Set<String>>,
    val openSettings: () -> Unit,
)

/** Largest backup file read from storage; the Kernel refuses anything above 8 MB as well. */
private const val MAX_BACKUP_BYTES = 8L * 1024 * 1024

/** Manual Health entry, exact Kernel summaries, read-only Health Connect import, and backup/restore. */
@Composable
fun HealthScreen(
    repository: HealthRepository,
    modifier: Modifier = Modifier,
    healthConnect: HealthConnectUi? = null,
    onShareBackup: ((ByteArray) -> Unit)? = null,
) {
    var day by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var refresh by remember { mutableIntStateOf(0) }
    var daily by remember { mutableStateOf<HealthDaily?>(null) }
    var weekly by remember { mutableStateOf<HealthWeekly?>(null) }
    var records by remember { mutableStateOf<List<HealthRecord>>(emptyList()) }
    var schedules by remember { mutableStateOf<List<MedicationSchedule>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var activity by rememberSaveable { mutableStateOf("") }
    var workoutMinutes by rememberSaveable { mutableStateOf("") }
    var sleepMinutes by rememberSaveable { mutableStateOf("") }
    var meal by rememberSaveable { mutableStateOf("") }
    var weightKg by rememberSaveable { mutableStateOf("") }
    var steps by rememberSaveable { mutableStateOf("") }
    var heartRate by rememberSaveable { mutableStateOf("") }
    var medicationName by rememberSaveable { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(day, refresh, repository) {
        daily = null
        weekly = null
        error = null
        when (val result = repository.daily(day)) {
            is Outcome.Ok -> daily = result.value
            is Outcome.Failed -> error = result.error.message
        }
        when (val result = repository.weekly(day)) {
            is Outcome.Ok -> weekly = result.value
            is Outcome.Failed -> error = result.error.message
        }
        when (val result = repository.records(day)) {
            is Outcome.Ok -> records = result.value
            is Outcome.Failed -> error = result.error.message
        }
        when (val result = repository.schedules(day)) {
            is Outcome.Ok -> schedules = result.value
            is Outcome.Failed -> error = result.error.message
        }
    }

    fun submit(kind: String, payload: JSONObject, onSaved: () -> Unit = {}) {
        scope.launch {
            when (val result = repository.command(kind, payload)) {
                is Outcome.Ok -> { onSaved(); refresh++ }
                is Outcome.Failed -> error = result.error.message
            }
        }
    }

    LazyColumn(modifier.fillMaxSize().testTag("health_screen"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Health · local daily records") }
        item { CaptionText("Your entries stay in the encrypted Health Kernel. This summary is not medical advice.") }
        item { OutlinedTextField(day, { day = it }, label = { Text("Day (YYYY-MM-DD)") }, modifier = Modifier.testTag("health_day")) }
        item {
            RevaCard {
                CaptionText("Daily analysis")
                daily?.let {
                    Text("Workout ${if (it.workoutCount == 0) "not recorded" else "${it.workoutMinutes} min"} · " +
                        "Sleep ${if (it.sleepCount == 0) "not recorded" else "${it.sleepMinutes} min"} · Meals ${it.mealCount}")
                    Text("Weight ${it.weightGrams?.let { grams -> "${grams / 1000.0} kg" } ?: "not recorded"}")
                    Text(stepsLine(it))
                    if (it.stepsConflict) {
                        ErrorText(
                            "Your entry says ${it.stepsManual} steps; Health Connect counted ${it.stepsHealthConnect}. " +
                                "REVA uses your entry and never adds the two. Delete one of them below to keep the other.",
                            Modifier.testTag("health_steps_conflict"),
                        )
                    }
                    Text("Heart rate ${if (it.heartRateCount == 0) "not recorded" else "${it.heartRateMinBpm}-${it.heartRateMaxBpm} bpm in ${it.heartRateCount} samples"}")
                    Text("Medication taken ${it.medicationsTaken} of ${it.medicationsScheduled} scheduled")
                    CaptionText("${it.sourceCount} source records")
                } ?: CaptionText("No verified daily summary available")
                error?.let { ErrorText(it) }
            }
        }
        item {
            RevaCard {
                CaptionText("Seven days ending $day")
                weekly?.let {
                    Text("Sleep ${if (it.sleepCount == 0) "not recorded" else "${it.sleepMinutes} min in ${it.sleepCount} sessions"}")
                    Text("Workout ${if (it.workoutCount == 0) "not recorded" else "${it.workoutMinutes} min in ${it.workoutCount} entries"} · Meals recorded ${it.mealCount}")
                    Text("Medication marked taken ${it.medicationTaken} of ${it.medicationExpected} scheduled entries")
                    Text("Steps ${if (it.stepsDays == 0) "not recorded" else "${it.stepsTotal} across ${it.stepsDays} days"}")
                    if (it.stepsConflictDates.isNotEmpty()) {
                        CaptionText("Your entry and Health Connect differ on ${it.stepsConflictDates.joinToString()}; your entry is used.")
                    }
                    Text("Heart rate ${if (it.heartRateCount == 0) "not recorded" else "${it.heartRateMinBpm}-${it.heartRateMaxBpm} bpm in ${it.heartRateCount} samples"}")
                    CaptionText("${it.sourceCount} source records")
                } ?: CaptionText("No verified seven-day summary available")
            }
        }
        if (healthConnect != null) {
            item { HealthConnectCard(healthConnect, repository, onChanged = { refresh++ }) }
        }
        manualForms(
            day = day,
            records = records,
            schedules = schedules,
            fields = ManualFields(activity, workoutMinutes, sleepMinutes, meal, weightKg, steps, heartRate, medicationName),
            onField = { field, value ->
                when (field) {
                    "activity" -> activity = value
                    "workoutMinutes" -> workoutMinutes = value
                    "sleepMinutes" -> sleepMinutes = value
                    "meal" -> meal = value
                    "weightKg" -> weightKg = value
                    "steps" -> steps = value
                    "heartRate" -> heartRate = value
                    "medicationName" -> medicationName = value
                }
            },
            onError = { error = it },
            submit = ::submit,
        )
        item { BackupCard(repository, onShareBackup, onRestored = { refresh++ }) }
    }
}

private fun stepsLine(day: HealthDaily): String = when {
    day.stepsCount == 0 -> "Steps not recorded"
    day.stepsSource == "health_connect" -> "Steps ${day.steps} · from Health Connect"
    else -> "Steps ${day.steps}"
}

private data class ManualFields(
    val activity: String,
    val workoutMinutes: String,
    val sleepMinutes: String,
    val meal: String,
    val weightKg: String,
    val steps: String,
    val heartRate: String,
    val medicationName: String,
)

private fun LazyListScope.manualForms(
    day: String,
    records: List<HealthRecord>,
    schedules: List<MedicationSchedule>,
    fields: ManualFields,
    onField: (String, String) -> Unit,
    onError: (String) -> Unit,
    submit: (String, JSONObject, () -> Unit) -> Unit,
) {
    item {
        RevaCard {
            CaptionText("Log workout")
            OutlinedTextField(fields.activity, { onField("activity", it) }, label = { Text("Activity") })
            OutlinedTextField(fields.workoutMinutes, { onField("workoutMinutes", it) }, label = { Text("Minutes") })
            Button(onClick = {
                val minutes = fields.workoutMinutes.toLongOrNull()
                if (minutes == null) onError("Enter whole workout minutes.")
                else submit("workout.log", JSONObject().put("date", day).put("activity", fields.activity).put("duration_minutes", minutes)) { onField("activity", ""); onField("workoutMinutes", "") }
            }, modifier = Modifier.testTag("health_log_workout")) { Text("Save workout") }
        }
    }
    item {
        RevaCard {
            CaptionText("Log sleep ending this day")
            OutlinedTextField(fields.sleepMinutes, { onField("sleepMinutes", it) }, label = { Text("Minutes slept") })
            Button(onClick = {
                val minutes = fields.sleepMinutes.toLongOrNull()
                if (minutes == null) onError("Enter whole sleep minutes.")
                else submit("sleep.log", JSONObject().put("date", day).put("duration_minutes", minutes)) { onField("sleepMinutes", "") }
            }, modifier = Modifier.testTag("health_log_sleep")) { Text("Save sleep") }
        }
    }
    item {
        RevaCard {
            CaptionText("Log meal")
            OutlinedTextField(fields.meal, { onField("meal", it) }, label = { Text("Meal description") })
            Button(onClick = { submit("meal.log", JSONObject().put("date", day).put("description", fields.meal)) { onField("meal", "") } }, modifier = Modifier.testTag("health_log_meal")) { Text("Save meal") }
        }
    }
    item {
        RevaCard {
            CaptionText("Log weight")
            OutlinedTextField(fields.weightKg, { onField("weightKg", it) }, label = { Text("Kilograms") })
            Button(onClick = {
                val grams = fields.weightKg.toBigDecimalOrNull()?.multiply(java.math.BigDecimal(1000))?.toLongExactOrNull()
                if (grams == null) onError("Enter weight in kilograms, up to three decimal places.")
                else submit("weight.log", JSONObject().put("date", day).put("weight_grams", grams)) { onField("weightKg", "") }
            }, modifier = Modifier.testTag("health_log_weight")) { Text("Save weight") }
        }
    }
    item {
        RevaCard {
            CaptionText("Log steps for this day")
            OutlinedTextField(fields.steps, { onField("steps", it) }, label = { Text("Steps counted") })
            Button(onClick = {
                val count = fields.steps.toLongOrNull()
                if (count == null) onError("Enter a whole step count.")
                else submit("steps.log", JSONObject().put("date", day).put("steps", count)) { onField("steps", "") }
            }, modifier = Modifier.testTag("health_log_steps")) { Text("Save steps") }
        }
    }
    item {
        RevaCard {
            CaptionText("Log a heart-rate reading · no medical interpretation")
            OutlinedTextField(fields.heartRate, { onField("heartRate", it) }, label = { Text("Beats per minute") })
            Button(onClick = {
                val bpm = fields.heartRate.toLongOrNull()
                if (bpm == null) onError("Enter whole beats per minute.")
                else submit("heart_rate.log", JSONObject().put("date", day).put("bpm", bpm)) { onField("heartRate", "") }
            }, modifier = Modifier.testTag("health_log_heart_rate")) { Text("Save reading") }
        }
    }
    item {
        RevaCard {
            CaptionText("Daily medication schedule · name only; no dose advice")
            OutlinedTextField(fields.medicationName, { onField("medicationName", it) }, label = { Text("Medication name") })
            Button(onClick = { submit("medication.schedule", JSONObject().put("start_date", day).put("name", fields.medicationName)) { onField("medicationName", "") } }, modifier = Modifier.testTag("health_schedule_medication")) { Text("Add daily schedule") }
            schedules.forEach { schedule ->
                Text(schedule.name)
                val taken = records.any { it.kind == "medication_taken" && it.scheduleId == schedule.id }
                Button(onClick = { submit("medication.mark_taken", JSONObject().put("schedule_id", schedule.id).put("date", day)) {} },
                    enabled = !taken, modifier = Modifier.testTag("health_mark_taken")) { Text(if (taken) "Taken today" else "Mark taken today") }
                Button(onClick = { submit("record.delete", JSONObject().put("id", schedule.id)) {} }) { Text("Delete schedule and its history") }
            }
        }
    }
    item {
        RevaCard {
            CaptionText("Entries on $day")
            if (records.isEmpty()) CaptionText("No entries recorded")
            records.forEach { record ->
                Text(record.label)
                if (record.origins.isNotEmpty()) CaptionText("Recorded by ${record.origins.joinToString()}")
                Button(onClick = { submit("record.delete", JSONObject().put("id", record.id)) {} }) { Text("Delete entry") }
            }
        }
    }
}

/**
 * Read-only Health Connect: one permission request per data type, the granted set re-read whenever the screen
 * resumes (the user may have changed it in system settings), and a way to forget everything copied from it.
 */
@Composable
private fun HealthConnectCard(ui: HealthConnectUi, repository: HealthRepository, onChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    val importer = remember(ui, repository) { HealthConnectImporter(ui.gateway, repository) }
    var status by remember { mutableStateOf<HealthConnectStatus?>(null) }
    var granted by remember { mutableStateOf<Set<HealthConnectType>?>(null) }
    var everGranted by remember { mutableStateOf<Set<HealthConnectType>>(emptySet()) }
    var recheck by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var confirmForget by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ui.requestContract) { recheck++ }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_RESUME) recheck++ }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(recheck) {
        val current = withContext(Dispatchers.IO) { ui.gateway.status() }
        status = current
        granted = if (current == HealthConnectStatus.Available) {
            withContext(Dispatchers.IO) { runCatching { ui.gateway.grantedTypes() }.getOrNull() }
        } else {
            emptySet()
        }
        granted?.let { everGranted = everGranted + it }
    }

    RevaCard(modifier = Modifier.testTag("health_connect_card")) {
        CaptionText("Health Connect · read only")
        Text("REVA can copy daily totals from Health Connect into this phone's encrypted Health store. It never writes to Health Connect.")
        when (status) {
            null -> CaptionText("Checking Health Connect…")
            HealthConnectStatus.Unavailable -> CaptionText("Health Connect is not available on this phone.")
            HealthConnectStatus.NeedsUpdate -> CaptionText("Health Connect needs an update before REVA can read from it.")
            HealthConnectStatus.Available -> {
                HealthConnectType.entries.forEach { type ->
                    val allowed = granted?.contains(type) == true
                    Text("${type.label}: ${if (allowed) "allowed" else "not allowed"}", Modifier.testTag("health_connect_state_${type.name}"))
                    CaptionText(type.reason)
                    if (!allowed && type in everGranted) {
                        CaptionText("Access was turned off. Days already copied stay in REVA until you delete them below.")
                    }
                    if (!allowed) {
                        TextButton(onClick = { launcher.launch(setOf(ui.permissionFor(type))) }, modifier = Modifier.testTag("health_connect_allow_${type.name}")) {
                            Text("Allow ${type.label.lowercase()}")
                        }
                    }
                }
                Button(
                    onClick = {
                        busy = true
                        scope.launch {
                            val result = importer.import()
                            message = result.summary()
                            busy = false
                            recheck++
                            onChanged()
                        }
                    },
                    enabled = !busy && granted?.isNotEmpty() == true,
                    modifier = Modifier.testTag("health_connect_import"),
                ) { Text(if (busy) "Reading…" else "Copy the last 30 days") }
                TextButton(onClick = ui.openSettings, modifier = Modifier.testTag("health_connect_settings")) { Text("Manage access in Health Connect") }
            }
        }
        message?.let { CaptionText(it, Modifier.testTag("health_connect_result")) }
        TextButton(onClick = { confirmForget = true }, modifier = Modifier.testTag("health_connect_forget")) { Text("Delete everything copied from Health Connect") }
    }

    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text("Delete copied Health Connect data?") },
            text = { Text("This removes every day REVA copied from Health Connect. Those days are not copied again later. Your own entries and Health Connect itself are not changed.") },
            containerColor = RevaColors.Surface,
            confirmButton = {
                TextButton(onClick = {
                    confirmForget = false
                    scope.launch {
                        message = when (val result = repository.command("source.delete", JSONObject().put("source", "health_connect"))) {
                            is Outcome.Ok -> "Deleted everything copied from Health Connect."
                            is Outcome.Failed -> result.error.message
                        }
                        onChanged()
                    }
                }, modifier = Modifier.testTag("health_connect_forget_confirm")) { Text("Delete") }
            },
            dismissButton = { TextButton(onClick = { confirmForget = false }) { Text("Cancel") } },
        )
    }
}

/** Plain JSON backup through the share sheet, and restore from a picked file with a dry run first. */
@Composable
private fun BackupCard(repository: HealthRepository, onShare: ((ByteArray) -> Unit)?, onRestored: () -> Unit) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var confirmExport by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<ByteArray?>(null) }
    var preview by remember { mutableStateOf<HealthImportReport?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var restoring by remember { mutableStateOf(false) }
    // The card is the last item of a long list and grows downward. Bring what has just appeared into view,
    // so a preview, its confirm button or a result is never left below the fold (GYM-02.1).
    val previewInView = remember { BringIntoViewRequester() }
    val messageInView = remember { BringIntoViewRequester() }
    LaunchedEffect(preview) { if (preview != null) previewInView.bringIntoView() }
    LaunchedEffect(message) { if (message != null) messageInView.bringIntoView() }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        // Backing out of the picker changes nothing; choosing a file starts a new restore, so the last
        // result and any old preview go before the new file is read.
        if (uri == null) return@rememberLauncherForActivityResult
        message = null
        preview = null
        pending = null
        scope.launch {
            val bytes = withContext(Dispatchers.IO) {
                runCatching { context.contentResolver.openInputStream(uri)?.use { readUpTo(it, MAX_BACKUP_BYTES + 1) } }.getOrNull()
            }
            when {
                bytes == null -> message = "That file could not be read."
                bytes.size > MAX_BACKUP_BYTES -> message = "That file is larger than 8 MB."
                else -> when (val result = repository.importData("json", bytes, dryRun = true)) {
                    is Outcome.Ok -> { pending = bytes; preview = result.value }
                    is Outcome.Failed -> message = result.error.message
                }
            }
        }
    }

    RevaCard(modifier = Modifier.testTag("health_backup_card")) {
        CaptionText("Backup")
        Text("Save every Health record as a JSON file, or restore one. Restoring never replaces or brings back records deleted on this phone.")
        if (onShare != null) {
            TextButton(onClick = { confirmExport = true }, modifier = Modifier.testTag("health_export")) { Text("Share a Health backup") }
        }
        TextButton(onClick = { picker.launch(arrayOf("application/json", "*/*")) }, modifier = Modifier.testTag("health_restore")) { Text("Restore from a backup file") }
        preview?.let { report ->
            Column(Modifier.bringIntoViewRequester(previewInView), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("This file has ${countText(report)}, ${report.duplicates} already here and ${report.rejected.size} that cannot be restored.", Modifier.testTag("health_restore_preview"))
                report.rejected.take(5).forEach { CaptionText(it) }
                Button(onClick = {
                    val bytes = pending ?: return@Button
                    // One restore at a time: a second tap while the Kernel is committing must not start another
                    // and overwrite the first one's result.
                    if (restoring) return@Button
                    restoring = true
                    scope.launch {
                        // The result line is written only from what the Kernel returned after it committed.
                        message = try {
                            when (val result = repository.importData("json", bytes, dryRun = false)) {
                                is Outcome.Ok -> "Restored ${countText(result.value, fresh = false)}; ${result.value.duplicates} were already here; ${result.value.rejected.size} skipped."
                                is Outcome.Failed -> result.error.message
                            }
                        } finally {
                            restoring = false
                        }
                        preview = null
                        pending = null
                        onRestored()
                    }
                }, enabled = !restoring && report.added + report.deletions > 0, modifier = Modifier.testTag("health_restore_confirm")) {
                    Text(if (restoring) "Restoring…" else "Restore ${countText(report)}")
                }
                TextButton(onClick = { preview = null; pending = null }, enabled = !restoring) { Text("Cancel") }
            }
        }
        message?.let { CaptionText(it, Modifier.testTag("health_backup_result").bringIntoViewRequester(messageInView)) }
    }

    if (confirmExport && onShare != null) {
        AlertDialog(
            onDismissRequest = { confirmExport = false },
            title = { Text("Share a Health backup?") },
            text = { Text("The backup is a plain, unencrypted file with every Health record. Share it only with apps and people you trust.") },
            containerColor = RevaColors.Surface,
            confirmButton = {
                TextButton(onClick = {
                    confirmExport = false
                    scope.launch {
                        when (val result = repository.exportJson()) {
                            is Outcome.Ok -> onShare(result.value)
                            is Outcome.Failed -> message = result.error.message
                        }
                    }
                }, modifier = Modifier.testTag("health_export_confirm")) { Text("Share") }
            },
            dismissButton = { TextButton(onClick = { confirmExport = false }) { Text("Cancel") } },
        )
    }
}

/** "10 new records and 2 deletions": records and deletions are counted apart. */
internal fun countText(report: HealthImportReport, fresh: Boolean = true): String {
    val noun = if (fresh) "new record" else "record"
    val records = if (report.added == 1) "1 $noun" else "${report.added} ${noun}s"
    return when (report.deletions) {
        0 -> records
        1 -> "$records and 1 deletion"
        else -> "$records and ${report.deletions} deletions"
    }
}

private fun java.math.BigDecimal.toLongExactOrNull(): Long? = try { longValueExact() } catch (_: ArithmeticException) { null }
