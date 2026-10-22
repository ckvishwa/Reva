package app.reva.ui.gym

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import app.reva.data.GymPlanDay
import app.reva.data.GymPrescription
import app.reva.data.GymProgram
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaShapes
import app.reva.ui.theme.RevaText

/**
 * GYM-01A Training Plan: the seven plan days, the selected day's prescription, and the way in to a
 * workout. A plan day is a rotation slot, not a weekday; the anchor date says where the rotation
 * starts.
 */
@Composable
fun TrainingPlanScreen(state: GymUiState, vm: GymViewModel, modifier: Modifier = Modifier) {
    when {
        state.phase == GymPhase.Loading && state.program == null -> TrainingPlanSkeleton(modifier.fillMaxSize())
        state.program == null -> EmptyPlan(state, vm, modifier)
        else -> PlanContent(state, state.program, vm, modifier)
    }
}

@Composable
private fun EmptyPlan(state: GymUiState, vm: GymViewModel, modifier: Modifier = Modifier) {
    Column(
        modifier
            .fillMaxSize()
            .padding(16.dp)
            .testTag("gym_plan_empty"),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        GymHeader("Training Plan", "No plan on this device yet", onBack = null)
        GymStatusSlot(state.phase, state.savedNote, state.error)
        GymCard {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PixelGlyph(PixelIcon.Dumbbell, size = 20.dp, tint = RevaColors.GymAccent)
                Text("Start from the base program", style = MaterialTheme.typography.titleMedium, color = RevaColors.GymText)
            }
            Text(
                "Seven rotation days: five training days and two rest days, 90 prescribed working sets. " +
                    "Everything in it can be edited afterwards, and it is created once on this device.",
                style = MaterialTheme.typography.bodyMedium,
                color = RevaColors.GymSecondary,
            )
            GymPrimaryButton(
                "Create training plan",
                { vm.createDefaultProgram() },
                Modifier.fillMaxWidth().testTag("gym_create_plan"),
                enabled = state.phase != GymPhase.Saving,
            )
        }
    }
}

@Composable
private fun PlanContent(state: GymUiState, program: GymProgram, vm: GymViewModel, modifier: Modifier = Modifier) {
    val day = state.selectedDay
    LazyColumn(
        modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp)
            .testTag("gym_plan"),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Spacer(Modifier.height(12.dp))
            GymHeader(
                "Training Plan",
                "${program.name} · rotation from ${program.anchorDate} · plan v${program.planVersion}",
                onBack = null,
            ) {
                GymSecondaryButton(
                    if (state.editing) "Done" else "Edit plan",
                    { vm.toggleEditing() },
                    Modifier.testTag("gym_edit_plan"),
                )
            }
        }
        item { GymStatusSlot(state.phase, state.savedNote, state.error) }
        item { DayStrip(program.days, state.selectedDayId ?: day?.dayId, vm::selectDay) }
        if (day == null) {
            item { Text("Choose a day", color = RevaColors.GymSecondary) }
        } else if (state.editing) {
            item { PlanEditor(program, day, state.phase, vm) }
        } else {
            item { DayHeading(day) }
            if (day.isRest) {
                item { RestDayCard() }
            } else {
                itemsIndexed(day.exercises, key = { index, e -> "${e.exerciseKey}-$index" }) { _, exercise ->
                    PrescriptionRow(exercise)
                }
                item {
                    GymPrimaryButton(
                        "Start workout",
                        { vm.startWorkout(day.dayId) },
                        Modifier.fillMaxWidth().testTag("gym_start_workout"),
                        enabled = state.phase != GymPhase.Saving,
                    )
                }
            }
        }
        if (state.recent.isNotEmpty()) {
            item { GymSectionTitle("Recent workouts") }
            items(state.recent, key = { it.id }) { session ->
                GymCard(
                    Modifier
                        .clickable { vm.openSession(session.id) }
                        .testTag("gym_recent_${session.id}"),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(session.label, style = MaterialTheme.typography.titleMedium, color = RevaColors.GymText)
                            Text(
                                "${session.date} · ${session.metrics.workingSetsCompleted} working sets",
                                style = MaterialTheme.typography.bodySmall,
                                color = RevaColors.GymSecondary,
                            )
                        }
                        GymBadge(
                            session.state.replace('_', ' '),
                            color = if (session.state == "completed") RevaColors.GymSuccess else RevaColors.GymWarning,
                        )
                    }
                }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

/** The seven rotation days, training and rest told apart at a glance. */
@Composable
private fun DayStrip(days: List<GymPlanDay>, selected: String?, onSelect: (String) -> Unit) {
    Row(
        Modifier.horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        days.forEach { day ->
            val active = day.dayId == selected
            Column(
                Modifier
                    .width(56.dp)
                    .clip(RevaShapes.GymCard)
                    .background(if (active) RevaColors.GymAccent.copy(alpha = 0.18f) else RevaColors.GymSurface)
                    .border(
                        1.dp,
                        if (active) RevaColors.GymAccent else RevaColors.Border,
                        RevaShapes.GymCard,
                    )
                    .clickable { onSelect(day.dayId) }
                    .padding(vertical = 10.dp)
                    .testTag("gym_day_${day.dayId}"),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    "D${day.dayIndex}",
                    style = RevaText.Small,
                    color = if (active) RevaColors.GymAccent else RevaColors.GymSecondary,
                )
                PixelGlyph(
                    if (day.isRest) PixelIcon.Rest else PixelIcon.Dumbbell,
                    tint = if (day.isRest) RevaColors.Muted else if (active) RevaColors.GymAccent else RevaColors.GymSecondary,
                    label = if (day.isRest) "Rest day" else "Training day",
                )
                Text(
                    if (day.isRest) "rest" else "${day.plannedWorkingSets}",
                    style = MaterialTheme.typography.labelSmall,
                    color = RevaColors.Muted,
                )
            }
        }
    }
}

@Composable
private fun DayHeading(day: GymPlanDay) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(
            day.label,
            style = MaterialTheme.typography.titleLarge,
            color = RevaColors.GymText,
            modifier = Modifier.testTag("gym_day_label"),
        )
        Text(
            if (day.isRest) {
                "Rest day · no prescribed working sets"
            } else {
                "Day ${day.dayIndex} · ${day.exercises.size} exercises · ${day.plannedWorkingSets} prescribed working sets"
            },
            style = MaterialTheme.typography.bodySmall,
            color = RevaColors.GymSecondary,
        )
    }
}

@Composable
private fun RestDayCard() {
    GymCard(Modifier.testTag("gym_rest_day")) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PixelGlyph(PixelIcon.Rest, size = 20.dp, tint = RevaColors.Muted)
            Text("Rest day", style = MaterialTheme.typography.titleMedium, color = RevaColors.GymText)
        }
        Text(
            "Nothing is prescribed. You can still start another day from the strip above.",
            style = MaterialTheme.typography.bodyMedium,
            color = RevaColors.GymSecondary,
        )
    }
}

@Composable
private fun PrescriptionRow(exercise: GymPrescription) {
    GymCard(Modifier.testTag("gym_exercise_${exercise.exerciseKey}"), padding = 12.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                Modifier
                    .size(28.dp)
                    .clip(RevaShapes.GymRow)
                    .background(RevaColors.GymElevated),
                contentAlignment = Alignment.Center,
            ) {
                PixelGlyph(PixelIcon.Dumbbell, tint = RevaColors.GymAccent)
            }
            Column(Modifier.weight(1f)) {
                Text(
                    "${exercise.order}. ${exercise.name}",
                    style = MaterialTheme.typography.titleMedium,
                    color = RevaColors.GymText,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                if (!exercise.equipment.isNullOrBlank()) {
                    Text(exercise.equipment, style = MaterialTheme.typography.bodySmall, color = RevaColors.Muted)
                }
            }
            Text(exercise.target, style = RevaText.Amount, color = RevaColors.GymSecondary)
        }
    }
}

/**
 * Editing a plan day: rename it, switch it between training and rest, reorder, add or drop an
 * exercise, and change the prescription. Saving sends the whole seven-day plan back as a new version.
 */
@Composable
private fun PlanEditor(program: GymProgram, day: GymPlanDay, phase: GymPhase, vm: GymViewModel) {
    var label by remember(day.dayId) { mutableStateOf(day.label) }
    var isRest by remember(day.dayId) { mutableStateOf(day.isRest) }
    var exercises by remember(day.dayId, day.exercises) { mutableStateOf(day.exercises) }

    fun commit() {
        val editedDay = day.copy(
            label = label.trim().ifBlank { day.label },
            isRest = isRest,
            exercises = if (isRest) emptyList() else exercises.mapIndexed { index, e -> e.copy(order = index + 1) },
        )
        vm.savePlan(program.days.map { if (it.dayId == day.dayId) editedDay else it })
    }

    GymCard(Modifier.testTag("gym_plan_editor")) {
        GymSectionTitle("Edit day ${day.dayIndex}")
        OutlinedTextField(
            value = label,
            onValueChange = { label = it },
            label = { Text("Workout name") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().testTag("gym_edit_label"),
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Rest day", style = MaterialTheme.typography.bodyMedium, color = RevaColors.GymText, modifier = Modifier.weight(1f))
            Switch(
                checked = isRest,
                onCheckedChange = { isRest = it },
                colors = SwitchDefaults.colors(checkedTrackColor = RevaColors.GymAccent),
                modifier = Modifier.testTag("gym_edit_rest"),
            )
        }
        if (!isRest) {
            exercises.forEachIndexed { index, exercise ->
                ExerciseEditor(
                    exercise = exercise,
                    canMoveUp = index > 0,
                    canMoveDown = index < exercises.size - 1,
                    onChange = { updated -> exercises = exercises.toMutableList().also { it[index] = updated } },
                    onMoveUp = {
                        exercises = exercises.toMutableList().also { it.add(index - 1, it.removeAt(index)) }
                    },
                    onMoveDown = {
                        exercises = exercises.toMutableList().also { it.add(index + 1, it.removeAt(index)) }
                    },
                    onRemove = { exercises = exercises.toMutableList().also { it.removeAt(index) } },
                )
            }
            NewExerciseRow { added -> exercises = exercises + added }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            GymPrimaryButton(
                "Save plan",
                ::commit,
                Modifier.weight(1f).testTag("gym_save_plan"),
                enabled = phase != GymPhase.Saving,
            )
            GymSecondaryButton("Cancel", { vm.toggleEditing() }, Modifier.weight(1f))
        }
    }
}

@Composable
private fun ExerciseEditor(
    exercise: GymPrescription,
    canMoveUp: Boolean,
    canMoveDown: Boolean,
    onChange: (GymPrescription) -> Unit,
    onMoveUp: () -> Unit,
    onMoveDown: () -> Unit,
    onRemove: () -> Unit,
) {
    GymCard(background = RevaColors.GymElevated, padding = 10.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                exercise.name,
                style = MaterialTheme.typography.titleMedium,
                color = RevaColors.GymText,
                modifier = Modifier.weight(1f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            GymIconButton(PixelIcon.Left, "Move up", onMoveUp, enabled = canMoveUp)
            GymIconButton(PixelIcon.Right, "Move down", onMoveDown, enabled = canMoveDown)
            GymIconButton(PixelIcon.Trash, "Remove exercise", onRemove, tint = RevaColors.GymError)
        }
        OutlinedTextField(
            value = exercise.equipment ?: "",
            onValueChange = { onChange(exercise.copy(equipment = it.ifBlank { null })) },
            label = { Text("Equipment or variation") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Sets", exercise.plannedSets, Modifier.weight(1f)) { onChange(exercise.copy(plannedSets = it)) }
            NumberField("Min reps", exercise.minReps, Modifier.weight(1f)) { onChange(exercise.copy(minReps = it)) }
            NumberField("Max reps", exercise.maxReps, Modifier.weight(1f)) { onChange(exercise.copy(maxReps = it)) }
        }
        NumberField("Rest seconds (optional)", exercise.restSeconds ?: 0, Modifier.fillMaxWidth()) {
            onChange(exercise.copy(restSeconds = if (it <= 0) null else it))
        }
    }
}

@Composable
private fun NewExerciseRow(onAdd: (GymPrescription) -> Unit) {
    var name by remember { mutableStateOf("") }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
            value = name,
            onValueChange = { name = it },
            label = { Text("Add an exercise") },
            singleLine = true,
            modifier = Modifier.weight(1f).testTag("gym_add_exercise_name"),
        )
        GymIconButton(
            PixelIcon.Plus,
            "Add exercise",
            {
                val trimmed = name.trim()
                if (trimmed.isNotEmpty()) {
                    onAdd(
                        GymPrescription(
                            exerciseKey = exerciseKeyOf(trimmed),
                            name = trimmed,
                            equipment = null,
                            order = 0,
                            plannedSets = 3,
                            minReps = 8,
                            maxReps = 12,
                            restSeconds = null,
                        ),
                    )
                    name = ""
                }
            },
            Modifier.testTag("gym_add_exercise"),
            tint = RevaColors.GymAccent,
        )
    }
}

/**
 * A stable progress identity from a display name. Two materially different machines keep different
 * keys because their names differ; the same movement typed the same way shares one key.
 */
fun exerciseKeyOf(name: String): String {
    val key = name.lowercase().map { if (it.isLetterOrDigit()) it else '_' }.joinToString("")
        .trim('_').replace(Regex("_+"), "_")
    return if (key.isEmpty()) "exercise" else key.take(64)
}

@Composable
private fun NumberField(label: String, value: Int, modifier: Modifier = Modifier, onChange: (Int) -> Unit) {
    var text by remember(value) { mutableStateOf(value.toString()) }
    OutlinedTextField(
        value = text,
        onValueChange = {
            text = it.filter(Char::isDigit).take(4)
            onChange(text.toIntOrNull() ?: 0)
        },
        label = { Text(label, style = MaterialTheme.typography.labelSmall) },
        singleLine = true,
        textStyle = RevaText.Amount,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        modifier = modifier,
    )
}
