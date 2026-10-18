"""A JSON-lines subprocess that cannot outlive Core (AR-VA-008).

Heavy TTS runs in a child process (ADR-003). On Windows every worker is
assigned to a job object created with KILL_ON_JOB_CLOSE, so the OS kills
the worker when Core exits, including when Core is killed outright and no
Python cleanup runs. Everywhere else, `terminate()` is the only guard, and
the provider reports that limit rather than hiding it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from asyncio.subprocess import PIPE
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.shared.logging import get_logger

logger = get_logger("voice.worker")

# Variables a TTS worker may inherit. Everything else in Core's environment (tokens, API keys,
# proxy settings, Python startup hooks) stays behind: a worker only needs to run and find its
# libraries.
_INHERITED_ENV = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "CUDA_VISIBLE_DEVICES",
    }
)
# Verified local files are handed to the worker; it must never reach for the network.
_FORCED_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "PYTHONIOENCODING": "utf-8",
}


def worker_environment(base: Mapping[str, str]) -> dict[str, str]:
    """The environment a TTS worker gets: an allow-list of `base`, plus offline switches."""
    env = {name: value for name, value in base.items() if name.upper() in _INHERITED_ENV}
    env.update(_FORCED_ENV)
    return env


if sys.platform == "win32" or TYPE_CHECKING:
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_TERMINATE = 0x0001

    class _BasicLimits(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [  # noqa: RUF012
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32: ctypes.CDLL
    if sys.platform == "win32":
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    _kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = wintypes.BOOL


class ProcessJob:
    """Kill-on-close job object. A no-op (`active` is False) off Windows."""

    def __init__(self) -> None:
        self._handle: int | None = None
        if sys.platform == "win32":
            self._handle = self._create()

    @property
    def active(self) -> bool:
        return self._handle is not None

    def assign(self, pid: int) -> bool:
        if sys.platform != "win32" or self._handle is None:
            return False
        process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            return False
        try:
            return bool(_kernel32.AssignProcessToJobObject(self._handle, process))
        finally:
            _kernel32.CloseHandle(process)

    def close(self) -> None:
        """Close the job handle. The OS kills every process still assigned to it."""
        if sys.platform == "win32" and self._handle is not None:
            _kernel32.CloseHandle(self._handle)
        self._handle = None

    @staticmethod
    def _create() -> int | None:
        if sys.platform != "win32":
            return None
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            logger.warning("could not create job object; workers are not OS-guarded")
            return None
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not ok:
            _kernel32.CloseHandle(handle)
            logger.warning("could not configure job object; workers are not OS-guarded")
            return None
        return int(handle)


class SupervisedWorker:
    """One worker process speaking newline-delimited JSON over stdin/stdout."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @classmethod
    async def launch(
        cls,
        args: Sequence[str],
        *,
        job: ProcessJob | None,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
    ) -> SupervisedWorker:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=PIPE,
                stdout=PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=None if env is None else dict(env),
                cwd=cwd,
            )
        except OSError as exc:
            raise ProviderError(
                ProviderErrorKind.UNAVAILABLE, "TTS worker failed to start"
            ) from exc
        if job is not None and not job.assign(process.pid):
            logger.warning("worker %s is not covered by the kill-on-close job", process.pid)
        return cls(process)

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def running(self) -> bool:
        return self._process.returncode is None

    async def send(self, payload: dict[str, object]) -> None:
        stdin = self._process.stdin
        if stdin is None or not self.running:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker is not running")
        try:
            stdin.write(json.dumps(payload, ensure_ascii=True).encode("utf-8") + b"\n")
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "TTS worker pipe closed") from exc

    async def read_message(self) -> dict[str, Any] | None:
        """Read one JSON object. `None` means the worker closed its output."""
        stdout = self._process.stdout
        if stdout is None:
            return None
        raw = await stdout.readline()
        if not raw:
            return None
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                ProviderErrorKind.INVALID_RESPONSE, "TTS worker returned non-JSON"
            ) from exc
        if not isinstance(message, dict):
            raise ProviderError(ProviderErrorKind.INVALID_RESPONSE, "TTS worker response invalid")
        return message

    def kill(self) -> None:
        if self.running:
            with contextlib.suppress(ProcessLookupError, OSError):
                self._process.kill()

    async def terminate(self, grace_seconds: float = 1.0) -> None:
        """Ask the worker to exit by closing stdin, then kill it if it lingers."""
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            with contextlib.suppress(OSError):
                self._process.stdin.close()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=grace_seconds)
        except TimeoutError:
            self.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._process.wait(), timeout=grace_seconds)
