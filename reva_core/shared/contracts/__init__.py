"""Versioned Pydantic contracts shared across module boundaries.

Every durable or serialized record has a `schema_version`. Every
timestamp is timezone-aware UTC (naive datetimes are rejected at
validation time, not silently coerced).
"""
