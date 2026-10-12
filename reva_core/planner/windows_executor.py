"""Fixed-target Windows app launcher with process observation evidence."""

from __future__ import annotations

import asyncio
import csv
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from reva_core.planner.pipeline import (
    AuthorizationDecision,
    ExecutionEvidence,
    JsonDict,
    Registry,
    load_registry,
)

_APPS = {
    "calculator": ("calc.exe", ("calculatorapp.exe", "calculator.exe"), "Calculator"),
    "notepad": ("notepad.exe", ("notepad.exe",), "Notepad"),
    "chrome": ("chrome.exe", ("chrome.exe",), "Google Chrome"),
    "vscode": ("Code.exe", ("code.exe",), "Visual Studio Code"),
}


def build_windows_registry() -> Registry:
    entry = deepcopy(load_registry()["windows.app.open"])
    entry["args_schema"]["properties"]["app_key"]["enum"] = list(_APPS)
    return {"windows.app.open": entry}


class WindowsActionRuntime(Protocol):
    def launch(self, target: str) -> None: ...

    def is_running(self, names: tuple[str, ...]) -> bool: ...


class SystemWindowsActionRuntime:
    def launch(self, target: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows required")
        os.startfile(target)  # noqa: S606 -- target comes only from _APPS

    def is_running(self, names: tuple[str, ...]) -> bool:
        if sys.platform != "win32":
            return False
        tasklist = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "tasklist.exe"
        output = subprocess.check_output(  # noqa: S603 -- fixed System32 command and arguments
            [str(tasklist), "/fo", "csv", "/nh"],
            timeout=2,
            text=True,
            errors="replace",
        )
        running = {row[0].casefold() for row in csv.reader(output.splitlines()) if row}
        return any(name in running for name in names)


class WindowsActionExecutor:
    def __init__(self, *, runtime: WindowsActionRuntime | None = None) -> None:
        self._runtime = runtime or SystemWindowsActionRuntime()

    async def execute(self, tool: JsonDict, decision: AuthorizationDecision) -> ExecutionEvidence:
        if (
            not decision.allowed
            or decision.tier != "T1"
            or tool.get("capability_id") != "windows.app.open"
            or tool.get("target_device_id") != "local"
        ):
            return ExecutionEvidence("denied", "")
        args = tool.get("args")
        app_key = args.get("app_key") if isinstance(args, dict) else None
        app = _APPS.get(app_key) if isinstance(app_key, str) else None
        if app is None:
            return ExecutionEvidence("denied", "")
        target, process_names, label = app
        try:
            await asyncio.to_thread(self._runtime.launch, target)
            for _ in range(10):
                if await asyncio.to_thread(self._runtime.is_running, process_names):
                    return ExecutionEvidence("verified", f"Opened {label}.")
                await asyncio.sleep(0.2)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return ExecutionEvidence("failed", "")
        return ExecutionEvidence("unknown", "")
