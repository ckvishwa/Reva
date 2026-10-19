package app.reva.ui.health

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import app.reva.data.HealthDaily
import app.reva.data.HealthRecord
import app.reva.data.HealthRepository
import app.reva.data.HealthWeekly
import app.reva.data.MedicationSchedule
import app.reva.data.Outcome
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.RevaCard
import java.time.LocalDate
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Manual Health entry and an exact daily summary computed by the local encrypted Kernel. */
@Composable
fun HealthScreen(repository: HealthRepository, modifier: Modifier = Modifier) {
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
                    Text("Steps ${if (it.stepsCount == 0) "not recorded" else it.steps.toString()}")
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
                    Text("Heart rate ${if (it.heartRateCount == 0) "not recorded" else "${it.heartRateMinBpm}-${it.heartRateMaxBpm} bpm in ${it.heartRateCount} samples"}")
                    CaptionText("${it.sourceCount} source records")
                } ?: CaptionText("No verified seven-day summary available")
            }
        }
        item {
            RevaCard {
                CaptionText("Log workout")
                OutlinedTextField(activity, { activity = it }, label = { Text("Activity") })
                OutlinedTextField(workoutMinutes, { workoutMinutes = it }, label = { Text("Minutes") })
                Button(onClick = {
                    val minutes = workoutMinutes.toLongOrNull()
                    if (minutes == null) error = "Enter whole workout minutes."
                    else submit("workout.log", JSONObject().put("date", day).put("activity", activity).put("duration_minutes", minutes)) { activity = ""; workoutMinutes = "" }
                }, modifier = Modifier.testTag("health_log_workout")) { Text("Save workout") }
            }
        }
        item {
            RevaCard {
                CaptionText("Log sleep ending this day")
                OutlinedTextField(sleepMinutes, { sleepMinutes = it }, label = { Text("Minutes slept") })
                Button(onClick = {
                    val minutes = sleepMinutes.toLongOrNull()
                    if (minutes == null) error = "Enter whole sleep minutes."
                    else submit("sleep.log", JSONObject().put("date", day).put("duration_minutes", minutes)) { sleepMinutes = "" }
                }, modifier = Modifier.testTag("health_log_sleep")) { Text("Save sleep") }
            }
        }
        item {
            RevaCard {
                CaptionText("Log meal")
                OutlinedTextField(meal, { meal = it }, label = { Text("Meal description") })
                Button(onClick = { submit("meal.log", JSONObject().put("date", day).put("description", meal)) { meal = "" } }, modifier = Modifier.testTag("health_log_meal")) { Text("Save meal") }
            }
        }
        item {
            RevaCard {
                CaptionText("Log weight")
                OutlinedTextField(weightKg, { weightKg = it }, label = { Text("Kilograms") })
                Button(onClick = {
                    val grams = weightKg.toBigDecimalOrNull()?.multiply(java.math.BigDecimal(1000))?.toLongExactOrNull()
                    if (grams == null) error = "Enter weight in kilograms, up to three decimal places."
                    else submit("weight.log", JSONObject().put("date", day).put("weight_grams", grams)) { weightKg = "" }
                }, modifier = Modifier.testTag("health_log_weight")) { Text("Save weight") }
            }
        }
        item {
            RevaCard {
                CaptionText("Log steps for this day")
                OutlinedTextField(steps, { steps = it }, label = { Text("Steps counted") })
                Button(onClick = {
                    val count = steps.toLongOrNull()
                    if (count == null) error = "Enter a whole step count."
                    else submit("steps.log", JSONObject().put("date", day).put("steps", count)) { steps = "" }
                }, modifier = Modifier.testTag("health_log_steps")) { Text("Save steps") }
            }
        }
        item {
            RevaCard {
                CaptionText("Log a heart-rate reading · no medical interpretation")
                OutlinedTextField(heartRate, { heartRate = it }, label = { Text("Beats per minute") })
                Button(onClick = {
                    val bpm = heartRate.toLongOrNull()
                    if (bpm == null) error = "Enter whole beats per minute."
                    else submit("heart_rate.log", JSONObject().put("date", day).put("bpm", bpm)) { heartRate = "" }
                }, modifier = Modifier.testTag("health_log_heart_rate")) { Text("Save reading") }
            }
        }
        item {
            RevaCard {
                CaptionText("Daily medication schedule · name only; no dose advice")
                OutlinedTextField(medicationName, { medicationName = it }, label = { Text("Medication name") })
                Button(onClick = { submit("medication.schedule", JSONObject().put("start_date", day).put("name", medicationName)) { medicationName = "" } }, modifier = Modifier.testTag("health_schedule_medication")) { Text("Add daily schedule") }
                schedules.forEach { schedule ->
                    Text(schedule.name)
                    val taken = records.any { it.kind == "medication_taken" && it.scheduleId == schedule.id }
                    Button(onClick = { submit("medication.mark_taken", JSONObject().put("schedule_id", schedule.id).put("date", day)) },
                        enabled = !taken, modifier = Modifier.testTag("health_mark_taken")) { Text(if (taken) "Taken today" else "Mark taken today") }
                    Button(onClick = { submit("record.delete", JSONObject().put("id", schedule.id)) }) { Text("Delete schedule and its history") }
                }
            }
        }
        item {
            RevaCard {
                CaptionText("Entries on $day")
                if (records.isEmpty()) CaptionText("No entries recorded")
                records.forEach { record ->
                    Text(record.label)
                    Button(onClick = { submit("record.delete", JSONObject().put("id", record.id)) }) { Text("Delete entry") }
                }
            }
        }
    }
}

private fun java.math.BigDecimal.toLongExactOrNull(): Long? = try { longValueExact() } catch (_: ArithmeticException) { null }
