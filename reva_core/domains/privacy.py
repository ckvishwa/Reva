"""Per-domain privacy switches (ARD-700 section 4), stored by the Core next to its other data.

`sync` says whether a domain may replicate to a paired phone; `hosted_model_access` says whether
a hosted (cloud) model may see the domain's content. Finance, Health, Memory and Personal default
to no hosted-model access. This store only records the user's choice and reports it; the sync
transport and the hosted-model consent filter (AR-CORE-010) are separate pieces that read it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from reva_core.domains.service import DomainRequestError

DEFAULTS: dict[str, dict[str, bool]] = {
    "finance": {"sync": True, "hosted_model_access": False},
}
FILE_NAME = "domain_privacy.json"


class DomainPrivacyStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / FILE_NAME
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def get(self, domain: str) -> dict[str, bool]:
        if domain not in DEFAULTS:
            raise DomainRequestError("not_found", 404, f"unknown domain {domain!r}")
        with self._lock:
            stored = self._read().get(domain, {})
        current = dict(DEFAULTS[domain])
        for key, value in (stored if isinstance(stored, dict) else {}).items():
            if key in current and isinstance(value, bool):
                current[key] = value
        return current

    def update(self, domain: str, patch: dict[str, Any]) -> dict[str, bool]:
        current = self.get(domain)
        if not patch:
            raise DomainRequestError("validation_error", 422, "nothing to change")
        for key, value in patch.items():
            if key not in current:
                raise DomainRequestError("validation_error", 422, "unknown privacy switch", key)
            if not isinstance(value, bool):
                raise DomainRequestError("validation_error", 422, "must be true or false", key)
        current.update(patch)
        with self._lock:
            data = self._read()
            data[domain] = current
            self._path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(
                dir=self._path.parent, prefix=".privacy-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as out:
                    json.dump(data, out, indent=1, sort_keys=True)
                os.replace(temp_name, self._path)
            except BaseException:
                Path(temp_name).unlink(missing_ok=True)
                raise
        return current
