# Windows app-command routing — v2 design

Status: design, not yet implemented. Supersedes v1 (2026-08-17). Planning only — no production code changes accompany this document.

> **What changed from v1, and why.** A cross-slice review of this design against the wake-word design found one defect that neither document could see alone: `confirm` is a magic word, and **any** mechanism that can put text in the composer can therefore resolve a pending destructive action. Hold-to-Talk can already do that today; wake word will do it hands-free. v2 makes command routing source-aware so that a spoken word can never confirm a close. Four smaller corrections are noted inline (`close explorer` no longer falls silently through to the LLM; `CloseMainWindow` races are caught; process work moves off the UI thread; the VS Code fallback that v1 silently dropped is either restored or explicitly abandoned).

## Problem

Today, `AssistantViewModel.SendMessageCoreAsync` sends every non-empty composer message straight to REVA Core's assistant pipeline (`IRevaCoreClient.SendMessageAsync` → `POST v1/messages`), whether typed or populated by STT. Typing "open Chrome" behaves exactly like any other chat message. There is no local, deterministic interception anywhere in the desktop app or `reva_core` today (confirmed by recon — no `Command`/`Tool`/`Executor`/`Router` abstraction exists in `desktop/src`; `reva_core/tools/` and `reva_core/policy/` are reserved for a Phase-3 ADK-tool equivalent but are unimplemented).

This slice adds a small, fully local, deterministic command router that intercepts recognized app-open/app-close commands **before** the assistant sees them, executes them through a narrowly allowlisted Windows process executor, and lets everything else fall through to the existing assistant pipeline unchanged.

## Relationship to existing architecture (ADR-008, ADR-012)

ADR-008 (Allowlisted Tool Model) and ADR-012 (No Arbitrary Command Execution) establish the product-wide rule: every action REVA can take is a named, parameter-typed, allowlisted function — never a generic "run this command" surface, never shell/PowerShell/code execution. This router implements that invariant client-side, deterministically (string matching, not an LLM decision), separate from `reva_core`'s unbuilt `tools/`/`policy/` modules. The router never calls the assistant for a recognized command, so an LLM is never in the loop for anything it executes. `reva_core`/Python is untouched.

## The voice→execution path is real, and is accepted deliberately

v1 never stated this. It must be stated.

The transcription-only voice slice already lets a spoken sentence land in the composer. Once this router ships, **speech → composer → Send → a Windows process starts** is reachable in two steps, and it will be reachable hands-free once wake word ships. That is the intended product behavior and it is safe *because the Send press is a human, per-message, unbypassable gate*. Two consequences follow, and they are requirements, not observations:

1. **No auto-send may ever be added to any voice path** without re-opening this design. The gate is the whole safety argument.
2. **Confirmation of a destructive action may not be satisfiable by voice.** See below.

## Source-aware confirmation (the v1 defect)

v1's confirm/cancel state machine accepted the bare word `confirm` from whatever text reached `RouteAsync`. Combined with the voice path above:

> User types `close Chrome` → router replies "Close Google Chrome? … Type 'confirm' or 'cancel'." → within 30 seconds the user says something that transcribes to "confirm" — dictating a message, reading aloud, or answering someone else in the room — presses Send, and Chrome closes.

The window is 30 seconds wide, the trigger is a single extremely common English word, and STT will happily produce it. This is the one place in the slice where an accident destroys unsaved work.

**v2 rule:** `RouteAsync` takes a `CommandSource`. `confirm` and `cancel` resolve a pending action **only** when `source == CommandSource.Typed`. A transcribed `confirm` is `NotACommand` and falls through to chat, leaving the pending action untouched until it expires.

```csharp
public enum CommandSource { Typed, Transcribed }
```

`AssistantViewModel` knows which it is: text that arrived through `FinishVoiceInputAsync` (or, later, `WakeWordCoordinator`) is `Transcribed` until the user edits or retypes it. The simplest correct implementation is a `_composerTextIsTranscribed` flag set when a transcript is written into the composer and cleared on any user keystroke — which the existing `SyncComposerTextFromTextBox` path already observes.

Open/close *requests* remain source-agnostic: saying "open Chrome" and pressing Send is fine, because Send is the gate and opening an app is non-destructive. Only the confirmation step — the one that discards unsaved work — is typing-only.

## Scope (v1 of the feature, v2 of this document)

**In scope:** open/close for 7 allowlisted apps, source-aware `confirm`/`cancel` for pending close actions, routing inserted at the one call site identified by recon, result messages via the existing `AssistantMessage.FromAssistant` path (no XAML changes — the message list is role-agnostic beyond the "You"/"REVA" label).

**Out of scope:** any command beyond open/close; any non-allowlisted app; any Python/`reva_core` changes; any change to voice transcription, typed chat's non-command path, memory, or TTS behavior; wake word (sequenced after this slice).

## Command grammar

Matched against the trimmed, case-insensitive composer text:

- **Open:** `\A/?(?:open|launch|start)\s+(.+)\z`
- **Close:** `\A/?(?:close|quit)\s+(.+)\z`
- **Confirm/Cancel:** the entire trimmed text equals `confirm` or `cancel`, **and** `source == Typed`.

`\A`/`\z` rather than `^`/`$`: in .NET, `$` also matches immediately before a trailing newline, and `.` does not cross newlines. The combination means a multi-line composer message could match its first line only. `\A`/`\z` removes the ambiguity — a multi-line message is never a command.

The captured argument is trimmed, lowercased, and looked up against the allowlist's alias set **by exact equality** — never substring, never regex-in-the-argument. `"open Chrome"` → `"chrome"` → matches. `"open Chrome and tell me about tabs"` → no exact alias → not a command. This is the injection defense: the only thing that influences what runs is which fixed, hardcoded `AppDescriptor` a lookup returns, never the raw argument. Chaining, pipes, and redirection are rejected by construction, not by a blocklist.

### What falls through, and what does not (v1 correction)

v1 sent every non-match to the assistant. That is right for genuinely ambiguous input and **wrong** for input the router positively understood and declined, because the LLM will fill the silence with a plausible lie:

> User: `close explorer` → router stays silent → assistant replies "I've closed File Explorer for you." → File Explorer is still open.

v2 splits the cases:

| Input | Outcome | Why |
|---|---|---|
| No verb match (`hello`, `what's the weather`) | `NotACommand` → chat | Ordinary conversation |
| Verb matched, argument not an allowlisted alias (`open Photoshop`, `start over`) | `NotACommand` → chat | "start over", "open the door", "launch a campaign" are normal English; the router must not claim these |
| Verb matched, alias known, **close requested on an open-only app** (`close explorer`) | **`Rejected`** — "I can't close File Explorer." | The router understood exactly what was asked and is declining. Saying so is the honest answer, and it prevents a hallucinated confirmation |
| `confirm`/`cancel`, typed, pending action live | `Executed`/`Cancelled` | |
| `confirm`/`cancel`, typed, nothing pending or expired | `NotACommand` → chat | A user typing "confirm" in normal conversation gets normal chat |
| `confirm`/`cancel`, **transcribed** | `NotACommand` → chat, pending action untouched | The v2 rule above |

## Initial allowlist

| Key | Display name | Aliases (lowercase) | Open target | Close process names |
|---|---|---|---|---|
| `chrome` | Google Chrome | `chrome`, `google chrome` | `chrome.exe` (App Paths) | `chrome` |
| `edge` | Microsoft Edge | `edge`, `microsoft edge` | `msedge.exe` (App Paths) | `msedge` |
| `notepad` | Notepad | `notepad` | `notepad.exe` (PATH) | `notepad` |
| `calculator` | Calculator | `calculator`, `calc` | `calc.exe` (App Execution Alias) | `CalculatorApp`, `Calculator` |
| `vscode` | Visual Studio Code | `vscode`, `vs code`, `code` | `Code.exe` (App Paths, HKCU or HKLM) | `Code` |
| `explorer` | File Explorer | `file explorer`, `explorer` | `explorer.exe` | *(none — open-only)* |
| `settings` | Windows Settings | `settings`, `windows settings` | `ms-settings:` | *(none — open-only)* |

**Calculator** ships as a packaged app on Windows 11 (process `CalculatorApp`); older builds use `Calculator`. Both are checked on close; `calc.exe` is the open target either way.

**VS Code:** v1's design named a `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` fallback for user installs; v1's *plan* silently dropped it and shipped the bare `Code.exe` literal. v2 resolves the divergence in favour of the bare literal: `ShellExecute`'s App Paths lookup consults **HKCU as well as HKLM**, so a per-user VS Code install resolves `Code.exe` correctly without a hardcoded path, and a hardcoded path is a second string that can rot. If Task 6's acceptance run shows `open vscode` failing on a user install, the fallback comes back as a second literal in the descriptor — recorded as a finding, not a surprise.

**File Explorer and Windows Settings are open-only.** `explorer.exe` hosts the desktop shell and taskbar; `CloseMainWindow` on it has version-dependent behavior that risks closing more than a folder window. A Settings window has no clean one-process-one-thing semantics. Decided with user 2026-08-17.

Every `FileName` passed to `ProcessStartInfo` is one of these fixed literals. `Arguments` is never set. `UseShellExecute = true` throughout (required for `ms-settings:` and for graphical apps).

## Opening

```csharp
var startInfo = new ProcessStartInfo
{
    FileName = descriptor.OpenTarget,   // fixed literal, never user input
    UseShellExecute = true,
};
using var process = Process.Start(startInfo);
```

`Process.Start` with `UseShellExecute = true` **blocks** while the shell resolves and launches the target — cold-starting Chrome from a spinning disk is not instant. v1 ran this synchronously on the UI thread (`Task.FromResult` around a blocking call), which freezes the window. v2 runs both the launch and the process enumeration on the thread pool via `Task.Run`.

Failure (app not installed, `Win32Exception`/`FileNotFoundException`) is caught and reported as a safe message ("Couldn't open Visual Studio Code.") — never the exception message, never a file path, in the UI or the log.

## Closing

1. `Process.GetProcessesByName(name)` for each of the descriptor's close names, filtered to `MainWindowHandle != IntPtr.Zero` (Chrome runs many helper processes; only ones with a visible top-level window are candidates).
2. None found → **no confirmation step** — reply "Google Chrome isn't running." immediately. Nothing to confirm.
3. At least one → the confirmation state machine engages.
4. On a typed confirm: `CloseMainWindow()` on each match. **Never `Kill()`.** Report once the calls are issued, not once the process exits — `CloseMainWindow` is a polite request the app may ignore or answer with its own "save changes?" prompt.

**The enumerate→confirm→close gap is a real race** (v1 defect). Between `IsRunningAsync` and `CloseAsync` the user has up to 30 seconds to close the app themselves. `Process.CloseMainWindow()` on an exited process throws `InvalidOperationException`, and v1's executor had no catch — the exception would escape through `SendMessageCoreAsync`, which has no catch either. v2 wraps per-process: an exited process is skipped, and if every match has exited the outcome is `NotRunning`, not `Failed`.

## Confirmation state machine

`CommandRouter` holds a single `PendingClose? _pending` — one pending action at a time.

```csharp
private sealed record PendingClose(AppDescriptor App, DateTimeOffset ExpiresAtUtc);
```

- A recognized close with a running target sets `_pending` with a 30-second expiry and returns `"Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'."`
- A **typed** `confirm` inside the window executes the close and clears `_pending`.
- A **typed** `cancel` clears `_pending` (regardless of expiry) and returns `"Cancelled."`
- A **transcribed** `confirm`/`cancel` is `NotACommand` and leaves `_pending` alone.
- A new close arriving while pending overwrites it (last-write-wins).
- Expiry is checked lazily on the next confirm/cancel attempt — no timer, no `IDisposable` to leak. An injected `TimeProvider` (default `TimeProvider.System`) makes the boundary testable without `Thread.Sleep`.

## Interfaces

```csharp
public enum CommandSource { Typed, Transcribed }

public enum CommandOutcome { NotACommand, Executed, AwaitingConfirmation, Cancelled, Rejected }

public sealed record CommandRouteResult(CommandOutcome Outcome, string? ResultMessage);

public interface ICommandRouter
{
    Task<CommandRouteResult> RouteAsync(
        string text, CommandSource source, CancellationToken cancellationToken = default);
}

public enum AppCloseOutcome { NotRunning, CloseRequested, Failed }

public interface IAppExecutor
{
    Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
    Task<bool> IsRunningAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
    Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
}

public sealed record AppDescriptor(
    string Key,
    string DisplayName,
    IReadOnlyList<string> Aliases,
    string OpenTarget,
    string[]? CloseProcessNames);   // null => open-only
```

`CommandRouter` owns the allowlist table, the matching logic, the pending state machine, and the exact result strings. It calls an injected `IAppExecutor` and never touches `Process`/`ProcessStartInfo` — mirroring how `AssistantViewModel` never touches WinRT directly (`IVoiceDevice` is that seam; `IAppExecutor` is this one). `CommandRouter` is fully unit-testable with a fake executor and a manual `TimeProvider`. `WindowsAppExecutor` gets no unit tests, matching the `WindowsVoiceDevice` precedent — real OS dependency, verified by physical acceptance.

## Insertion point

Inside `AssistantViewModel.SendMessageCoreAsync`, after the existing trim/`IsPending`/empty guard and the existing `Messages.Add(AssistantMessage.FromUser(trimmed))` — so a command still appears as the user's own bubble — call `_commandRouter.RouteAsync(trimmed, currentSource, cancellationToken)`. On `NotACommand`, fall through to the unmodified `_coreClient.SendMessageAsync` path. On anything else, append `AssistantMessage.FromAssistant(result.ResultMessage!)`, skip the HTTP call, and return. `IsPending` is set and cleared exactly as today.

`MainWindow.xaml.cs`, `IRevaCoreClient`, the voice-turn path (which never calls `SendMessageCoreAsync`), memory, and TTS are untouched by construction.

## Dependency injection

`AssistantViewModel` gains a fourth optional parameter, `ICommandRouter? commandRouter = null`, defaulting to a null-object router that always returns `NotACommand` — mirroring `UnavailableVoiceDevice`, so existing call sites keep compiling and behaving identically.

**Parameter-count note.** This takes `AssistantViewModel` to four optional dependencies, and the wake-word slice wants a fifth. At five, positional optional parameters stop being readable and start producing silent mis-wiring (`new AssistantViewModel(client, null, lifecycle)` — which `null` was that?). The wake-word plan introduces an `AssistantViewModelDependencies` record; this slice deliberately stops at four rather than churning the signature twice.

`App.xaml.cs`: construct `var commandRouter = new CommandRouter(new WindowsAppExecutor());` between the existing `lifecycle` construction and `new MainWindow(...)`, and thread it through the same way `voiceDevice`/`lifecycle` were. No DI container.

## Logging and audit

Matches the voice slice's `DesktopLogger.Info("component.state=Value key=value")` convention — fixed identifiers only, never raw command text, never a file path:

- `command.state=Matched action=Open app=chrome source=typed`
- `command.state=Executed action=Open app=chrome result=success`
- `command.state=Rejected action=Open app=vscode reason=launch_failed`
- `command.state=Rejected action=Close app=explorer reason=open_only`
- `command.state=AwaitingConfirmation action=Close app=chrome`
- `command.state=Confirmed action=Close app=chrome result=requested`
- `command.state=Cancelled action=Close app=chrome`
- `command.state=ConfirmIgnored reason=transcribed_source` ← new in v2; the one line that will explain an otherwise baffling "I said confirm and nothing happened"

`app=` is always the fixed allowlist key, never the user's literal text. `source=` is the enum member. `DesktopLogger.Redact` remains a defense-in-depth backstop.

No `reva_core` audit_events — ADR-009's append-only audit table is server-side, and this router never calls Core for a recognized command. `DesktopLogger`'s local trace is the only record, matching the voice slice's `voice.state=` lines.

## Security boundary checklist

- No arbitrary executable paths — every `FileName` is one of 7 fixed literals. ✅
- No raw user input to `Process.Start` — the argument only selects a table row. ✅
- No `cmd.exe`/`powershell.exe`/`pwsh.exe`/script execution in the allowlist. ✅
- No `Process.Kill()` — `CloseMainWindow()` only. ✅
- No elevation — `Verb` is never `"runas"`. ✅
- No LLM-generated shell commands — the router runs before the assistant is ever called. ✅
- Never closes REVA itself, security tools, or system processes — closed set of 5 named consumer apps. ✅
- Rejects chaining/pipes/redirection — exact-alias equality against a fixed table. ✅
- **A destructive action cannot be confirmed by voice.** ✅ *(new in v2)*
- **A multi-line message is never a command.** ✅ *(new in v2 — `\A`/`\z` anchors)*

## Recon findings this design depends on

- Insertion point: `AssistantViewModel.SendMessageCoreAsync`, after the trim/pending/empty guard and the `Messages.Add(AssistantMessage.FromUser(trimmed))` line.
- Constructor pattern for new optional dependencies: established by `voiceDevice`/`lifecycle` in the voice slice.
- `AssistantMessageRole` has exactly two members — no XAML changes needed for command results.
- No existing confirm/cancel or dialog pattern anywhere in the desktop app — built entirely through the composer/message-list mechanism, no `ContentDialog`, no modal.
- `CoreProcessLauncher.cs` is the only existing "launch a process safely" precedent (used for `reva_core` itself) — its conventions inform `WindowsAppExecutor`'s shape.
- Test-double idiom: nested fake class + constructor-injected responder delegate + call-count properties + named static factories (`FakeCoreClient`, `FakeVoiceDevice`, `FakeCoreLifecycle`).
- **New for v2:** whether `AssistantViewModel` can distinguish typed from transcribed composer text today. It cannot — the flag is new work, specified in the plan's Task 4.
