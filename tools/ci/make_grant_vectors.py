"""Writes tests/fixtures/grant_vectors.json: signed grants shared by the Python and C# verifiers.

The private key is generated here and thrown away; only the public key, the signed grants and the
expected outcome of each case are kept. Run it only if the grant format changes (then update both
verifiers); the output is checked in so both languages test the same bytes.

    PYTHONPATH=. python tools/ci/make_grant_vectors.py
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec

from reva_core.policy.authorize import args_hash
from reva_core.policy.grants import Grant, GrantSigner

OUT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "grant_vectors.json"
NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
ARGS = {"app_key": "notepad"}
# Quotes, a backslash, a newline, a tab, accented and symbol characters: the spellings that differ
# between JSON writers. Both languages must hash these to the same bytes.
UNICODE_ARGS = {"app_key": 'café "quoted" \\ slash', "note": "line\nbreak\ttab ☃"}


def grant(args: dict[str, Any], **overrides: str) -> Grant:
    base = Grant(
        grant_id="01j-grant-0001",
        action_id="act-0001",
        capability="windows.app.open",
        args_hash=args_hash(args),
        target_device="local",
        actor="owner",
        issued_at=(NOW - timedelta(seconds=5)).isoformat(),
        expires_at=(NOW + timedelta(seconds=55)).isoformat(),
        idempotency_key="idem-0001",
    )
    return replace(base, **overrides)


def main() -> None:
    signer = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    stranger = GrantSigner(ec.generate_private_key(ec.SECP256R1()))
    good = grant(ARGS)
    cases: list[dict[str, Any]] = []

    def add(
        name: str,
        g: Grant,
        args: dict[str, Any],
        expect: str,
        *,
        signature: str | None = None,
        now: datetime = NOW,
        capability: str | None = None,
        target: str = "local",
        actor: str = "owner",
        signed_by: GrantSigner = signer,
    ) -> None:
        cases.append(
            {
                "name": name,
                "grant": g.to_dict(),
                "signature": signature if signature is not None else signed_by.sign(g),
                "args": args,
                "capability": capability or g.capability,
                "target_device": target,
                "actor": actor,
                "now": now.isoformat(),
                "expect": expect,
            }
        )

    add("valid", good, ARGS, "OK")
    add("valid_unicode_args", grant(UNICODE_ARGS, idempotency_key="idem-uni"), UNICODE_ARGS, "OK")
    add(
        "valid_close",
        grant(ARGS, capability="windows.app.close", idempotency_key="idem-close"),
        ARGS,
        "OK",
    )
    obsidian = {"app_key": "obsidian"}
    add("valid_obsidian", grant(obsidian, idempotency_key="idem-obsidian"), obsidian, "OK")
    add("expired", good, ARGS, "EXPIRED", now=NOW + timedelta(seconds=61))
    add("from_the_future", good, ARGS, "NOT_YET_VALID", now=NOW - timedelta(seconds=30))
    add("wrong_signer", good, ARGS, "BAD_SIGNATURE", signed_by=stranger)
    add(
        "tampered_args_hash",
        replace(good, args_hash="0" * 64),
        ARGS,
        "BAD_SIGNATURE",
        signature=signer.sign(good),
    )
    add("substituted_args", good, {"app_key": "chrome"}, "ARGS_MISMATCH")
    add("substituted_capability", good, ARGS, "CAPABILITY_MISMATCH", capability="windows.app.close")
    add("wrong_target", good, ARGS, "WRONG_TARGET", target="phone-0001")
    add("wrong_actor", good, ARGS, "WRONG_ACTOR", actor="someone")
    add("malformed_signature", good, ARGS, "MALFORMED", signature="AAAA")
    add("not_base64", good, ARGS, "MALFORMED", signature="not base64 !!")
    document = {
        "public_key_pem": signer.public_key_pem().decode("ascii"),
        "note": "Shared by the Python grant tests and the Windows executor tests.",
        "cases": cases,
    }
    OUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    main()
