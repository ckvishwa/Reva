package app.reva.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.reva.R

/** Design tokens, the same ones the Windows app uses (docs/design/REVA Windows App). Dark only for now. */
object RevaColors {
    val Ground = Color(0xFF0E1013)
    val Nav = Color(0xFF121519)
    val Surface = Color(0xFF15181D)
    val Border = Color(0xFF23282F)
    val Input = Color(0xFF0F1215)
    val Outline = Color(0xFF3A414B)
    val Track = Color(0xFF262B32)
    val Text = Color(0xFFECEEF1)
    val Secondary = Color(0xFFC9D0D8)
    val Muted = Color(0xFF9AA3AE)
    val Accent = Color(0xFFF2A65A)
    val AccentLight = Color(0xFFFFC48A)
    val Listening = Color(0xFF6CC4D9)
    val Success = Color(0xFF8FD3A6)
    val Error = Color(0xFFF0A0A0)

    // Gym (GYM-01) keeps the shared surfaces, type and spacing and adds the approved purple
    // accent for its primary actions. Green means a verified completed set, amber a pending one,
    // red only a destructive action or an error.
    val GymCanvas = Color(0xFF101114)
    val GymSurface = Color(0xFF191A20)
    val GymElevated = Color(0xFF24252E)
    val GymAccent = Color(0xFFB49AFF)
    val GymText = Color(0xFFF5F5F7)
    val GymSecondary = Color(0xFFB8BAC7)
    val GymSuccess = Color(0xFF7EE0AE)
    val GymWarning = Color(0xFFF3C77A)
    val GymError = Color(0xFFE86A73)
}

object RevaFonts {
    val Sans = FontFamily(
        Font(R.font.ibm_plex_sans_regular, FontWeight.Normal),
        Font(R.font.ibm_plex_sans_medium, FontWeight.Medium),
        Font(R.font.ibm_plex_sans_semibold, FontWeight.SemiBold),
    )
    val Mono = FontFamily(
        Font(R.font.ibm_plex_mono_regular, FontWeight.Normal),
        Font(R.font.ibm_plex_mono_medium, FontWeight.Medium),
    )
}

/** Card radius 14-16, button radius 10, minimum touch target 44 dp (design rules). */
object RevaShapes {
    val Card = RoundedCornerShape(16.dp)
    val SmallCard = RoundedCornerShape(14.dp)
    val Button = RoundedCornerShape(10.dp)
    val Input = RoundedCornerShape(8.dp)
    val MinTarget = 48.dp // 44 dp by the design, 48 dp where Android's own minimum is larger

    /** Gym cards and rows: rectangular with a visible border, 6-8 dp radius. */
    val GymCard = RoundedCornerShape(8.dp)
    val GymRow = RoundedCornerShape(6.dp)
}

private val scheme: ColorScheme = darkColorScheme(
    primary = RevaColors.Accent,
    onPrimary = RevaColors.Ground,
    secondary = RevaColors.Listening,
    onSecondary = RevaColors.Ground,
    background = RevaColors.Ground,
    onBackground = RevaColors.Text,
    surface = RevaColors.Surface,
    onSurface = RevaColors.Text,
    surfaceVariant = RevaColors.Input,
    onSurfaceVariant = RevaColors.Muted,
    surfaceContainer = RevaColors.Surface,
    surfaceContainerHigh = RevaColors.Surface,
    surfaceContainerHighest = RevaColors.Input,
    outline = RevaColors.Outline,
    outlineVariant = RevaColors.Border,
    error = RevaColors.Error,
    onError = RevaColors.Ground,
)

private fun style(size: Int, weight: FontWeight = FontWeight.Normal, mono: Boolean = false, line: Int = size + 6) = TextStyle(
    fontFamily = if (mono) RevaFonts.Mono else RevaFonts.Sans,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = line.sp,
)

private val typography = Typography(
    headlineMedium = style(28, FontWeight.Medium, line = 34),
    titleLarge = style(22, FontWeight.Medium, line = 28),
    titleMedium = style(16, FontWeight.SemiBold, line = 22),
    bodyLarge = style(16, line = 22),
    bodyMedium = style(14, line = 20),
    bodySmall = style(12, line = 16),
    labelLarge = style(14, FontWeight.SemiBold, line = 20),
    labelMedium = style(12, line = 16),
    labelSmall = style(11, line = 14),
)

object RevaText {
    /** Numbers (balances, amounts) use IBM Plex Mono. */
    val Number = style(24, mono = true, line = 30)
    val Amount = style(14, mono = true, line = 20)
    val Small = style(12, mono = true, line = 16)

    /** A workout timer: the largest mono style, so it reads at arm's length. */
    val Timer = style(34, FontWeight.Medium, mono = true, line = 40)
    /** A logged load or rep count in a set row. */
    val Metric = style(18, FontWeight.Medium, mono = true, line = 24)
}

@Composable
fun RevaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = scheme,
        typography = typography,
        shapes = Shapes(
            small = RevaShapes.Input,
            medium = RevaShapes.Button,
            large = RevaShapes.Card,
            extraLarge = RevaShapes.Card,
        ),
        content = content,
    )
}
