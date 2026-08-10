"""SQLite lifecycle, migrations, and repositories.

Owns: connections, transactions, migrations, schema. Does not decide
whether a memory should exist or an action is permitted — that is
`memory/` and `policy/`'s job once they exist.
"""
