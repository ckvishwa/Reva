using System.Runtime.InteropServices;

namespace Reva.Desktop.Voice;

/// <summary>
/// Global hold-to-talk gesture: Ctrl+Space (AR-WIN-010). A low-level keyboard hook is the only
/// Windows API that reports both the press and the release of a combination. It is installed
/// only while a voice session is on (<see cref="Enable"/>) and removed on <see cref="Disable"/>.
///
/// The hook reads key codes for this one combination and ignores everything else; it never records
/// or forwards other keys. While Ctrl+Space is held its Space events are swallowed so the focused
/// app does not also receive them. Hook callbacks only raise events: the work happens elsewhere,
/// because Windows drops a hook that is slow to return.
/// </summary>
public sealed class GlobalPushToTalkHotkey : IPushToTalkSource
{
    private const int WhKeyboardLl = 13;
    private const int WmKeyDown = 0x0100;
    private const int WmKeyUp = 0x0101;
    private const int WmSysKeyDown = 0x0104;
    private const int WmSysKeyUp = 0x0105;
    private const uint WmQuit = 0x0012;
    private const int VkSpace = 0x20;
    private const int VkControl = 0x11;
    private const int InjectedFlags = 0x12; // LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED

    private readonly object _lock = new();
    private readonly LowLevelKeyboardProc _callback;
    private Thread? _thread;
    private uint _threadId;
    private nint _hook;
    private volatile bool _held;

    public GlobalPushToTalkHotkey()
    {
        _callback = HookCallback;
    }

    public event Action? Pressed;

    public event Action? Released;

    public void Enable()
    {
        lock (_lock)
        {
            if (_thread is not null)
            {
                return;
            }

            using var ready = new ManualResetEventSlim();
            _thread = new Thread(() => Pump(ready)) { IsBackground = true, Name = "reva-ptt-hook" };
            _thread.SetApartmentState(ApartmentState.STA);
            _thread.Start();
            ready.Wait(TimeSpan.FromSeconds(2));
        }
    }

    public void Disable()
    {
        Thread? thread;
        uint threadId;
        lock (_lock)
        {
            thread = _thread;
            threadId = _threadId;
            _thread = null;
        }

        if (thread is null)
        {
            return;
        }

        PostThreadMessage(threadId, WmQuit, 0, 0);
        thread.Join(TimeSpan.FromSeconds(2));
        if (_held)
        {
            _held = false;
            Released?.Invoke();
        }
    }

    public void Dispose() => Disable();

    private void Pump(ManualResetEventSlim ready)
    {
        _threadId = GetCurrentThreadId();
        _hook = SetWindowsHookEx(WhKeyboardLl, _callback, GetModuleHandle(null), 0);
        ready.Set();
        if (_hook == 0)
        {
            return;
        }

        while (GetMessage(out var message, 0, 0, 0) > 0)
        {
            TranslateMessage(ref message);
            DispatchMessage(ref message);
        }

        UnhookWindowsHookEx(_hook);
        _hook = 0;
    }

    private nint HookCallback(int code, nint wParam, nint lParam)
    {
        if (code >= 0)
        {
            var message = (int)wParam;
            var key = Marshal.ReadInt32(lParam);
            var flags = Marshal.ReadInt32(lParam, 8);
            if ((flags & InjectedFlags) != 0)
            {
                // Keys synthesized by another program must never open the microphone.
                return CallNextHookEx(0, code, wParam, lParam);
            }

            var isDown = message is WmKeyDown or WmSysKeyDown;
            var isUp = message is WmKeyUp or WmSysKeyUp;
            if (key == VkSpace && isDown && (_held || (GetAsyncKeyState(VkControl) & 0x8000) != 0))
            {
                if (!_held)
                {
                    _held = true;
                    Pressed?.Invoke();
                }

                return 1; // swallow Space (and its auto-repeat) while the gesture is held
            }

            if (_held && ((key == VkSpace && isUp) || (key is VkControl or 0xA2 or 0xA3 && isUp)))
            {
                _held = false;
                Released?.Invoke();
                if (key == VkSpace)
                {
                    return 1;
                }
            }
        }

        return CallNextHookEx(0, code, wParam, lParam);
    }

    private delegate nint LowLevelKeyboardProc(int code, nint wParam, nint lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct Msg
    {
        public nint Hwnd;
        public uint Message;
        public nint WParam;
        public nint LParam;
        public uint Time;
        public int X;
        public int Y;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern nint SetWindowsHookEx(int idHook, LowLevelKeyboardProc lpfn, nint hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UnhookWindowsHookEx(nint hhk);

    [DllImport("user32.dll")]
    private static extern nint CallNextHookEx(nint hhk, int nCode, nint wParam, nint lParam);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    private static extern int GetMessage(out Msg lpMsg, nint hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref Msg lpMsg);

    [DllImport("user32.dll")]
    private static extern nint DispatchMessage(ref Msg lpMsg);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool PostThreadMessage(uint idThread, uint msg, nint wParam, nint lParam);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern nint GetModuleHandle(string? lpModuleName);
}
