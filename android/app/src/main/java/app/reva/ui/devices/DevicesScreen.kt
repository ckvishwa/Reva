package app.reva.ui.devices

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.reva.ui.CaptionText
import app.reva.ui.ErrorText
import app.reva.ui.MutedText
import app.reva.ui.PrimaryButton
import app.reva.ui.RevaCard
import app.reva.ui.SecondaryButton
import app.reva.ui.SectionTitle
import app.reva.ui.theme.RevaColors
import app.reva.ui.theme.RevaText

/**
 * More, then Devices: pair with a PC, compare the 6 digits, sync, and forget. Everything here is a view of
 * [DevicesViewModel]; scanning is a separate screen ([QrScanner]) opened by [onScan].
 */
@Composable
fun DevicesScreen(vm: DevicesViewModel, onScan: () -> Unit, onBack: () -> Unit, modifier: Modifier = Modifier) {
    val state by vm.state.collectAsState()
    var typedCode by remember { mutableStateOf("") }
    LazyColumn(
        modifier.fillMaxSize().testTag("devices_screen"),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Devices", style = MaterialTheme.typography.headlineMedium, color = RevaColors.Text, modifier = Modifier.semantics { heading() })
        }
        item { SecondaryButton("Back", onBack, Modifier.testTag("devices_back")) }

        state.message?.let { message ->
            item {
                RevaCard(radius = 14.dp, borderColor = if (state.isError) RevaColors.Error else RevaColors.Outline) {
                    if (state.isError) ErrorText(message, Modifier.testTag("devices_message")) else MutedText(message, Modifier.testTag("devices_message"))
                }
            }
        }

        if (state.phase == DevicesPhase.Contacting || state.phase == DevicesPhase.Syncing) {
            item {
                RevaCard(Modifier.testTag("devices_busy")) {
                    CircularProgressIndicator(color = RevaColors.Accent, strokeWidth = 2.dp)
                    MutedText(if (state.phase == DevicesPhase.Syncing) "Syncing with your PC…" else "Contacting your PC…")
                }
            }
        }

        if (state.phase == DevicesPhase.WaitingForApproval) {
            item {
                RevaCard(radius = 14.dp, borderColor = RevaColors.Accent, modifier = Modifier.testTag("pairing_wait")) {
                    SectionTitle("Check these digits on your PC")
                    Text(
                        state.fingerprint.orEmpty().chunked(3).joinToString(" "),
                        style = RevaText.Number,
                        color = RevaColors.Accent,
                        modifier = Modifier.testTag("pairing_fingerprint").semantics { contentDescription = "Pairing digits ${state.fingerprint.orEmpty().toList().joinToString(" ")}" },
                    )
                    MutedText("They must match the digits REVA shows on your PC. If they differ, tap Cancel and do not approve.")
                    MutedText("Waiting for you to approve on the PC…")
                    SecondaryButton("Cancel", vm::cancelPairing, Modifier.testTag("pairing_cancel"))
                }
            }
        }

        val pc = state.pc
        if (pc != null) {
            item {
                RevaCard(radius = 14.dp, modifier = Modifier.testTag("paired_pc")) {
                    SectionTitle("Windows PC")
                    MutedText("${pc.host}:${pc.port}")
                    CaptionText(state.lastSyncText ?: "Not synced yet")
                    CaptionText("Syncs Finance only. Key ${pc.tlsSha256.take(8)}…")
                    PrimaryButton("Sync now", vm::syncNow, Modifier.testTag("sync_now"), enabled = !state.isBusy)
                    SecondaryButton("Forget this PC", vm::forget, Modifier.testTag("forget_pc"), enabled = !state.isBusy)
                    CaptionText("To remove this phone from the PC too, use Revoke in REVA on the PC.")
                }
            }
        } else if (state.phase == DevicesPhase.Idle) {
            item {
                RevaCard(radius = 14.dp, modifier = Modifier.testTag("not_paired")) {
                    SectionTitle("Pair with your PC")
                    MutedText("On the PC: turn on the pairing gateway in Devices, then show the pairing code. Scan it here. Both screens will show the same 6 digits; you approve on the PC.")
                    PrimaryButton("Scan the code", onScan, Modifier.testTag("scan_code"))
                    OutlinedTextField(
                        value = typedCode,
                        onValueChange = { typedCode = it },
                        label = { Text("Or paste the code text") },
                        modifier = Modifier.fillMaxWidth().testTag("pairing_text"),
                        singleLine = true,
                    )
                    SecondaryButton("Use this code", { vm.onPairingCode(typedCode) }, Modifier.testTag("use_code"), enabled = typedCode.isNotBlank())
                }
            }
        }
    }
}
