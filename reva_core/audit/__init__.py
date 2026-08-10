"""Safe structured audit events.

Owns the `AuditEvent` contract and the guarantee that one can never be
constructed with a secret in it. Never stores passwords, keys, access
tokens, pairing secrets, or raw microphone data (security invariant #6).
Persistence SQL lives in `storage/repositories/audit_repository.py` —
this module decides *what* an audit event is, storage decides *how* it
is written.
"""
