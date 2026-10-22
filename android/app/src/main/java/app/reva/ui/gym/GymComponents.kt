package app.reva.ui.gym

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaShapes
import app.reva.ui.theme.RevaText

/**
 * The Gym screens' shared pieces: one pixel icon set, rectangular bordered cards, stat tiles and
 * layout-shaped skeletons. Everything else (type, spacing, fonts) comes from the app's own theme.
 */

/**
 * Pixel icons, one consistent set, drawn from 7x7 grids so they stay crisp at any density and add
 * no dependency. `1` is a filled pixel.
 */
enum class PixelIcon(val rows: List<String>) {
    Dumbbell(listOf("0000000", "1100011", "1110111", "1111111", "1110111", "1100011", "0000000")),
    Timer(listOf("0011100", "0001000", "0111110", "1101011", "1100011", "1100011", "0111110")),
    Check(listOf("0000000", "0000010", "0000110", "1001100", "1111000", "0110000", "0000000")),
    Plus(listOf("0000000", "0001000", "0001000", "0111110", "0001000", "0001000", "0000000")),
    Minus(listOf("0000000", "0000000", "0000000", "0111110", "0000000", "0000000", "0000000")),
    Left(listOf("0000100", "0001100", "0011100", "0111100", "0011100", "0001100", "0000100")),
    Right(listOf("0010000", "0011000", "0011100", "0011110", "0011100", "0011000", "0010000")),
    Pause(listOf("0000000", "0110110", "0110110", "0110110", "0110110", "0110110", "0000000")),
    Play(listOf("0110000", "0111000", "0111100", "0111110", "0111100", "0111000", "0110000")),
    Rest(listOf("0000000", "0111110", "1000001", "1011101", "1000001", "0111110", "0000000")),
    Trash(listOf("0011100", "1111111", "0000000", "1010101", "1010101", "1010101", "0111110")),
    Edit(listOf("0000011", "0000110", "0001100", "0011000", "0110000", "1100000", "1110000")),
    Note(listOf("1111110", "1000010", "1011010", "1000010", "1011010", "1000010", "1111110")),
    Flag(listOf("1000000", "1111100", "1111100", "1111100", "1000000", "1000000", "1000000")),
}

@Composable
fun PixelGlyph(
    icon: PixelIcon,
    modifier: Modifier = Modifier,
    size: Dp = 16.dp,
    tint: Color = RevaColors.GymSecondary,
    label: String? = null,
) {
    val described = if (label == null) modifier else modifier.semantics { contentDescription = label }
    Canvas(described.size(size)) { drawPixels(icon, tint) }
}

private fun DrawScope.drawPixels(icon: PixelIcon, tint: Color) {
    val cell = this.size.minDimension / 7f
    icon.rows.forEachIndexed { y, row ->
        row.forEachIndexed { x, pixel ->
            if (pixel == '1') {
                drawRect(color = tint, topLeft = Offset(x * cell, y * cell), size = Size(cell, cell))
            }
        }
    }
}

/** Soft brutalism: a rectangular surface, a visible border, a small radius. */
@Composable
fun GymCard(
    modifier: Modifier = Modifier,
    background: Color = RevaColors.GymSurface,
    borderColor: Color = RevaColors.Border,
    padding: Dp = 14.dp,
    radius: Dp = 8.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(radius)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(shape)
            .background(background)
            .border(1.dp, borderColor, shape)
            .padding(padding),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = content,
    )
}

/** One number with its label. Numbers are mono so columns line up. */
@Composable
fun GymStat(label: String, value: String, modifier: Modifier = Modifier, valueColor: Color = RevaColors.GymText) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(value, style = RevaText.Metric, color = valueColor)
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = RevaColors.Muted)
    }
}

/** A short state word: green for a verified result, amber for pending, red for a failure. */
@Composable
fun GymBadge(text: String, modifier: Modifier = Modifier, color: Color = RevaColors.GymAccent) {
    Box(
        modifier
            .clip(RevaShapes.GymRow)
            .background(color.copy(alpha = 0.16f))
            .border(1.dp, color.copy(alpha = 0.5f), RevaShapes.GymRow)
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelSmall, color = color)
    }
}

@Composable
fun GymPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = RevaShapes.MinTarget),
        shape = RevaShapes.GymRow,
        colors = ButtonDefaults.buttonColors(
            containerColor = RevaColors.GymAccent,
            contentColor = Color(0xFF17141F),
            disabledContainerColor = RevaColors.GymAccent.copy(alpha = 0.3f),
            disabledContentColor = Color(0xFF17141F).copy(alpha = 0.6f),
        ),
        contentPadding = PaddingValues(horizontal = 16.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun GymSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    danger: Boolean = false,
) {
    val color = if (danger) RevaColors.GymError else RevaColors.GymText
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = RevaShapes.MinTarget),
        shape = RevaShapes.GymRow,
        border = BorderStroke(1.dp, if (danger) RevaColors.GymError.copy(alpha = 0.6f) else RevaColors.Outline),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = color, disabledContentColor = RevaColors.Muted),
        contentPadding = PaddingValues(horizontal = 14.dp),
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

/** A screen header: back, title, and one line of context under it. */
@Composable
fun GymHeader(
    title: String,
    subtitle: String?,
    onBack: (() -> Unit)?,
    modifier: Modifier = Modifier,
    trailing: @Composable (() -> Unit)? = null,
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            GymIconButton(PixelIcon.Left, "Back", onBack, Modifier.testTag("gym_back"))
            Spacer(Modifier.width(8.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleLarge, color = RevaColors.GymText, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = RevaColors.GymSecondary)
            }
        }
        trailing?.invoke()
    }
}

@Composable
fun GymIconButton(
    icon: PixelIcon,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    tint: Color = RevaColors.GymSecondary,
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.size(RevaShapes.MinTarget),
        shape = RevaShapes.GymRow,
        border = BorderStroke(1.dp, RevaColors.Border),
        contentPadding = PaddingValues(0.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = tint),
    ) {
        PixelGlyph(icon, size = 16.dp, tint = if (enabled) tint else RevaColors.Muted, label = label)
    }
}

/** One line of truth about the last action: saving, saved, or refused. Never "saved" before a commit. */
@Composable
fun GymStatusStrip(phase: GymPhase, savedNote: String?, error: String?, modifier: Modifier = Modifier) {
    val (text, color, tag) = when {
        error != null -> Triple(error, RevaColors.GymError, "gym_error")
        phase == GymPhase.Saving -> Triple("Saving to this device...", RevaColors.GymWarning, "gym_saving")
        savedNote != null -> Triple(savedNote, RevaColors.GymSuccess, "gym_saved")
        else -> Triple(null, RevaColors.GymSecondary, "gym_status")
    }
    if (text == null) return
    Row(
        modifier
            .fillMaxWidth()
            .clip(RevaShapes.GymRow)
            .background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.45f), RevaShapes.GymRow)
            .padding(horizontal = 10.dp, vertical = 8.dp)
            .testTag(tag),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        PixelGlyph(
            if (error != null) PixelIcon.Flag else if (phase == GymPhase.Saving) PixelIcon.Timer else PixelIcon.Check,
            tint = color,
            size = 14.dp,
        )
        Text(text, style = MaterialTheme.typography.bodySmall, color = color)
    }
}

/** A still placeholder block. No shimmer, no spinner: the approved dark surfaces only. */
@Composable
fun SkeletonBlock(height: Dp, modifier: Modifier = Modifier, widthFraction: Float = 1f) {
    Box(
        modifier
            .fillMaxWidth(widthFraction)
            .height(height)
            .clip(RevaShapes.GymRow)
            .background(RevaColors.GymElevated),
    )
}

@Composable
fun TrainingPlanSkeleton(modifier: Modifier = Modifier) {
    Column(modifier.padding(16.dp).testTag("gym_plan_skeleton"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonBlock(28.dp, widthFraction = 0.6f)
        SkeletonBlock(14.dp, widthFraction = 0.35f)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(7) { SkeletonBlock(56.dp, Modifier.width(44.dp)) }
        }
        SkeletonBlock(20.dp, widthFraction = 0.5f)
        repeat(5) { SkeletonBlock(52.dp) }
        SkeletonBlock(48.dp)
    }
}

@Composable
fun LiveWorkoutSkeleton(modifier: Modifier = Modifier) {
    Column(modifier.padding(16.dp).testTag("gym_live_skeleton"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonBlock(64.dp)
        SkeletonBlock(24.dp, widthFraction = 0.55f)
        repeat(3) { SkeletonBlock(44.dp) }
    }
}

@Composable
fun SessionDetailsSkeleton(modifier: Modifier = Modifier) {
    Column(modifier.padding(16.dp).testTag("gym_details_skeleton"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonBlock(56.dp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(3) { SkeletonBlock(64.dp, Modifier.weight(1f)) }
        }
        repeat(3) { SkeletonBlock(72.dp) }
    }
}

/** 2026-10-22T17:05:00Z shown as 17:05 UTC, with no pretence about the device's own zone. */
fun shortTime(instant: String?): String {
    if (instant == null || instant.length < 16) return "--:--"
    return instant.substring(11, 16)
}

fun dayLabel(instant: String?): String = instant?.take(10) ?: "--"

@Composable
fun GymSectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
        color = RevaColors.Muted,
        modifier = modifier,
    )
}
