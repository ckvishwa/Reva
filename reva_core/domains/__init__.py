"""Thin API layer over the Rust Domain Kernel (ARD-300 section 4, AR-CORE-009).

Nothing in this package implements a domain rule or touches a database: it translates HTTP
requests into Kernel calls and Kernel results back into HTTP responses. Storage, validation,
events, import/export and queries all live in `kernel/` (crate `reva-kernel`).
"""
