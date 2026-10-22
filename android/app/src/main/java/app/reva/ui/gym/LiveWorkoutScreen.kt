package app.reva.ui.gym

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.reva.data.GymExerciseBlock
import app.reva.data.GymSetRecord
import app.reva.data.formatDuration
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaText
import kotlinx.coroutines.delay

/**
 * GYM-01B Live Workout. One-handed logging: the set logger is the first thing under the exercise,
 * the keypad is numeric, and a save is only ever reported once the Kernel has committed it.
 *
 * The session clock and the rest timer both tick in the composition. The recorded truth is the
 * session's own timestamps in the Kernel, so a kill, a rotation or a trip to another tab loses
 * nothing: duration is recomputed from `started_at`, the pause intervals and `ended_at`.
 */
@Composable
fun LiveWorkoutScreen(state: GymUiState, vm: GymViewModel, modifier: Modifier = Modifier) {
    val detail = state.session
    if (detail == null) {
        LiveWorkoutSkeleton(modifier.fillMaxSize())
        return
    }
    val session = detail.session
    val block = state.currentPrescription?.let { detail.blockFor(it.exerciseKey) }

    // One tick a second drives both clocks. Nothing is written by a tick.
    var seconds by remember(session.id, session.state) { mutableLongStateOf(detail.metrics.activeSeconds) }
    LaunchedEffect(session.id, session.state, detail.metrics.activeSeconds) {
        seconds = detail.metrics.activeSeconds
        while (session.state == "in_progress") {
            delay(1_000)
            seconds += 1
        }
    }
    LaunchedEffect(state.restTimer.running) {
        while (state.restTimer.running) {
            delay(1_000)
            vm.tickRest()
        }
    }

    LazyColumn(
        modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp)
            .testTag("gym_live"),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Spacer(Modifier.height(12.dp))
            GymHeader(session.label, "Plan v${session.planVersion} · day ${session.snapshot?.dayIndex ?: "-"}", { vm.openPlan() })
        }
        item { SessionHeaderCard(state, seconds, vm) }
        item { ExerciseNavigator(state, block, vm) }
        item { SetLogger(state, vm) }
        // Below the logger, and in a slot that keeps its height: a save notice or a rest timer
        // appearing must never move the weight and reps fields under the user's thumb (GYM-02).
        item { GymStatusSlot(state.phase, state.savedNote, state.error) }
        if (state.restTimer.active) {
            item { RestTimerCard(state, vm) }
        }
        if (block != null && block.sets.isNotEmpty()) {
            item { GymSectionTitle("Logged this exercise") }
            items(block.sets, key = { it.id }) { set -> LoggedSetRow(set, state, vm) }
        }
        item { SessionNotesCard(state, vm) }
        item {
            GymPrimaryButton(
                "Finish workout",
                { vm.askToFinish() },
                Modifier.fillMaxWidth().testTag("gym_finish"),
                enabled = state.phase != GymPhase.Saving,
            )
        }
        item { Spacer(Modifier.height(24.dp)) }
    }

    if (state.finishPrompt) {
        FinishDialog(state, vm)
    }
}

@Composable
private fun SessionHeaderCard(state: GymUiState, seconds: Long, vm: GymViewModel) {
    val session = state.session?.session ?: return
    val metrics = state.session.metrics
    GymCard(Modifier.testTag("gym_session_header")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    formatDuration(seconds),
                    style = RevaText.Timer,
                    color = if (session.isPaused) RevaColors.GymWarning else RevaColors.GymAccent,
                    modifier = Modifier.testTag("gym_timer"),
                )
                Text(
                    "active · started ${shortTime(session.startedAt)} UTC on ${session.date}",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                )
            }
            Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                GymBadge(
                    session.state.replace('_', ' '),
                    color = when (session.state) {
                        "in_progress" -> RevaColors.GymAccent
                        "paused" -> RevaColors.GymWarning
                        "completed" -> RevaColors.GymSuccess
                        else -> RevaColors.Muted
                    },
                )
                GymIconButton(
                    if (session.isPaused) PixelIcon.Play else PixelIcon.Pause,
                    if (session.isPaused) "Resume workout" else "Pause workout",
                    { vm.pauseOrResume() },
                    Modifier.testTag("gym_pause"),
                    enabled = state.phase != GymPhase.Saving,
                    tint = RevaColors.GymAccent,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            GymStat("working sets", "${metrics.workingSetsCompleted}/${metrics.plannedWorkingSets}")
            GymStat("warm-ups", "${metrics.warmupSetsCompleted}")
            GymStat("elapsed", formatDuration(metrics.elapsedSeconds))
            if (metrics.pausedSeconds > 0) GymStat("paused", formatDuration(metrics.pausedSeconds))
        }
    }
}

@Composable
private fun RestTimerCard(state: GymUiState, vm: GymViewModel) {
    GymCard(Modifier.testTag("gym_rest_timer"), background = RevaColors.GymElevated) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PixelGlyph(PixelIcon.Timer, size = 18.dp, tint = RevaColors.GymWarning)
            Text(
                formatDuration(state.restTimer.remainingSeconds.toLong()),
                style = RevaText.Metric,
                color = RevaColors.GymWarning,
                modifier = Modifier.weight(1f),
            )
            if (state.restTimer.running) {
                GymSecondaryButton("Pause", { vm.pauseRest() })
            } else {
                GymSecondaryButton("Resume", { vm.resumeRest() })
            }
            GymSecondaryButton("+30s", { vm.extendRest() })
            GymSecondaryButton("Skip", { vm.skipRest() }, Modifier.testTag("gym_rest_skip"))
        }
        Text(
            "Resting. Logging and leaving this screen both still work.",
            style = MaterialTheme.typography.bodySmall,
            color = RevaColors.Muted,
        )
    }
}

@Composable
private fun ExerciseNavigator(state: GymUiState, block: GymExerciseBlock?, vm: GymViewModel) {
    val prescription = state.currentPrescription
    GymCard(Modifier.testTag("gym_navigator")) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GymIconButton(
                PixelIcon.Left,
                "Previous exercise",
                { vm.previousExercise() },
                enabled = state.currentExerciseIndex > 0,
            )
            Column(Modifier.weight(1f)) {
                Text(
                    prescription?.name ?: "Exercise",
                    style = MaterialTheme.typography.titleMedium,
                    color = RevaColors.GymText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.testTag("gym_exercise_name"),
                )
                Text(
                    "${state.currentExerciseIndex + 1} of ${state.exerciseCount} · target ${prescription?.target ?: "-"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                )
                if (!prescription?.equipment.isNullOrBlank()) {
                    Text(prescription.equipment, style = MaterialTheme.typography.bodySmall, color = RevaColors.Muted)
                }
            }
            GymIconButton(
                PixelIcon.Right,
                "Next exercise",
                { vm.nextExercise() },
                Modifier.testTag("gym_next_exercise"),
                enabled = state.currentExerciseIndex + 1 < state.exerciseCount,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            GymStat(
                "done",
                "${block?.workingSetsCompleted ?: 0}/${prescription?.plannedSets ?: 0}",
                valueColor = if ((block?.workingSetsCompleted ?: 0) >= (prescription?.plannedSets ?: 0) && (prescription?.plannedSets ?: 0) > 0) {
                    RevaColors.GymSuccess
                } else {
                    RevaColors.GymText
                },
            )
            Column {
                Text(
                    state.previous?.summary ?: if (state.previousLoaded) "No previous record." else "Reading history...",
                    style = RevaText.Amount,
                    color = RevaColors.GymSecondary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.testTag("gym_previous"),
                )
                Text(
                    state.previous?.let { "last · ${it.date}" } ?: "previous performance",
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.Muted,
                )
            }
        }
    }
}

@Composable
private fun SetLogger(state: GymUiState, vm: GymViewModel) {
    val draft = state.draft
    GymCard(Modifier.testTag("gym_set_logger")) {
        GymSectionTitle("Log a set")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = draft.load,
                onValueChange = { value -> vm.editDraft { it.copy(load = value.filter { c -> c.isDigit() || c == '.' }.take(7)) } },
                label = { Text("Weight (${state.unit})") },
                singleLine = true,
                textStyle = RevaText.Metric,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                modifier = Modifier.weight(1.2f).testTag("gym_input_load"),
            )
            OutlinedTextField(
                value = draft.reps,
                onValueChange = { value -> vm.editDraft { it.copy(reps = value.filter(Char::isDigit).take(4)) } },
                label = { Text("Reps") },
                singleLine = true,
                textStyle = RevaText.Metric,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(1f).testTag("gym_input_reps"),
            )
            OutlinedTextField(
                value = draft.rir,
                onValueChange = { value -> vm.editDraft { it.copy(rir = value.filter(Char::isDigit).take(1)) } },
                label = { Text("RIR") },
                singleLine = true,
                textStyle = RevaText.Metric,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.weight(0.8f).testTag("gym_input_rir"),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Warm-up set", style = MaterialTheme.typography.bodyMedium, color = RevaColors.GymText, modifier = Modifier.weight(1f))
            Switch(
                checked = draft.warmUp,
                onCheckedChange = { checked -> vm.editDraft { it.copy(warmUp = checked) } },
                colors = SwitchDefaults.colors(checkedTrackColor = RevaColors.GymAccent),
                modifier = Modifier.testTag("gym_input_warmup"),
            )
        }
        OutlinedTextField(
            value = draft.notes,
            onValueChange = { value -> vm.editDraft { it.copy(notes = value.take(200)) } },
            label = { Text("Form note (optional)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().testTag("gym_input_note"),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GymPrimaryButton(
                if (draft.warmUp) "Log warm-up" else "Log set",
                { vm.logSet() },
                Modifier.weight(1f).testTag("gym_log_set"),
                enabled = draft.canLog && state.phase != GymPhase.Saving,
            )
            GymSecondaryButton("Copy last", { vm.copyPreviousSet() }, Modifier.testTag("gym_copy_last"))
        }
        RestSettings(state, vm)
    }
}

@Composable
private fun RestSettings(state: GymUiState, vm: GymViewModel) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "Rest timer ${state.restTimer.totalSeconds}s",
            style = MaterialTheme.typography.bodySmall,
            color = RevaColors.GymSecondary,
            modifier = Modifier.weight(1f),
        )
        GymSecondaryButton("-30s", { vm.configureRest(state.restTimer.enabled, state.restTimer.totalSeconds - 30) })
        GymSecondaryButton("+30s", { vm.configureRest(state.restTimer.enabled, state.restTimer.totalSeconds + 30) })
        Switch(
            checked = state.restTimer.enabled,
            onCheckedChange = { vm.configureRest(it) },
            colors = SwitchDefaults.colors(checkedTrackColor = RevaColors.GymAccent),
            modifier = Modifier.testTag("gym_rest_enabled"),
        )
    }
}

@Composable
private fun LoggedSetRow(set: GymSetRecord, state: GymUiState, vm: GymViewModel) {
    var editing by remember(set.id) { mutableStateOf(false) }
    var load by remember(set.id) { mutableStateOf(set.loadMilli?.let { (it / 1000.0).toString().trimEnd('0').trimEnd('.') } ?: "") }
    var reps by remember(set.id) { mutableStateOf(set.reps?.toString() ?: "") }
    GymCard(
        Modifier.testTag("gym_set_${set.setOrder}"),
        background = RevaColors.GymElevated,
        padding = 10.dp,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PixelGlyph(
                if (set.completed) PixelIcon.Check else PixelIcon.Minus,
                tint = if (set.completed) RevaColors.GymSuccess else RevaColors.GymWarning,
                label = if (set.completed) "Completed set" else "Pending set",
            )
            Column(Modifier.weight(1f)) {
                Text(
                    "${if (set.isWorking) "Set" else "Warm-up"} ${set.setOrder} · ${set.load ?: "bodyweight"} x ${set.reps ?: "-"}",
                    style = RevaText.Amount,
                    color = RevaColors.GymText,
                )
                Text(
                    buildString {
                        append(if (set.completed) "logged ${shortTime(set.completedAt)} UTC" else "pending")
                        set.rir?.let { append(" · RIR $it") }
                        set.notes?.let { append(" · $it") }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.Muted,
                )
            }
            GymIconButton(PixelIcon.Edit, "Edit set ${set.setOrder}", { editing = !editing })
            GymIconButton(
                PixelIcon.Trash,
                "Remove set ${set.setOrder}",
                { vm.removeSet(set.id) },
                Modifier.testTag("gym_remove_set_${set.setOrder}"),
                enabled = state.phase != GymPhase.Saving,
                tint = RevaColors.GymError,
            )
        }
        if (editing) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = load,
                    onValueChange = { load = it.filter { c -> c.isDigit() || c == '.' }.take(7) },
                    label = { Text("Weight") },
                    singleLine = true,
                    textStyle = RevaText.Amount,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = reps,
                    onValueChange = { reps = it.filter(Char::isDigit).take(4) },
                    label = { Text("Reps") },
                    singleLine = true,
                    textStyle = RevaText.Amount,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                )
                GymSecondaryButton(
                    "Save",
                    {
                        editing = false
                        vm.updateSet(set.id, load, reps, null)
                    },
                    Modifier.testTag("gym_save_set_${set.setOrder}"),
                )
            }
        }
    }
}

@Composable
private fun SessionNotesCard(state: GymUiState, vm: GymViewModel) {
    val session = state.session?.session ?: return
    var notes by remember(session.id, session.notes) { mutableStateOf(session.notes ?: "") }
    var effort by remember(session.id, session.effortNote) { mutableStateOf(session.effortNote ?: "") }
    GymCard(Modifier.testTag("gym_notes")) {
        GymSectionTitle("Session notes")
        OutlinedTextField(
            value = notes,
            onValueChange = { notes = it.take(500) },
            label = { Text("What happened") },
            modifier = Modifier.fillMaxWidth().testTag("gym_input_session_note"),
        )
        OutlinedTextField(
            value = effort,
            onValueChange = { effort = it.take(500) },
            label = { Text("Effort or recovery") },
            modifier = Modifier.fillMaxWidth(),
        )
        GymSecondaryButton(
            "Save notes",
            { vm.saveNote(notes.ifBlank { null }, effort.ifBlank { null }) },
            Modifier.testTag("gym_save_notes"),
            enabled = state.phase != GymPhase.Saving,
        )
    }
}

/** Finishing is confirmed, counted from committed data, and done once. */
@Composable
private fun FinishDialog(state: GymUiState, vm: GymViewModel) {
    val detail = state.session ?: return
    val snapshot = detail.session.snapshot
    val performed = detail.exercises.count { it.workingSetsCompleted > 0 }
    val planned = snapshot?.exercises?.size ?: 0
    val phase by vm.state.collectAsState()
    AlertDialog(
        onDismissRequest = { vm.dismissFinish() },
        containerColor = RevaColors.GymSurface,
        title = { Text("Finish this workout?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    "$performed of $planned prescribed exercises have a completed working set.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = RevaColors.GymText,
                )
                Text(
                    "${detail.metrics.workingSetsCompleted} working sets, " +
                        "${detail.metrics.warmupSetsCompleted} warm-ups, " +
                        "${formatDuration(detail.metrics.activeSeconds)} active.",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                )
                if (detail.metrics.workingSetsPending > 0) {
                    Text(
                        "${detail.metrics.workingSetsPending} logged sets are not marked completed and stay that way.",
                        style = MaterialTheme.typography.bodySmall,
                        color = RevaColors.GymWarning,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { vm.finishWorkout() },
                enabled = phase.phase != GymPhase.Saving,
                modifier = Modifier.testTag("gym_finish_confirm"),
            ) { Text("Finish", color = RevaColors.GymAccent) }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { vm.discardWorkout() }, modifier = Modifier.testTag("gym_discard")) {
                    Text("Discard", color = RevaColors.GymError)
                }
                TextButton(onClick = { vm.dismissFinish() }) { Text("Keep going") }
            }
        },
    )
}
