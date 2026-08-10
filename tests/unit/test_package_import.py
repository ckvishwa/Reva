"""Package/import smoke test — every Phase 0 module must import cleanly
with zero external services and zero credentials available."""

import importlib

import reva_core

MODULES = [
    "reva_core.config.settings",
    "reva_core.shared.errors",
    "reva_core.shared.ids",
    "reva_core.shared.time",
    "reva_core.shared.redaction",
    "reva_core.shared.logging",
    "reva_core.shared.contracts.base",
    "reva_core.shared.contracts.ids",
    "reva_core.shared.contracts.conversation",
    "reva_core.shared.contracts.memory",
    "reva_core.shared.contracts.reminder",
    "reva_core.shared.contracts.tool",
    "reva_core.shared.contracts.permission",
    "reva_core.shared.contracts.sync",
    "reva_core.shared.contracts.health",
    "reva_core.storage.connection",
    "reva_core.storage.migrations",
    "reva_core.storage.bootstrap",
    "reva_core.storage.repositories.audit_repository",
    "reva_core.audit.events",
    "reva_core.audit.logger",
    "reva_core.models.llm",
    "reva_core.models.embedding",
    "reva_core.models.stt",
    "reva_core.models.tts",
    "reva_core.orchestration.lifecycle",
    "reva_core.api.app",
    "reva_core.__main__",
]


def test_package_has_version():
    assert reva_core.__version__


def test_all_phase_0_modules_import_cleanly():
    for module_name in MODULES:
        importlib.import_module(module_name)
