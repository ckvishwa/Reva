# Voice slice — Task 0 interface reconnaissance

Read-only recon for the transcription-only voice slice plan
(`docs/superpowers/plans/2026-08-16-transcription-only-voice-slice.md`).
No source files were changed to produce this document. Each section states
the verified, current truth with a file:line citation, followed by the
plan's stated assumption (where the plan states one) and whether it matches.

## 1. `IRevaCoreLifecycle` full member list; `CoreLifecycleState` member names

`desktop/src/Reva.Desktop/Services/IRevaCoreLifecycle.cs:1-17`:

```csharp
public interface IRevaCoreLifecycle
{
    CoreLifecycleState State { get; }
    string StatusText { get; }
    event EventHandler? StateChanged;
    Task StartAsync(CancellationToken cancellationToken = default);
    void StopMonitoring();
}
```

`desktop/src/Reva.Desktop/Services/CoreLifecycleState.cs:4-10`:

```csharp
public enum CoreLifecycleState
{
    Starting,
    Connected,
    Unavailable,
    AuthorizationUnavailable,
}
```

**Plan's assumption:** `Connected` and `Unavailable` members exist.
**Match:** Yes — confirmed correct. (The enum also has `Starting` and
`AuthorizationUnavailable`, which the plan's phrasing didn't claim were
absent.)

## 2. Is `IRevaCoreLifecycle.StateChanged` raised from a background thread?

Raise site: `SetState()` at `desktop/src/Reva.Desktop/Services/RevaCoreLifecycle.cs:319`
(`StateChanged?.Invoke(this, EventArgs.Empty);`). It is called from 4 places,
all reached through `async` chains that use `.ConfigureAwait(true)`
uniformly (`RevaCoreLifecycle.cs:61,99,137,144,161-164,205,211,219,225,272,279,294,301`).

The background-monitor loop (`RunMonitorLoopAsync`, `RevaCoreLifecycle.cs:179-213`)
is the one path that runs independently of a caller awaiting it
(`_ = RunMonitorLoopAsync(...)` at `RevaCoreLifecycle.cs:176`, fire-and-forget).
Its own code comment (`RevaCoreLifecycle.cs:183-198`) states the design is
deliberate: it uses `await Task.Yield()` (never `Task.Run`) specifically so
each loop iteration's continuation posts back through the
`SynchronizationContext` captured when `StartMonitor()` was called (the UI
thread's `DispatcherQueueSynchronizationContext` in production), rather than
running on a thread-pool thread. Quoting the comment: *"Deliberately NOT
Task.Run: that would detach the loop from the caller's
SynchronizationContext (the UI thread's dispatcher in production), so
RunMonitorIterationAsync's SetState/StateChanged would fire on a thread-pool
thread."*

**Verified fact:** In production, `StateChanged` does **not** fire on a raw
background/thread-pool thread. It fires on the UI thread, but via *implicit*
marshalling — `ConfigureAwait(true)` capturing the UI thread's
`SynchronizationContext` — not via any explicit dispatcher-hop code in
`RevaCoreLifecycle`, `ShellViewModel`, or `MainWindow`. `CoreStatusText`
(`desktop/src/Reva.Desktop/ViewModels/ShellViewModel.cs:30`) survives purely
because of this implicit capture, which is why `ShellViewModel` itself does
no dispatcher marshalling (`ShellViewModel.cs:32-37` calls
`RaisePropertyChanged` directly, synchronously, no thread check).

**Plan's assumption:** The plan's Task 6 draft code comment
(`docs/superpowers/plans/2026-08-16-transcription-only-voice-slice.md:1093-1095`)
states *"StateChanged may be raised from a poll/timer thread."* — i.e., the
plan assumes background-thread delivery is a live possibility it must guard
against.
**Match:** Partially wrong — see "Assumptions that were wrong" below. The
defensive code the plan adds (`HasThreadAccess` check + `TryEnqueue`) remains
correct and safe regardless, since it degrades to a direct call when already
on the UI thread.

## 3. `ObservableObject` — `PropertyChanged`-raising method name; `SetProperty` synchronicity

`desktop/src/Reva.Desktop/State/ObservableObject.cs:11-29`:

```csharp
public abstract class ObservableObject : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        RaisePropertyChanged(propertyName);
        return true;
    }

    protected void RaisePropertyChanged(string? propertyName) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
```

Method name: `RaisePropertyChanged`, `protected`, at `ObservableObject.cs:27-28`.
`SetProperty` calls `RaisePropertyChanged` directly and synchronously (no
`Task`, no `await`, no dispatch) at `ObservableObject.cs:23`.

**Plan's assumption:** The plan writes `RaisePropertyChanged` (and flags it
might actually be `OnPropertyChanged`).
**Match:** Yes — confirmed correct, it is exactly `RaisePropertyChanged`.
`SetProperty` raising synchronously is also confirmed.

## 4. `RevaCoreClient.SendBytesAsync` — own `CancellationTokenSource` or relies on `HttpClient.Timeout`?

`desktop/src/Reva.Desktop/Services/RevaCoreClient.cs:129-199` (`SendBytesAsync`,
used only by `SynthesizeSpeechAsync`, `RevaCoreClient.cs:67-77`). It creates
**no** `CancellationTokenSource` of its own. It sends the caller's
`cancellationToken` straight through to `_httpClient.SendAsync(request,
cancellationToken)` (`RevaCoreClient.cs:157`) and catches
`TaskCanceledException` only `when (!cancellationToken.IsCancellationRequested)`
(`RevaCoreClient.cs:159-162`) — that guard is precisely what distinguishes
"HttpClient's own `Timeout` fired" from "the caller cancelled," which only
makes sense if there is no separate CTS layering a shorter/independent
timeout on top. `SendAsync<T>` (the non-bytes path, `RevaCoreClient.cs:79-127`)
has the identical shape (`RevaCoreClient.cs:108,110-116`).

**Verified fact:** `SendBytesAsync` relies entirely on `HttpClient.Timeout`;
it does not create its own `CancellationTokenSource`.

**Plan's assumption:** None stated as a fixed answer — the plan explicitly
defers to this recon item (`plan:836`: *"the exact edit depends on its
current body (Task 0 Step 1.4)"*) and gives the resulting instruction: wrap
the send in a `CancellationTokenSource(_requestTimeout)` linked to the
caller's token, matching `SendAsync<T>`'s pattern.
**Match:** N/A (open question, not a fixed assumption) — this is a **new
addition**, not a fix to an existing regression; Task 4 Step 5 is the
straightforward "add it" case, not the "undo interference" case.

## 5. Every call site of `RevaCoreClient` methods; which have `catch (OperationCanceledException)`

| Method | Call site | Has `catch (OperationCanceledException)`? |
|---|---|---|
| `GetHealthAsync` | `RevaCoreLifecycle.cs:61` (`StartAsync`) | No |
| `GetHealthAsync` | `RevaCoreLifecycle.cs:99` (`StartAsync`, re-probe) | No |
| `GetHealthAsync` | `RevaCoreLifecycle.cs:219` (`RunMonitorIterationAsync`) | No |
| `GetHealthAsync` | `RevaCoreLifecycle.cs:272` (`WaitForHealthAsync`) | No |
| `GetVersionAsync` | **none** — not called anywhere in `src/`. Test doubles in `AssistantViewModelTests.cs:39-40`, `MemoryViewModelTests.cs:31-32` explicitly `throw new NotSupportedException("...never calls GetVersionAsync.")` | N/A |
| `SendMessageAsync` | `AssistantViewModel.cs:321` (`SendMessageCoreAsync`, private) called from: | |
| | (a) `AssistantViewModel.cs:161` — public `SendMessageAsync` (composer Send button) | **No** — only `try/finally` (`AssistantViewModel.cs:319-338`), no `catch` at all |
| | (b) `AssistantViewModel.cs:242` — inside `FinishVoiceInputAsync`'s try block | Yes — outer `catch (OperationCanceledException)` at `AssistantViewModel.cs:268-271` |
| `CreateMemoryAsync` | `MemoryViewModel.cs:84` (`RememberAsync`) | No — only `try/finally` (`MemoryViewModel.cs:82-98`) |
| `QueryMemoriesAsync` | `MemoryViewModel.cs:120` (`SearchAsync`) | No — only `try/finally` (`MemoryViewModel.cs:118-135`) |
| `TranscribeSpeechAsync` | `AssistantViewModel.cs:234` (`FinishVoiceInputAsync`) | Yes — `AssistantViewModel.cs:268-271` |
| `SynthesizeSpeechAsync` | `AssistantViewModel.cs:254` (`FinishVoiceInputAsync`) | Yes — `AssistantViewModel.cs:268-271` |

Also worth noting: `App.xaml.cs:43` (`await lifecycle.StartAsync();`, inside
`OnLaunched`, an `async void`) has no `catch` at all around the whole chain
that reaches all four `GetHealthAsync` sites.

**Plan's callout** (`plan:737`): *"AssistantViewModel.SendMessageAsync is the
one to check closely."* Confirmed — it is the one production call site with
zero `OperationCanceledException` handling anywhere in its call chain. This
validates rather than contradicts the plan; Task 4 Step 4 needs to address
it (currently: default `CancellationToken` on this path from
`MainWindow.xaml.cs:53,62`, so it's latent rather than actively triggered
today, but Task 4's behavior change makes it live).

## 6. `WindowsVoiceDevice` — where `_recordingPath` is written; is it deleted after `StopRecordingAsync` returns?

Written in `StartRecordingAsync`: `WindowsVoiceDevice.cs:74-77`:

```csharp
_recordingPath = Path.Combine(
    Path.GetTempPath(),
    $"reva-desktop-voice-{Guid.NewGuid():N}.wav");
await File.WriteAllBytesAsync(_recordingPath, Array.Empty<byte>(), cancellationToken);
```

Deleted in `StopRecordingAsync`'s `finally` block: `WindowsVoiceDevice.cs:128-132`:

```csharp
finally
{
    _recordingPath = null;
    DeleteIfExists(path);
}
```

**Verified fact:** Yes, it is deleted — the bytes are read
(`File.ReadAllBytesAsync(path, ...)`, `WindowsVoiceDevice.cs:126`) and then
the `finally` block deletes the file (`DeleteIfExists`,
`WindowsVoiceDevice.cs:194-211`, swallows `IOException`/
`UnauthorizedAccessException`) — this executes as part of
`StopRecordingAsync`'s own method body, i.e. before the `Task` it returns
completes, so by the time a caller's `await StopRecordingAsync()` resumes
the file is already gone. `CancelRecording()` (`WindowsVoiceDevice.cs:178-185`)
also deletes it on the abort path. No explicit assumption was stated in the
plan for this item to check against — it is background for Task 5's
"temp-file hygiene" work.

## 7. Does `DesktopConfigurationTests.cs` already exist?

`desktop/tests/Reva.Desktop.Tests/Unit/DesktopConfigurationTests.cs` exists
and is non-empty (confirmed via `Glob` + `Read`; it already has tests for
`DesktopConfiguration`'s constructor, loopback-URL validation, etc.,
starting at `DesktopConfigurationTests.cs:5`).

**Verified fact:** Yes, it already exists.

## 8. Does `MainWindow.xaml.cs` call `RefreshVoiceAvailabilityAsync` at startup?

Yes. `desktop/src/Reva.Desktop/MainWindow.xaml.cs:103-106`:

```csharp
private async void Root_Loaded(object sender, RoutedEventArgs e)
{
    await Assistant.RefreshVoiceAvailabilityAsync();
}
```

Wired to the window's root element's `Loaded` event in
`desktop/src/Reva.Desktop/MainWindow.xaml:11`:
`<Grid Padding="24" RowDefinitions="Auto,Auto,*,Auto,Auto,Auto,Auto,Auto" Loaded="Root_Loaded">`
— this fires once, at window/page load, i.e. at startup.

**Verified fact:** The call already exists at startup.

**Plan's assumption:** The plan (`plan:68`, and again at `plan:1187`:
*"If Task 0 Step 1.8 found that `RefreshVoiceAvailabilityAsync` is not
called at startup, add that call now"*) assumes it is **not** currently
called, and that Task 6 must add it.
**Match:** No — see "Assumptions that were wrong" below.

## 9. `FakeHttpMessageHandler` — what factory methods exist; is a delaying one needed?

`desktop/tests/Reva.Desktop.Tests/Unit/FakeHttpMessageHandler.cs:22-32`:

```csharp
public static FakeHttpMessageHandler ReturningStatus(HttpStatusCode statusCode, string? jsonBody = null) => ...
public static FakeHttpMessageHandler ThrowingConnectionRefused() => ...
public static FakeHttpMessageHandler ThrowingTimeout() => ...
```

No delaying/latency-simulating factory method exists today.

**Plan's assumption:** Task 4 needs a delaying one; the plan already drafts
adding `FakeHttpMessageHandler.Delayed(TimeSpan delay, HttpStatusCode
status, string json)` (`plan:638`) and uses it in several Task 4 tests
(`plan:671,689,703,720`).
**Match:** Yes — confirmed correct; `Delayed(...)` must be added, exactly as
the plan already assumes.

## 10. Does `DispatcherQueue.GetForCurrentThread()` return `null` (not throw) on an xUnit test thread?

Confirmed with a throwaway test added to
`desktop/tests/Reva.Desktop.Tests/Unit/` (a temporary
`ThrowawayDispatcherQueueProbeTests.cs`, deleted after running — not part of
the committed test suite):

```csharp
[Fact]
public void GetForCurrentThread_OnXunitTestThread()
{
    var queue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
    Console.WriteLine($"DispatcherQueue.GetForCurrentThread() == null: {queue is null}");
}
```

Run via `dotnet test tests/Reva.Desktop.Tests/Reva.Desktop.Tests.csproj --filter "FullyQualifiedName~ThrowawayDispatcherQueueProbeTests"`.

**Actual output:**
```
DispatcherQueue.GetForCurrentThread() == null: True
Passed Reva.Desktop.Tests.Unit.ThrowawayDispatcherQueueProbeTests.GetForCurrentThread_OnXunitTestThread [109 ms]
```

**Verified fact:** It returns `null`. It does not throw.

**Plan's assumption:** The plan's Task 6 draft code comment
(`plan:1074-1076`) states: *"Captured on the constructing thread: the UI
thread in MainWindow, null under xUnit. Never throws — a null queue simply
means 'already on the right thread, invoke directly.'"* and wraps the call
in `try { return DispatcherQueue.GetForCurrentThread(); } catch { return
null; }` (`plan:1077-1087`) defensively anyway.
**Match:** Yes — confirmed correct. The `try/catch` wrapper in the plan's
draft is unnecessary (it never throws) but harmless.

---

## Assumptions that were wrong — plan needs a decision

**1. Item 8 — `MainWindow.xaml.cs` already calls `RefreshVoiceAvailabilityAsync` at startup.**

The plan (`plan:68` and `plan:1187`) assumes this call is missing and
instructs Task 6 to add it ("If Task 0 Step 1.8 found that
`RefreshVoiceAvailabilityAsync` is not called at startup, add that call
now"). It is **not** missing — `MainWindow.xaml.cs:103-106`'s `Root_Loaded`
handler (wired from `MainWindow.xaml:11`'s `Loaded="Root_Loaded"`) already
calls it once at window load. Task 6 must not add a second, duplicate call.
The controller should decide whether Task 6's instruction at `plan:1187`
should be changed to "confirm the existing call site still fires under the
new `AssistantViewModel` constructor shape" (since Task 6 changes
`AssistantViewModel`'s constructor to take an optional `IRevaCoreLifecycle`)
rather than "add the call."

**2. Item 2 — the plan's stated rationale for why `StateChanged` needs
defensive dispatcher marshalling is inaccurate, though the resulting code
is still safe.**

The plan's Task 6 draft comment (`plan:1093-1095`) says *"StateChanged may
be raised from a poll/timer thread."* In the current implementation
(`RevaCoreLifecycle.cs:179-213`), the background monitor loop deliberately
avoids ever running its continuations on a raw thread-pool thread — it uses
`await Task.Yield()` (never `Task.Run`) specifically so `ConfigureAwait(true)`
carries every continuation back through the `SynchronizationContext`
captured when the loop started (the UI thread's dispatcher, in production).
The code's own comment (`RevaCoreLifecycle.cs:190-198`) states this is
deliberate, precisely to avoid the poll/timer-thread problem the plan's
comment describes. So in production, `StateChanged` today does not actually
fire off the UI thread.

This is not a functional bug in the plan's Task 6 draft — the
`_dispatcherQueue.HasThreadAccess` check (`plan:1096-1100`) degrades safely
to a direct call when already on the UI thread, so the added code remains
correct regardless of which premise is true. It is a documentation-accuracy
issue only: the code comment the plan will introduce
(`docs/superpowers/plans/2026-08-16-transcription-only-voice-slice.md:1093-1095`)
asserts something about `RevaCoreLifecycle`'s current behavior that isn't
accurate as written, and a future reader debugging a real "off-thread"
report would be pointed at the wrong mental model. The controller should
decide whether to leave the defensive code as-is (recommended — it costs
nothing and is a reasonable hedge against a future change to the monitor
loop) but correct the comment's premise, e.g.: *"`StateChanged` does not
currently fire off the UI thread in production — the monitor loop
deliberately preserves the captured `SynchronizationContext` via
`ConfigureAwait(true)` — but nothing enforces that invariant at the
interface level, so this handler marshals defensively rather than depending
on an implementation detail of `RevaCoreLifecycle` it doesn't own."*

All other checked assumptions (items 1, 3, 9, 10) were confirmed correct.
Items 4, 5, 6, 7 were open discovery questions with no fixed assumption to
be right or wrong about; their answers are recorded above for Tasks 4, 5,
and confirm Task 0 Step 1.7's prerequisite is already satisfied.
