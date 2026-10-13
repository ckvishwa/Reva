"""Locate and load the generated Python binding of the Domain Kernel.

The binding (`reva_kernel.py` plus the native library next to it) is a build artifact of
`tools/kernel/build_bindings.py`. Its directory comes from the `REVA_KERNEL_BINDINGS`
environment variable, the `kernel_bindings_dir` setting, or the repo default.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path
from types import ModuleType

_lock = threading.Lock()
_loaded: dict[Path, ModuleType] = {}

REPO_DEFAULT = Path(__file__).resolve().parents[2] / "kernel" / "bindings" / "python"


class KernelUnavailableError(RuntimeError):
    """The Kernel binding is not built or cannot be loaded."""


def bindings_dir(configured: Path | None = None) -> Path:
    env = os.environ.get("REVA_KERNEL_BINDINGS")
    if env:
        return Path(env)
    return configured if configured is not None else REPO_DEFAULT


def load_kernel(configured: Path | None = None) -> ModuleType:
    directory = bindings_dir(configured).resolve()
    with _lock:
        cached = _loaded.get(directory)
        if cached is not None:
            return cached
        module_file = directory / "reva_kernel.py"
        # One binding per process: loading the same native library through a second module
        # instance re-registers its callbacks and breaks the first one's key provider.
        existing = sys.modules.get("reva_kernel")
        existing_file = getattr(existing, "__file__", None)
        if existing is not None and existing_file:
            if Path(existing_file).resolve() != module_file.resolve():
                raise KernelUnavailableError(
                    "a Domain Kernel binding from another location is already loaded"
                )
            _loaded[directory] = existing
            return existing
        if not module_file.is_file():
            raise KernelUnavailableError(
                f"Domain Kernel binding not built (expected {module_file})"
            )
        spec = importlib.util.spec_from_file_location("reva_kernel", module_file)
        if spec is None or spec.loader is None:
            raise KernelUnavailableError("cannot import the Domain Kernel binding")
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get("reva_kernel")
        sys.modules["reva_kernel"] = module
        try:
            spec.loader.exec_module(module)
        except OSError as exc:  # native library missing or wrong architecture
            if previous is not None:
                sys.modules["reva_kernel"] = previous
            else:
                sys.modules.pop("reva_kernel", None)
            raise KernelUnavailableError(
                f"Domain Kernel native library failed to load: {exc}"
            ) from exc
        _loaded[directory] = module
        return module
