package app.reva.ui.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.reva.brain.ModeController
import app.reva.brain.RunMode
import app.reva.ui.CaptionText
import app.reva.ui.MutedText
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import kotlinx.coroutines.launch

/** Explicit provider, disclosure and consent controls. The key field never uses saveable state. */
@Composable
fun ModeSettingsCard(
    modes: ModeController,
    saveKey: suspend (String) -> Boolean,
    clearKey: suspend () -> Unit,
) {
    val status by modes.state.collectAsState()
    val config = status.config
    val scope = rememberCoroutineScope()
    var keyDraft by remember { mutableStateOf("") }
    var modelDraft by remember { mutableStateOf(config.model) }
    var keyNotice by remember { mutableStateOf("") }
    RevaCard(modifier = Modifier.testTag("more_modes")) {
        SectionTitle("How REVA thinks")
        Text("Mode: ${status.label}", modifier = Modifier.testTag("mode_current"))
        MutedText(status.reason)
        if (status.retryRequired) SecondaryButton("Retry hosted reasoning", { modes.retryHosted() })
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SecondaryButton("Paired", { modes.configure(config.copy(preferred = RunMode.Paired)) })
            SecondaryButton("Standalone", { modes.configure(config.copy(preferred = RunMode.Standalone)) })
            SecondaryButton("Offline-lite", { modes.configure(config.copy(preferred = RunMode.OfflineLite)) })
        }
        MutedText("Standalone sends your free-form question as text to Anthropic (api.anthropic.com). Audio, screen contents and Kernel rows stay on this phone. Provider: Anthropic. Model: ${config.model}.")
        MutedText("Free-form questions require both Finance and Memory consent. Turning either off keeps all hosted questions on this phone.")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(config.hostedEnabled, onCheckedChange = { modes.configure(config.copy(hostedEnabled = it)) }, modifier = Modifier.testTag("hosted_enabled"))
            CaptionText("Allow hosted processing (off by default)")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(config.autoHostedFallback, onCheckedChange = { modes.configure(config.copy(autoHostedFallback = it)) })
            CaptionText("When the PC is unavailable, use hosted processing if enabled")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(config.financeConsent, onCheckedChange = { modes.configure(config.copy(financeConsent = it)) }, modifier = Modifier.testTag("finance_cloud_consent"))
            CaptionText("Allow Finance content in hosted questions")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(config.memoryConsent, onCheckedChange = { modes.configure(config.copy(memoryConsent = it)) }, modifier = Modifier.testTag("memory_cloud_consent"))
            CaptionText("Allow Memory content in hosted questions")
        }
        OutlinedTextField(modelDraft, onValueChange = { modelDraft = it.take(80) }, label = { Text("Claude model ID") }, singleLine = true)
        SecondaryButton("Save model", { runCatching { modes.configure(config.copy(model = modelDraft.trim())) }.onFailure { keyNotice = "That model ID is not valid." } })
        OutlinedTextField(
            keyDraft, onValueChange = { keyDraft = it.take(512) },
            label = { Text(if (status.keyConfigured) "Replace stored API key" else "Provider API key") },
            visualTransformation = PasswordVisualTransformation(), singleLine = true,
            modifier = Modifier.testTag("hosted_api_key"),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SecondaryButton("Store key", {
                val toSave = keyDraft
                keyDraft = ""
                scope.launch { keyNotice = if (saveKey(toSave)) "Key stored on this phone." else "The key could not be stored." }
            })
            SecondaryButton("Remove key", { scope.launch { clearKey(); keyNotice = "Key removed." } })
        }
        MutedText(if (status.keyConfigured) "A key is stored on this phone." else "No usable key is stored.")
        if (keyNotice.isNotBlank()) MutedText(keyNotice)
    }
}
