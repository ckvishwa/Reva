"""Typed configuration. Safe defaults, `.env` overrides, loopback-only enforcement."""

from reva_core.config.settings import Settings, load_settings

__all__ = ["Settings", "load_settings"]
