"""Runs kernel/tests/conformance/*.json through the UniFFI Python binding.

The fixture is shared with the native Rust runner (kernel/tests/conformance.rs) and the
Kotlin runner (kernel/tests/kotlin). Expected values are subset-matched: every key in the
expectation must be present and equal; arrays must have the same length.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "kernel" / "tests" / "conformance" / "finance.json"
VOLATILE = {"version", "created_at", "updated_at"}
FORBIDDEN = {
    "pay",
    "payment",
    "transfer",
    "send",
    "withdraw",
    "purchase",
    "buy",
    "wire",
    "ach",
    "login",
    "credential",
    "password",
    "bank",
}


def bindings_dir() -> Path:
    return Path(
        os.environ.get("REVA_KERNEL_BINDINGS", REPO_ROOT / "kernel" / "bindings" / "python")
    )


def load_binding():
    # Same loader as the Core, so the process holds exactly one instance of the binding.
    from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel

    try:
        return load_kernel(bindings_dir())
    except KernelUnavailableError as exc:
        raise FileNotFoundError(str(exc)) from exc


def make_keys(binding):
    class MemKeys:  # implements the KeyProvider protocol; plays the host key vault
        def __init__(self) -> None:
            self.keys: dict[str, bytes] = {}

        def load_key(self, domain: str):
            return self.keys.get(domain)

        def store_key(self, domain: str, key: bytes) -> None:
            self.keys[domain] = bytes(key)

    return MemKeys()


def error_code(binding, exc: BaseException) -> str:
    names = {
        "Locked": "locked",
        "WrongKey": "wrong_key",
        "Corrupt": "corrupt",
        "MigrationFailed": "migration_failed",
        "Validation": "validation",
        "Conflict": "conflict",
        "NotFound": "not_found",
        "Deleted": "deleted",
        "Internal": "internal",
    }
    return names.get(type(exc).__name__, f"unexpected:{type(exc).__name__}")


def subset(expected: Any, actual: Any, path: str = "") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {actual!r}"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key}: missing in {actual!r}"
            subset(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual), (
            f"{path}: expected {len(expected)} items, got {actual!r}"
        )
        for index, (e, a) in enumerate(zip(expected, actual, strict=True)):
            subset(e, a, f"{path}[{index}]")
    else:
        assert expected == actual, f"{path}: expected {expected!r}, got {actual!r}"


def strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


class Runner:
    def __init__(self, binding) -> None:
        self.b = binding
        self.dir = tempfile.mkdtemp(prefix="reva-kernel-py-")
        self.keys = make_keys(binding)
        self.handle = binding.open_domain("finance", self.keys, self.dir)

    def close(self) -> None:
        self.handle = None
        shutil.rmtree(self.dir, ignore_errors=True)

    def _attempt(self, fn):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001 - the binding raises typed DomainError subclasses
            return None, exc

    def _expect(self, step: dict, label: str, exc: BaseException | None) -> bool:
        want = step.get("expect_error")
        if want:
            assert exc is not None, f"{label}: expected error {want}, but it succeeded"
            got = error_code(self.b, exc)
            assert got == want, f"{label}: expected error {want}, got {got} ({exc})"
            return True
        assert exc is None, f"{label}: unexpected error {exc!r}"
        return False

    def list_rows(self, handle, name: str):
        params = {"limit": 1000} if name == "list_transactions" else {}
        return strip(json.loads(handle.query(name, json.dumps(params)).rows_json))

    def run_step(self, step: dict, index: int) -> None:
        op = step["op"]
        label = f"step {index} ({op} {step.get('kind') or step.get('name') or ''})"
        h = self.handle
        if op == "command":
            result, exc = self._attempt(
                lambda: h.command(step["kind"], json.dumps(step["payload"]))
            )
            if self._expect(step, label, exc):
                return
            if "expect" in step:
                subset(
                    step["expect"],
                    {
                        "event_id": result.event_id,
                        "aggregate_id": result.aggregate_id,
                        "version": result.version,
                    },
                    label,
                )
        elif op == "query":
            result, exc = self._attempt(lambda: h.query(step["name"], json.dumps(step["params"])))
            if self._expect(step, label, exc):
                return
            if "expect_rows" in step:
                subset(step["expect_rows"], json.loads(result.rows_json), label)
            if "expect_source_ids_sorted" in step:
                assert sorted(result.source_ids) == step["expect_source_ids_sorted"], label
        elif op == "today":
            text = self.b.today([h], step.get("as_of"))
            subset(step["expect"], json.loads(text), label)
        elif op in ("import", "import_error"):
            before = (h.event_count(), h.projection_digest())
            result, exc = self._attempt(
                lambda: h.import_data(
                    step["format"], step["data"].encode("utf-8"), json.dumps(step["options"])
                )
            )
            if op == "import_error":
                assert self._expect(step, label, exc), f"{label}: import_error needs expect_error"
            else:
                assert exc is None, f"{label}: {exc!r}"
                actual = {
                    "accepted": result.accepted,
                    "duplicates": result.duplicates,
                    "dry_run": result.dry_run,
                    "rejected": [{"row": r.row, "reason": r.reason} for r in result.rejected],
                }
                subset(step["expect"], actual, label)
                listed = len(json.loads(result.rows_json))
                assert listed == result.accepted + result.duplicates + len(result.rejected), (
                    f"{label}: row report incomplete"
                )
            if step.get("check_unchanged") or op == "import_error":
                assert (h.event_count(), h.projection_digest()) == before, f"{label}: state changed"
        elif op == "reopen":
            digest, events = h.projection_digest(), h.event_count()
            self.handle = None
            self.handle = self.b.open_domain("finance", self.keys, self.dir)
            assert (self.handle.projection_digest(), self.handle.event_count()) == (
                digest,
                events,
            ), f"{label}: state differs"
        elif op == "rebuild_equals_live":
            before = h.projection_digest()
            h.rebuild_projections()
            assert h.projection_digest() == before, (
                f"{label}: rebuilt projections differ from live state"
            )
            assert h.integrity_check() == "ok", label
        elif op == "export_roundtrip":
            data = h.export("json")
            dir_b = tempfile.mkdtemp(prefix="reva-kernel-py-b-")
            try:
                b = self.b.open_domain("finance", make_keys(self.b), dir_b)
                report = b.import_data("json", data, "{}")
                assert not report.rejected and report.accepted > 0, f"{label}: {report.rejected!r}"
                for name in (
                    "list_accounts", "list_categories", "list_budgets", "list_bills",
                    "list_networth_snapshots", "list_transactions",
                ):  # fmt: skip
                    assert self.list_rows(h, name) == self.list_rows(b, name), (
                        f"{label}: {name} differs"
                    )
                again = b.import_data("json", data, json.dumps({"dry_run": True}))
                assert again.accepted == 0 and again.duplicates == report.accepted, label
                assert b.integrity_check() == "ok", label
                del b
            finally:
                shutil.rmtree(dir_b, ignore_errors=True)
        elif op == "export_csv_check":
            text = bytes(h.export("csv")).decode("utf-8")
            assert text.splitlines()[0] == step["expect_header"], label
            for needle in step["expect_contains"]:
                assert needle in text, f"{label}: csv missing {needle}"
        elif op == "no_money_movement":
            for name in h.command_names():
                tokens = set(name.replace(".", "_").split("_"))
                assert not (tokens & FORBIDDEN), f"{label}: {name} looks like money movement"
        else:
            raise AssertionError(f"{label}: unknown op")


def run_suite(binding, fixture: Path = FIXTURE) -> int:
    suite = json.loads(fixture.read_text(encoding="utf-8"))
    runner = Runner(binding)
    failures: list[str] = []
    try:
        for index, step in enumerate(suite["steps"]):
            try:
                runner.run_step(step, index)
            except AssertionError as exc:
                failures.append(str(exc))
    finally:
        runner.close()
    if failures:
        raise AssertionError(
            f"{len(failures)} of {len(suite['steps'])} steps failed:\n" + "\n".join(failures)
        )
    return len(suite["steps"])
