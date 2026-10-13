# S02 shutdown lifecycle proof (2026-10-11)

Code under test: HEAD 4a6b3ee (shutdown implementation from 266bb72 + 35665f7, unchanged). No new implementation was needed.
Built from a detached worktree at 4a6b3ee (Debug), launched as the real WinUI exe, closed with CloseMainWindow() (equivalent to the title-bar X).
Core was located through REVA_CORE_REPO_ROOT; REVA_DATA_DIR was a temp dir; port 18756 (not the default 8756).

## Checks
- 10 launch/close cycles: Desktop exited each time (about 150 ms), zero Core processes left, port 18756 closed. PASS (see log).
- External Core: a Core started separately on the same port survived Desktop shutdown and kept listening. PASS.
- No blind `Environment.Exit(0)` in HEAD: the only occurrence is in the uncommitted variant preserved on branch `archive/shutdown-wip` (813ded1), which is not adopted.
- Tray quit: Desktop has no tray icon or tray menu in code (searched src for tray/NotifyIcon/Exit), so there is no separate quit path. Window close is the only exit and it uses `MainWindow_Closed` -> `RunShutdownSequenceAsync`. N/A, not PASS.
- Unit tests (ownership gates, real cmd.exe PID check, shutdown order): in the .NET suite, 350 passed / 0 failed at 4a6b3ee.
- Not covered: wake word enabled during shutdown (needs mic and AccessKey): NEEDS_HARDWARE.

## Raw log
```
S02 proof 2026-10-11T23:12:43.1046198-04:00  exe=D:\Projects\Reva-s02-proof\desktop\src\Reva.Desktop\bin\Debug\net10.0-windows10.0.19041.0\Reva.Desktop.exe  port=18756  data=C:\Users\ckvis\AppData\Local\Temp\reva-s02-acf600b8029146d1b280402edf688148
pre-existing reva_core processes: 
{"Cycle":1,"DesktopPid":50984,"CorePidListener":53392,"CoreProcsBefore":"38840,53392","CloseSent":true,"DesktopExited":true,"ExitMs":147,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":2,"DesktopPid":50868,"CorePidListener":41948,"CoreProcsBefore":"46432,41948","CloseSent":true,"DesktopExited":true,"ExitMs":146,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":3,"DesktopPid":49436,"CorePidListener":25460,"CoreProcsBefore":"52504,25460","CloseSent":true,"DesktopExited":true,"ExitMs":149,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":4,"DesktopPid":57452,"CorePidListener":57716,"CoreProcsBefore":"50412,57716","CloseSent":true,"DesktopExited":true,"ExitMs":156,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":5,"DesktopPid":53480,"CorePidListener":59076,"CoreProcsBefore":"52332,59076","CloseSent":true,"DesktopExited":true,"ExitMs":151,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":6,"DesktopPid":42472,"CorePidListener":56608,"CoreProcsBefore":"58288,56608","CloseSent":true,"DesktopExited":true,"ExitMs":145,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":7,"DesktopPid":47996,"CorePidListener":23972,"CoreProcsBefore":"53332,23972","CloseSent":true,"DesktopExited":true,"ExitMs":148,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":8,"DesktopPid":57496,"CorePidListener":51480,"CoreProcsBefore":"57476,51480","CloseSent":true,"DesktopExited":true,"ExitMs":153,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":9,"DesktopPid":45540,"CorePidListener":55000,"CoreProcsBefore":"55024,55000","CloseSent":true,"DesktopExited":true,"ExitMs":154,"CoreProcsAfter":"","PortStillListening":false}
{"Cycle":10,"DesktopPid":56068,"CorePidListener":58104,"CoreProcsBefore":"50248,58104","CloseSent":true,"DesktopExited":true,"ExitMs":141,"CoreProcsAfter":"","PortStillListening":false}
OWNED CYCLES: 10, cycles with survivor/hang: 0
--- external Core test
external Core launched pid=59336 listener=47044 reva_core procs=59336,47044
desktop exited=True; Core procs during=59336,47044 after=59336,47044; port listening=True
EXTERNAL CORE SURVIVED: True
cleanup: remaining reva_core procs=
```

Repro script: `docs/archive/s02-shutdown-proof.ps1`
