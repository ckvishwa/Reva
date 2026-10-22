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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.reva.data.GymExerciseBlock
import app.reva.data.GymSessionDetail
import app.reva.data.formatDuration
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaText

/**
 * GYM-01C Session Details: the receipt. Every number on this screen was computed by the Kernel
 * from the sets that were actually committed. Nothing is estimated, scored or congratulated.
 */
@Composable
fun SessionDetailsScreen(state: GymUiState, vm: GymViewModel, modifier: Modifier = Modifier) {
    val detail = state.session
    if (detail == null) {
        SessionDetailsSkeleton(modifier.fillMaxSize())
        return
    }
    var confirmDelete by remember(detail.session.id) { mutableStateOf(false) }

    LazyColumn(
        modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp)
            .testTag("gym_details"),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Spacer(Modifier.height(12.dp))
            GymHeader(detail.session.label, "Workout receipt · plan v${detail.session.planVersion}", { vm.openPlan() })
        }
        item { GymStatusSlot(state.phase, state.savedNote, state.error) }
        item { ReceiptHeader(detail) }
        item { SummaryCards(detail) }
        item { GymSectionTitle("Exercise breakdown") }
        items(detail.exercises, key = { it.exerciseKey + it.exerciseOrder }) { block -> ExerciseBreakdown(block) }
        if (detail.exercises.isEmpty()) {
            item {
                GymCard(Modifier.testTag("gym_details_empty")) {
                    Text("No sets were recorded in this workout.", color = RevaColors.GymSecondary)
                }
            }
        }
        item { NotesCard(detail, state, vm) }
        item { Actions(detail, state, vm) { confirmDelete = true } }
        item { Spacer(Modifier.height(24.dp)) }
    }

    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            containerColor = RevaColors.GymSurface,
            title = { Text("Delete this workout?") },
            text = {
                Text(
                    "Every set in it is removed from this device and will not come back through a sync or a rebuild. " +
                        "This cannot be undone.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = RevaColors.GymSecondary,
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmDelete = false
                        vm.deleteSession(detail.session.id)
                    },
                    modifier = Modifier.testTag("gym_delete_confirm"),
                ) { Text("Delete", color = RevaColors.GymError) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("Keep it") } },
        )
    }
}

@Composable
private fun ReceiptHeader(detail: GymSessionDetail) {
    val session = detail.session
    GymCard(Modifier.testTag("gym_receipt_header")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(session.date, style = RevaText.Metric, color = RevaColors.GymText)
                Text(
                    "${shortTime(session.startedAt)} - ${shortTime(session.endedAt)} UTC",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                )
            }
            GymBadge(
                session.state.replace('_', ' '),
                color = when (session.state) {
                    "completed" -> RevaColors.GymSuccess
                    "discarded" -> RevaColors.Muted
                    else -> RevaColors.GymWarning
                },
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
            GymStat("active", formatDuration(detail.metrics.activeSeconds))
            GymStat("elapsed", formatDuration(detail.metrics.elapsedSeconds))
            if (detail.metrics.pausedSeconds > 0) GymStat("paused", formatDuration(detail.metrics.pausedSeconds))
        }
    }
}

@Composable
private fun SummaryCards(detail: GymSessionDetail) {
    val metrics = detail.metrics
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GymCard(Modifier.weight(1f), padding = 12.dp) {
                GymStat("exercises", "${metrics.exercisesPerformed}")
            }
            GymCard(Modifier.weight(1f), padding = 12.dp) {
                GymStat(
                    "working sets",
                    "${metrics.workingSetsCompleted}",
                    valueColor = RevaColors.GymSuccess,
                )
            }
            GymCard(Modifier.weight(1f), padding = 12.dp) {
                GymStat("planned", "${metrics.plannedWorkingSets}")
            }
        }
        GymCard(Modifier.testTag("gym_volume")) {
            GymSectionTitle("Working-set volume")
            if (metrics.volumeByUnit.isEmpty()) {
                Text(
                    "No completed working set carried an external load, so there is no volume to report.",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                )
            } else {
                metrics.volumeByUnit.forEach { volume ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(volume.text, style = RevaText.Metric, color = RevaColors.GymText, modifier = Modifier.weight(1f))
                        Text(
                            "${volume.sets} sets · load x reps",
                            style = MaterialTheme.typography.labelSmall,
                            color = RevaColors.Muted,
                        )
                    }
                }
            }
            if (metrics.warmupSetsCompleted > 0 || metrics.volumeExcludedSets > 0) {
                Text(
                    buildString {
                        if (metrics.warmupSetsCompleted > 0) append("${metrics.warmupSetsCompleted} warm-ups excluded. ")
                        if (metrics.volumeExcludedSets > 0) {
                            append("${metrics.volumeExcludedSets} bodyweight or assisted sets are recorded but kept out of volume.")
                        }
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.Muted,
                )
            }
            if (metrics.workingSetsPending > 0) {
                Text(
                    "${metrics.workingSetsPending} logged sets were never marked completed.",
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.GymWarning,
                )
            }
        }
    }
}

@Composable
private fun ExerciseBreakdown(block: GymExerciseBlock) {
    GymCard(Modifier.testTag("gym_block_${block.exerciseKey}")) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PixelGlyph(PixelIcon.Dumbbell, size = 18.dp, tint = RevaColors.GymAccent)
            Column(Modifier.weight(1f)) {
                Text(
                    block.exerciseName,
                    style = MaterialTheme.typography.titleMedium,
                    color = RevaColors.GymText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    buildString {
                        block.equipment?.let { append("$it · ") }
                        append(
                            block.planned?.let { "planned ${it.target}" } ?: "not in the plan for this day",
                        )
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.Muted,
                )
            }
            GymBadge(
                "${block.workingSetsCompleted}/${block.planned?.plannedSets ?: block.workingSetsLogged}",
                color = if (block.planned != null && block.workingSetsCompleted >= block.planned.plannedSets) {
                    RevaColors.GymSuccess
                } else {
                    RevaColors.GymWarning
                },
            )
        }
        block.sets.forEach { set ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PixelGlyph(
                    if (set.completed) PixelIcon.Check else PixelIcon.Minus,
                    size = 12.dp,
                    tint = if (set.completed) RevaColors.GymSuccess else RevaColors.GymWarning,
                )
                Text(
                    "${if (set.isWorking) "Set ${set.setOrder}" else "Warm-up ${set.setOrder}"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = RevaColors.GymSecondary,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    "${set.load ?: set.loadSemantics} x ${set.reps ?: "-"}",
                    style = RevaText.Amount,
                    color = RevaColors.GymText,
                )
                Text(
                    buildString {
                        set.rir?.let { append("RIR $it · ") }
                        append(if (set.completed) shortTime(set.completedAt) else "pending")
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.Muted,
                )
            }
            set.notes?.let {
                Text("· $it", style = MaterialTheme.typography.labelSmall, color = RevaColors.Muted)
            }
        }
    }
}

@Composable
private fun NotesCard(detail: GymSessionDetail, state: GymUiState, vm: GymViewModel) {
    var notes by remember(detail.session.id, detail.session.notes) { mutableStateOf(detail.session.notes ?: "") }
    var effort by remember(detail.session.id, detail.session.effortNote) { mutableStateOf(detail.session.effortNote ?: "") }
    GymCard(Modifier.testTag("gym_details_notes")) {
        GymSectionTitle("Notes")
        OutlinedTextField(
            value = notes,
            onValueChange = { notes = it.take(500) },
            label = { Text("Session note") },
            modifier = Modifier.fillMaxWidth(),
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
            Modifier.testTag("gym_details_save_notes"),
            enabled = state.phase != GymPhase.Saving,
        )
    }
}

@Composable
private fun Actions(detail: GymSessionDetail, state: GymUiState, vm: GymViewModel, onDelete: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GymPrimaryButton("Back to Gym", { vm.openPlan() }, Modifier.weight(1f).testTag("gym_back_to_gym"))
            if (detail.session.isOpen) {
                GymSecondaryButton("Keep logging", { vm.openLiveWorkout() }, Modifier.weight(1f))
            }
        }
        GymSecondaryButton(
            "Delete workout",
            onDelete,
            Modifier.fillMaxWidth().testTag("gym_delete"),
            enabled = state.phase != GymPhase.Saving,
            danger = true,
        )
    }
}
