"""Local Core authentication.

Owns the local API token's lifecycle (generation, storage, retrieval).
`api/` enforces the token on requests; this module decides what the
token is and where it lives. No SQL, no domain logic, no HTTP.

Interim implementation: see `local_token.py` docstring and
`docs/security/security-invariants.md` for the DPAPI/Credential
Manager migration path this is standing in for.
"""
