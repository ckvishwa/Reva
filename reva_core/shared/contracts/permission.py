"""Permission contract. PLANNED: enforcement engine implemented in `policy/`."""

from __future__ import annotations

from enum import StrEnum

from reva_core.shared.contracts.base import UtcDatetime, VersionedModel
from reva_core.shared.contracts.ids import EntityId


class PermissionCapability(StrEnum):
    """Matches the V1 PRD permission table (section 9)."""

    MICROPHONE = "microphone"
    NOTIFICATIONS = "notifications"
    ACTIVE_WINDOW_CONTEXT = "active_window_context"
    OPEN_APPS_FILES_URLS = "open_apps_files_urls"
    CLIPBOARD_WRITE = "clipboard_write"
    CLOUD_MODEL_PROCESSING = "cloud_model_processing"
    DEVICE_PAIRING_SYNC = "device_pairing_sync"


class Permission(VersionedModel):
    id: EntityId
    capability: PermissionCapability
    granted: bool = False
    updated_at: UtcDatetime
