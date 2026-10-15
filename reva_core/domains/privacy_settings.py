"""The three per-domain privacy switches in one place (ARD-300 `/v1/settings/privacy`, FR-DOM-006).

* `sync`: may this domain replicate to a paired phone.
* `devices`: may a paired device reach this domain at all. Off beats `sync`.
* `hosted_model`: may a hosted (cloud) model see this domain's content.

Each switch is stored where the code that enforces it already reads it, so there is one truth:
`sync` in the domain privacy file (the pairing gateway reads it), `devices` next to it (the gateway
checks it first), and `hosted_model` in the cloud settings (the consent filter reads it). Finance,
Health, Memory and Personal start with no hosted-model access. A domain that is not built yet has
no data to sync or share, so its `sync` and `devices` are fixed off and only `hosted_model` can be
chosen ahead of time.
"""

from __future__ import annotations

from typing import Any

from reva_core.domains.privacy import DEFAULTS, DomainPrivacyStore
from reva_core.domains.service import DomainRequestError
from reva_core.providers.cloud import HOSTED_DOMAINS, CloudSettingsStore

SWITCHES = ("sync", "devices", "hosted_model")


class PrivacySettings:
    def __init__(self, domain_privacy: DomainPrivacyStore, cloud: CloudSettingsStore) -> None:
        self._privacy = domain_privacy
        self._cloud = cloud

    def snapshot(self) -> dict[str, dict[str, bool]]:
        hosted = self._cloud.load().domains
        view: dict[str, dict[str, bool]] = {}
        for domain in HOSTED_DOMAINS:
            built = domain in DEFAULTS
            view[domain] = {
                "sync": built and self._privacy.get(domain)["sync"],
                "devices": built and self._privacy.devices_allowed(domain),
                "hosted_model": hosted.get(domain) is True,
            }
        return view

    def update(self, patch: dict[str, dict[str, Any]]) -> dict[str, dict[str, bool]]:
        """All-or-nothing: every entry is checked before anything is written."""
        if not patch:
            raise DomainRequestError("validation_error", 422, "nothing to change")
        for domain, switches in patch.items():
            if domain not in HOSTED_DOMAINS:
                raise DomainRequestError("not_found", 404, f"unknown domain {domain!r}")
            if not isinstance(switches, dict) or not switches:
                raise DomainRequestError("validation_error", 422, "nothing to change", domain)
            for name, value in switches.items():
                if name not in SWITCHES:
                    raise DomainRequestError(
                        "validation_error", 422, "unknown privacy switch", name
                    )
                if not isinstance(value, bool):
                    raise DomainRequestError("validation_error", 422, "must be true or false", name)
                if name in ("sync", "devices") and domain not in DEFAULTS:
                    raise DomainRequestError(
                        "validation_error",
                        422,
                        f"{domain} is not built yet; nothing to share",
                        name,
                    )
        for domain, switches in patch.items():
            if "sync" in switches:
                self._privacy.update(domain, {"sync": switches["sync"]})
            if "devices" in switches:
                self._privacy.set_devices(domain, switches["devices"])
            if "hosted_model" in switches:
                self.set_hosted_model(domain, switches["hosted_model"])
        return self.snapshot()

    def set_hosted_model(self, domain: str, allowed: bool) -> None:
        """The consent filter's switch, mirrored into the domain's own privacy record."""
        settings = self._cloud.load()
        settings.domains[domain] = allowed
        self._cloud.save(settings)
        if domain in DEFAULTS:
            self._privacy.update(domain, {"hosted_model_access": allowed})
