package app.reva.ui.talk

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import app.reva.ui.CaptionText
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.theme.RevaColors
import app.reva.voice.MicPermission
import app.reva.voice.TalkEffect
import app.reva.voice.TalkLine
import app.reva.voice.VoiceController
import app.reva.voice.VoiceState
import app.reva.voice.Who

/**
 * Talk: type or speak. Typing is always available. The mic button is the only thing that ever asks for the
 * microphone permission, and the microphone is open only while the status line says "Listening".
 */
@Composable
fun TalkScreen(
    controller: VoiceController,
    onBeforePermissionRequest: () -> Unit,
    onOpenAppSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val ui by controller.ui.collectAsState()
    var draft by rememberSaveable { mutableStateOf("") }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        controller.onPermissionChanged()
    }
    LaunchedEffect(controller) {
        controller.effects.collect { effect ->
            when (effect) {
                TalkEffect.RequestMicPermission -> {
                    onBeforePermissionRequest()
                    launcher.launch(android.Manifest.permission.RECORD_AUDIO)
                }
            }
        }
    }

    Column(modifier.fillMaxSize().imePadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            "Talk",
            style = MaterialTheme.typography.headlineMedium,
            color = RevaColors.Text,
            modifier = Modifier.semantics { heading() },
        )
        val prefs = remember { context.getSharedPreferences("reva_voice", android.content.Context.MODE_PRIVATE) }
        var avatarOn by remember { mutableStateOf(prefs.getBoolean("avatar_enabled", true)) }
        // With the keyboard open there is little room: the avatar shrinks so the input row stays visible.
        val keyboardOpen = WindowInsets.ime.getBottom(LocalDensity.current) > 0
        AvatarView(controller, enabled = avatarOn, height = if (keyboardOpen) 100.dp else 220.dp)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Switch(
                checked = avatarOn,
                onCheckedChange = { avatarOn = it; prefs.edit().putBoolean("avatar_enabled", it).apply() },
                modifier = Modifier.testTag("talk_avatar_switch"),
            )
            CaptionText("Show the avatar")
        }
        StatusLine(ui.state, ui.micOpen, ui.thinking, ui.partial)
        ui.voiceOffReason?.let { MutedText(it, Modifier.testTag("talk_voice_off")) }
        if (ui.permission == MicPermission.DeniedForever) {
            RevaCard(modifier = Modifier.testTag("talk_mic_blocked")) {
                MutedText("The microphone is blocked for REVA. Typing still works.")
                SecondaryButton("Open app settings", onOpenAppSettings, Modifier.testTag("talk_open_settings"))
            }
        }
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth().testTag("talk_lines"),
            contentPadding = PaddingValues(vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (ui.lines.isEmpty()) {
                item { MutedText("Say something or type below. Nothing is recorded; speech is recognised on this phone.") }
            }
            items(ui.lines, key = { it.id }) { line -> Line(line) }
        }
        OutlinedTextField(
            value = draft,
            onValueChange = { draft = it.take(VoiceController.MAX_TEXT) },
            label = { Text("Type to REVA") },
            modifier = Modifier.fillMaxWidth().testTag("talk_input"),
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            PrimaryButton(
                "Send",
                { controller.onTextSubmitted(draft); draft = "" },
                Modifier.testTag("talk_send"),
                enabled = draft.isNotBlank(),
            )
            SecondaryButton(micLabel(ui.state), controller::onMicTapped, Modifier.testTag("talk_mic"))
            if (ui.state != VoiceState.Idle) {
                SecondaryButton("Stop", controller::onStopTapped, Modifier.testTag("talk_stop"))
            }
        }
    }
}

private fun micLabel(state: VoiceState): String = when (state) {
    VoiceState.Idle -> "Speak"
    VoiceState.Listening -> "Done"
    VoiceState.Speaking, VoiceState.Reasoning, VoiceState.Transcribing -> "Interrupt"
    else -> "Speak"
}

@Composable
private fun StatusLine(state: VoiceState, micOpen: Boolean, thinking: Boolean, partial: String) {
    val text = when {
        micOpen -> if (partial.isBlank()) "Listening" else "Listening: $partial"
        state == VoiceState.AcquiringPermission -> "Waiting for the microphone permission"
        state == VoiceState.Reasoning || state == VoiceState.Transcribing || thinking -> "Thinking"
        state == VoiceState.Speaking -> "Speaking"
        else -> "Ready"
    }
    CaptionText(text, Modifier.testTag("talk_status").semantics { contentDescription = "Status: $text" })
}

@Composable
private fun Line(line: TalkLine) {
    val (label, color) = when (line.who) {
        Who.You -> "You" to RevaColors.Secondary
        Who.Reva -> "REVA" to RevaColors.Accent
        Who.Notice -> "Note" to RevaColors.Secondary
    }
    Column(Modifier.fillMaxWidth()) {
        CaptionText(label)
        Text(line.text, style = MaterialTheme.typography.bodyLarge, color = if (line.who == Who.Notice) RevaColors.Secondary else RevaColors.Text)
    }
}
