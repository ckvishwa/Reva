# Windows app-command routing — v1 design

Status: design, not yet implemented. Planning only per user instruction — no production code changes accompany this document.

## Problem

Today, `AssistantViewModel.SendMessageCoreAsync` sends every non-empty composer message straight to REVA Core's assistant pipeline (`IRevaCoreClient.SendMessageAsync` → `POST v1/messages`), whether typed or populated by STT. Typing "open Chrome" behaves exactly like any other chat message — it goes to the assistant and whatever it replies with is shown. There is no local, deterministic interception anywhere in the desktop app or `reva_core` today (confirmed by recon — no `Command`/`Tool`/`Executor`/`Router` abstraction exists in `desktop/src`; `reva_core/tools/` and `reva_core/policy/` are reserved for a Phase-3 ADK-tool-based equivalent but are unimplemented).

This slice adds a small, fully local, deterministic command router that intercepts recognized app-open/app-close commands **before** the assistant ever sees them, executes them through a narrowly allowlisted Windows process executor, and lets everything else fall through to the existing assistant pipeline completely unchanged.

## Relationship to existing architecture (ADR-008, ADR-012)

ADR-008 (Allowlisted Tool Model) and ADR-012 (No Arbitrary Command Execution) already establish the product-wide rule: every action REVA can take is a named, parameter-typed, allowlisted function — never a generic "run this command" surface, never shell/PowerShell/code execution. This router implements that same invariant in a new, narrower place: entirely client-side, entirely deterministic (string matching, not an LLM decision), and entirely separate from `reva_core`'s still-unbuilt `tools/`/`policy/` modules.

This is deliberate, not an oversight: the router never calls the assistant for a recognized command, so an LLM is never in the loop for anything this router executes — it's a stronger security posture than a future ADK-tool-based equivalent, not a competing one. The design doc for that future Phase-3 work should reference this one when it's scoped; this slice does not attempt to unify with it. `reva_core`/Python is untouched by this slice — desktop-only, matching the transcription-only voice slice's precedent.

## Scope (v1)

**In scope:** open/close for 7 allowlisted apps, `confirm`/`cancel` for pending close actions, routing inserted at the one call site identified by recon, result messages via the existing `AssistantMessage.FromAssistant` path (no UI/XAML changes needed — recon confirmed the message list is role-agnostic beyond the "You"/"REVA" label).

**Out of scope:** any command beyond open/close (no "list running apps", no "minimize", no window management); any non-allowlisted app; any Python/`reva_core` changes; any change to voice transcription, typed chat's non-command path, memory, or TTS behavior (all confirmed unchanged by construction — see Insertion Point below); wake-word (blocked behind this slice per user instruction, reconciled separately after this design is accepted).

## Command grammar

Two verb classes, matched against the trimmed, case-insensitive composer text:

- **Open:** `^/?(open|launch|start)\s+(.+)$`
- **Close:** `^/?(close|quit)\s+(.+)$`
- **Confirm/Cancel:** the entire trimmed, case-insensitive text equals `confirm` or `cancel` (no verb+argument form).

The captured argument (group 2) is trimmed, lowercased, and looked up against the allowlist's alias set **by exact equality** — never substring/contains, never regex-in-the-argument. `"open Chrome"` → argument `"chrome"` → matches. `"open Chrome and tell me about tabs"` → argument `"chrome and tell me about tabs"` → no exact alias match → **not a command**. This is the injection defense: since the only thing that can influence what actually runs is which fixed, hardcoded `AppDescriptor` a lookup returns — never the raw argument string itself — chaining, pipes, redirection, and extra words are rejected by construction, not by a blocklist that could miss a variant.

Anything that doesn't match either regex, or matches but the argument isn't an allowlisted alias, is **not a command** and falls through to the existing assistant pipeline with zero behavior change — this includes bare `confirm`/`cancel` when there is no pending action to resolve (simplest, safest default: a user who happens to type "confirm" in normal conversation with nothing pending gets normal chat behavior, not a router message).

## Initial allowlist

| Display name | Aliases (lowercase) | Open target | Close supported |
|---|---|---|---|
| Google Chrome | `chrome`, `google chrome` | `chrome` (registered Windows "App Paths") | Yes — process name `chrome` |
| Microsoft Edge | `edge`, `microsoft edge` | `msedge` (App Paths) | Yes — process name `msedge` |
| Notepad | `notepad` | `notepad.exe` (always on PATH) | Yes — process name `notepad` |
| Calculator | `calculator`, `calc` | `calc.exe` (App Execution Alias, Win10/11) | Yes — process name `CalculatorApp`/`Calculator` (verify exact modern process name during implementation — Win11's Calculator process name differs from legacy `calc.exe`; this is exactly the kind of thing Task 0-style recon must nail down before the plan is written, not guessed here) |
| Visual Studio Code | `vscode`, `vs code`, `code` | `Code.exe` via App Paths if present, else the standard per-user install path `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe` as a documented fallback | Yes — process name `Code` |
| File Explorer | `file explorer`, `explorer` | `explorer.exe` | **No — open-only.** `explorer.exe` hosts the desktop shell/taskbar; `CloseMainWindow` on it has odd, version-dependent behavior that risks closing more than a folder window. Decided with user 2026-08-17: exclude from the close command set entirely rather than special-case it. |
| Windows Settings | `settings`, `windows settings` | fixed URI `ms-settings:` (`UseShellExecute = true`) | **No — open-only.** Not in the required close-command examples; a settings window has no clean "one process, one thing to close" semantics worth building for v1. |

Every `FileName` passed to `ProcessStartInfo` is one of the fixed literal strings in this table — never derived from user text beyond the alias lookup that selects a row. `Arguments` is never set. `UseShellExecute = true` for every entry (required for `ms-settings:` URI resolution and for graphical apps generally, per user's spec).

## Opening

`IAppExecutor.OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken)`:

```csharp
var startInfo = new ProcessStartInfo
{
    FileName = descriptor.OpenTarget,       // one of the fixed strings above, never user input
    UseShellExecute = true,
};
using var process = Process.Start(startInfo);
```

Failure (app not installed, launch throws `Win32Exception`/`FileNotFoundException`) is caught and reported as a safe result message ("Couldn't open Visual Studio Code.") — never surfaces the exception message or a file path to the UI or a log.

## Closing

`IAppExecutor.CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken)`:

1. `Process.GetProcessesByName(descriptor.CloseProcessName)`, filtered to `MainWindowHandle != IntPtr.Zero` (excludes headless helper/renderer processes — Chrome in particular runs many `chrome.exe` processes, only the ones with a visible top-level window are candidates).
2. If none found: **no confirmation step at all** — immediately reply "Google Chrome isn't running." No pending state is created, since there is nothing to confirm closing.
3. If at least one found: this is where the confirm/cancel state machine engages (see below).
4. On confirm: call `CloseMainWindow()` on each matching process. **Never `Kill()`.** Report success once the calls are issued (not once the process actually exits — `CloseMainWindow` is a polite request the app can ignore or prompt "save changes?" on; the router does not wait for or verify exit, matching "never force-kill" and keeping the router itself fast/synchronous-feeling).

## Confirmation state machine

`CommandRouter` holds a single `PendingClose? _pending` field — one pending action at a time, matching "only one component may own microphone capture"-style single-ownership discipline already established in this codebase for the voice slice.

```csharp
private sealed record PendingClose(AppDescriptor App, DateTimeOffset ExpiresAtUtc);
```

- A recognized `close`/`quit` command with at least one running process sets `_pending = new PendingClose(descriptor, _timeProvider.GetUtcNow().AddSeconds(30))` and returns the result message: `"Close Google Chrome? Unsaved work may be lost. Type 'confirm' or 'cancel'."` (exact wording from the user's spec).
- A bare `confirm`: if `_pending is not null` and `_timeProvider.GetUtcNow() < _pending.ExpiresAtUtc`, execute the close, clear `_pending`, return a success/failure result message. If `_pending` is null or expired, **not a command** (falls through to chat — see grammar section).
- A bare `cancel`: if `_pending is not null` (regardless of expiry), clear it and return `"Cancelled."`. If `_pending` is null, not a command.
- A *new* `close`/`quit` command arriving while `_pending` is already set: overwrites `_pending` with the new target (last-write-wins — simpler than stacking, and the user's own next message made their intent to close something else clear).
- Expiry is checked lazily (on the next `confirm`/`cancel` attempt), not via a timer — no background thread, no `IDisposable` timer object to leak or need cleanup on shutdown. A `TimeProvider` (constructor-injected, defaulting to `TimeProvider.System`) makes the 30-second boundary deterministically testable via `FakeTimeProvider` without `Thread.Sleep`.

## Interfaces

```csharp
public interface ICommandRouter
{
    Task<CommandRouteResult> RouteAsync(string text, CancellationToken cancellationToken = default);
}

public enum CommandOutcome { NotACommand, Executed, AwaitingConfirmation, Cancelled, Rejected }

public sealed record CommandRouteResult(CommandOutcome Outcome, string? ResultMessage);

public interface IAppExecutor
{
    Task<bool> OpenAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
    Task<AppCloseOutcome> CloseAsync(AppDescriptor descriptor, CancellationToken cancellationToken = default);
}

public enum AppCloseOutcome { NotRunning, CloseRequested, Failed }

public sealed record AppDescriptor(
    string DisplayName,
    IReadOnlyList<string> Aliases,
    string OpenTarget,
    string? CloseProcessName);   // null => open-only, per the Explorer/Settings decision
```

`CommandRouter` (the `ICommandRouter` implementation) owns: the allowlist table, the regex/matching logic, the pending-confirmation state machine, and the exact result-message text. It calls into an injected `IAppExecutor` for the actual OS-level work and never touches `Process`/`ProcessStartInfo` itself — this mirrors the established pattern where `AssistantViewModel` never touches WinRT types directly (`IVoiceDevice` is the seam there; `IAppExecutor` is the equivalent seam here). `CommandRouter` is fully unit-testable with a fake `IAppExecutor` and a `FakeTimeProvider`; `WindowsAppExecutor` (the real `IAppExecutor`) gets no unit tests, matching the established, already-reviewed precedent for `WindowsVoiceDevice` (real OS dependency, verified only by the physical acceptance run, not xUnit).

## Insertion point (preserves every other path unchanged)

Per recon: inside `AssistantViewModel.SendMessageCoreAsync`, after the existing trim/`IsPending`/empty-string guard and the existing `Messages.Add(AssistantMessage.FromUser(trimmed))` line — so a command still appears as the user's own message bubble, exactly like any chat message — call `_commandRouter.RouteAsync(trimmed, cancellationToken)`. On `NotACommand`, fall through to the existing, completely unmodified code (the `_coreClient.SendMessageAsync` call and everything after it) with zero changes. On any other outcome, append `AssistantMessage.FromAssistant(result.ResultMessage!)`, skip the Core HTTP call entirely, and return — `IsPending` is still set/cleared around this exactly as it is today, for UI consistency (Send stays disabled for the brief duration of a local process-launch call), even though there's no network round trip.

This is a single, surgical insertion point. `MainWindow.xaml.cs`, `IRevaCoreClient`, the voice-turn code path (which never calls `SendMessageCoreAsync` at all, per the transcription-only slice), memory, and TTS are all untouched by construction — none of them are anywhere near this insertion point.

## Dependency injection

New optional trailing constructor parameter on `AssistantViewModel`: `ICommandRouter? commandRouter = null`, defaulting to a null-object router that always returns `NotACommand` — matching the established `UnavailableVoiceDevice`-style null-object precedent, so every existing 1/2/3-arg `AssistantViewModel` test call site keeps compiling and behaving identically.

`App.xaml.cs`'s `OnLaunched`: construct `var appExecutor = new WindowsAppExecutor(); var commandRouter = new CommandRouter(appExecutor);` between the existing `lifecycle` construction and the `new MainWindow(...)` call, then thread it through `MainWindow`'s constructor the same way `voiceDevice`/`lifecycle` were added in the voice slice — no DI container, matching this project's stated "a handful of services do not need one" convention.

## Logging and audit

Matches the voice slice's established `DesktopLogger.Info("component.state=Value key=value")` convention exactly — canonical, fixed identifiers only, never raw command text, app display names beyond the fixed allowlist string, or file paths:

- `command.state=Matched action=Open app=chrome`
- `command.state=Executed action=Open app=chrome result=success`
- `command.state=Rejected action=Open app=vscode reason=launch_failed`
- `command.state=AwaitingConfirmation action=Close app=chrome`
- `command.state=Confirmed action=Close app=chrome result=requested`
- `command.state=Cancelled action=Close app=chrome`

`app=` values are always the fixed allowlist alias/key (e.g. `chrome`), never the user's literal typed text — this satisfies "log only canonical action ID, app ID and fixed result code" precisely, and the existing `DesktopLogger.Redact` keyword filter remains a defense-in-depth backstop.

This router deliberately produces **no `reva_core` audit_events** (ADR-009's append-only audit table is a Core-side, server-side concept) — it never calls Core for a recognized command, so there is nothing to audit there. `DesktopLogger`'s local trace log is the only record, matching how the voice slice's `voice.state=` lines work today.

## Security boundary checklist (from user's spec, verified against this design)

- No arbitrary executable paths — every `FileName` is one of 7 fixed literal strings. ✅
- No raw user input passed to `Process.Start` — the argument only ever selects a row in a fixed table; it's never concatenated into `FileName`/`Arguments`. ✅
- No `cmd.exe`/`powershell.exe`/`pwsh.exe`/script execution — none of the 7 allowlist entries are shells or interpreters. ✅
- No `Process.Kill()` — closing uses `CloseMainWindow()` only, never `Kill()`. ✅
- No elevation — `ProcessStartInfo` never sets `Verb = "runas"`. ✅
- No LLM-generated shell commands — the router runs entirely before the assistant is ever called for a recognized command; the LLM never sees, and cannot influence, what executes. ✅
- Never closes REVA itself, security tools, system processes, or unknown apps — satisfied by construction: the close-capable allowlist is a closed set of 5 named consumer apps, and REVA's own process is never in it. ✅
- Rejects chaining/pipes/redirection/injection-like input — satisfied by exact-alias-equality matching against a fixed table (see Command Grammar). ✅

## Reconnaissance findings this design depends on

(For the implementation plan to cite with exact file:line references — captured here so the plan doesn't have to re-derive them.)

- Insertion point: `AssistantViewModel.cs`'s `SendMessageCoreAsync`, after the trim/pending/empty guard and the `Messages.Add(AssistantMessage.FromUser(trimmed))` line.
- Constructor pattern for new optional dependencies: established by `voiceDevice`/`lifecycle` in the voice slice.
- `AssistantMessageRole` has exactly two members (`User`, `Assistant`) — no UI/XAML changes needed for command results.
- No existing confirm/cancel or dialog pattern anywhere in the desktop app — this is genuinely new UX, built entirely through the composer/message-list mechanism already in place (no `ContentDialog`, no modal).
- `CoreProcessLauncher.cs` is the only existing "launch a process safely" precedent in this codebase (used for launching `reva_core` itself, not user apps) — its conventions (`UseShellExecute` decision made deliberately, checked `Process.Start()` return value, no raw `Process` object leaking past a thin interface) inform `WindowsAppExecutor`'s shape even though it serves a different purpose.
- Test-double idiom: nested fake class + constructor-injected responder delegate + call-count properties + named static factory helpers (`FakeCoreClient`, `FakeVoiceDevice`, `FakeCoreLifecycle` all follow this) — `FakeCommandRouter`/`FakeAppExecutor` should match it exactly.
