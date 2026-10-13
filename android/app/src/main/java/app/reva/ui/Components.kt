package app.reva.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaShapes
import app.reva.ui.theme.RevaText

/** A surface card with the design's border and radius. */
@Composable
fun RevaCard(
    modifier: Modifier = Modifier,
    radius: Dp = 16.dp,
    padding: Dp = 16.dp,
    borderColor: Color = RevaColors.Border,
    background: Color = RevaColors.Surface,
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

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleMedium, color = RevaColors.Text, modifier = modifier)
}

@Composable
fun MutedText(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = RevaColors.Muted, modifier = modifier)
}

@Composable
fun CaptionText(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = RevaColors.Muted, modifier = modifier)
}

@Composable
fun ErrorText(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = RevaColors.Error,
        modifier = modifier.semantics { contentDescription = "Error: $text" },
    )
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = RevaShapes.MinTarget),
        shape = RevaShapes.Button,
        colors = ButtonDefaults.buttonColors(
            containerColor = RevaColors.Accent,
            contentColor = RevaColors.Ground,
            disabledContainerColor = RevaColors.Accent.copy(alpha = 0.35f),
            disabledContentColor = RevaColors.Ground.copy(alpha = 0.6f),
        ),
        contentPadding = PaddingValues(horizontal = 16.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = RevaShapes.MinTarget),
        shape = RevaShapes.Button,
        border = BorderStroke(1.dp, RevaColors.Outline),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = RevaColors.Text, disabledContentColor = RevaColors.Muted),
        contentPadding = PaddingValues(horizontal = 16.dp),
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

/** A thin progress bar. Over 90% of a limit the bar turns light orange (design rule). */
@Composable
fun UsageBar(fraction: Float, nearLimit: Boolean, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(8.dp)
            .clip(RoundedCornerShape(4.dp))
            .background(RevaColors.Track),
    ) {
        Box(
            Modifier
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .height(8.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(if (nearLimit) RevaColors.AccentLight else RevaColors.Accent),
        )
    }
}

@Composable
fun MoneyText(text: String, modifier: Modifier = Modifier, color: Color = RevaColors.Secondary) {
    Text(text, style = RevaText.Amount, color = color, modifier = modifier)
}
