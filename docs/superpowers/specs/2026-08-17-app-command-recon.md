# App-command routing — Task 0 recon findings

Read: `AssistantViewModel.cs`, `MainWindow.xaml.cs`, `DesktopLogger.cs`, `AssistantMessage.cs`.

1. **Composer text from transcript.** `AssistantViewModel.FinishVoiceInputAsync`'s success branch (lines 404-406) does:
   ```csharp
   ComposerText = string.IsNullOrWhiteSpace(ComposerText)
       ? text
       : $"{ComposerText.TrimEnd()} {text}";
   ```
   Confirms design assumption — append happens via the public `ComposerText` setter, not a dedicated method today.

2. **User typing reaches the ViewModel** via `MainWindow.xaml.cs`'s `SyncComposerTextFromTextBox()` (`Assistant.ComposerText = ComposerBox.Text;`), called explicitly before both `SendButton_Click` and `ComposerBox_KeyDown` (Enter). The x:Bind TwoWay binding also commits on `LostFocus`, but the explicit sync is what guarantees Send always sees the live text — confirmed via comment in code citing manual UI-Automation reproduction.

3. **No existing way to distinguish typed vs. transcribed text.** `ComposerText`'s setter (`AssistantViewModel.cs:145-149`) is a plain `SetProperty` — same code path for a keystroke and a transcript append. Confirmed: this is new work, exactly as Task 4 assumes.

4. **`SendMessageCoreAsync`'s exact current shape** (lines 451-491):
   - Trim + `IsPending`/empty guard: `if (trimmed.Length == 0 || IsPending) return null;`
   - `Messages.Add(AssistantMessage.FromUser(trimmed));`
   - `clearComposer` branch: `if (clearComposer) { ComposerText = string.Empty; }`
   - `finally { IsPending = false; RaiseVoiceAvailabilityProperties(); }`
   Matches the plan's insertion-point description exactly — command routing goes in the `try`, after the guard/Add/clear, before the `_coreClient.SendMessageAsync` call.

5. **`DesktopLogger.Info` signature:** `public static void Info(string message)`. `Redact` is applied automatically inside `Log()` for every call (`Info`/`Warn`/`Error` all route through it) — any message containing `token`/`authorization`/`bearer`/`password`/`secret` (case-insensitive) is withheld entirely. Confirmed.

6. **`AssistantMessage.FromAssistant` exists** (`State/AssistantMessage.cs:21`). **`AssistantMessageRole` has exactly two members** (`User`, `Assistant`). No XAML changes needed for command results — `RoleLabel` already maps both to display strings.

**No contradictions found.** Every plan assumption in Task 0 holds against the code as it currently stands. Proceeding to Task 1.
