"""AR-CORE-003: capability-driven provider selection with refusal fallback."""

from __future__ import annotations

import pytest

from reva_core.providers.registry import ProviderKind, ProviderRegistry, ProviderSpec
from reva_core.shared.errors import ProviderError, ProviderErrorKind


class _Healthy:
    def __init__(self, name: str) -> None:
        self.name = name

    async def health(self) -> bool:
        return True


class _Unhealthy:
    name = "unhealthy"

    async def health(self) -> bool:
        return False


def _spec(
    name: str,
    *,
    caps: frozenset[str] = frozenset({"speak", "stop"}),
    default: bool = False,
    deterministic: bool = False,
    factory=None,
) -> ProviderSpec:
    return ProviderSpec(
        kind=ProviderKind.TTS,
        name=name,
        factory=factory or (lambda: _Healthy(name)),
        capabilities=caps,
        default=default,
        deterministic=deterministic,
    )


async def test_default_provider_is_selected_without_a_preference():
    registry = ProviderRegistry()
    registry.register(_spec("chatterbox"))
    registry.register(_spec("kokoro", default=True))

    selection = await registry.acquire(ProviderKind.TTS)

    assert selection.name == "kokoro"
    assert selection.skipped == ()


async def test_explicit_preference_beats_the_default():
    registry = ProviderRegistry()
    registry.register(_spec("chatterbox"))
    registry.register(_spec("kokoro", default=True))

    selection = await registry.acquire(ProviderKind.TTS, preferred="chatterbox")

    assert selection.name == "chatterbox"


async def test_required_capabilities_filter_candidates():
    registry = ProviderRegistry()
    registry.register(_spec("legacy", caps=frozenset({"speak"}), default=True))
    registry.register(_spec("kokoro", caps=frozenset({"speak", "stop"})))

    selection = await registry.acquire(ProviderKind.TTS, require=frozenset({"stop"}))

    assert selection.name == "kokoro"


async def test_refusing_provider_falls_back_and_records_why():
    def refuse():
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, "asset hash mismatch")

    registry = ProviderRegistry()
    registry.register(_spec("kokoro", default=True, factory=refuse))
    registry.register(_spec("chatterbox"))

    selection = await registry.acquire(ProviderKind.TTS)

    assert selection.name == "chatterbox"
    assert selection.skipped == (("kokoro", "asset hash mismatch"),)


async def test_unhealthy_provider_is_skipped():
    registry = ProviderRegistry()
    registry.register(_spec("sick", default=True, factory=_Unhealthy))
    registry.register(_spec("well"))

    selection = await registry.acquire(ProviderKind.TTS)

    assert selection.name == "well"
    assert selection.skipped[0][0] == "sick"


async def test_all_candidates_refusing_raises_unavailable():
    def refuse():
        raise ProviderError(ProviderErrorKind.UNAVAILABLE, "nope")

    registry = ProviderRegistry()
    registry.register(_spec("kokoro", default=True, factory=refuse))

    with pytest.raises(ProviderError) as excinfo:
        await registry.acquire(ProviderKind.TTS)

    assert excinfo.value.kind == ProviderErrorKind.UNAVAILABLE


async def test_empty_kind_raises_unavailable():
    with pytest.raises(ProviderError):
        await ProviderRegistry().acquire(ProviderKind.TTS)


async def test_deterministic_provider_is_never_the_silent_default():
    registry = ProviderRegistry()
    registry.register(_spec("fake", default=True, deterministic=True))

    with pytest.raises(ProviderError):
        await registry.acquire(ProviderKind.TTS)

    selection = await registry.acquire(ProviderKind.TTS, allow_deterministic=True)
    assert selection.name == "fake"


async def test_unhealthy_provider_is_shut_down_when_skipped():
    closed: list[str] = []

    class _Closing(_Unhealthy):
        async def shutdown(self) -> None:
            closed.append("closed")

    registry = ProviderRegistry()
    registry.register(_spec("sick", default=True, factory=_Closing))
    registry.register(_spec("well"))

    await registry.acquire(ProviderKind.TTS)

    assert closed == ["closed"]


def test_duplicate_registration_is_rejected():
    registry = ProviderRegistry()
    registry.register(_spec("kokoro"))

    with pytest.raises(ValueError):
        registry.register(_spec("kokoro"))


def test_names_lists_registered_providers_per_kind():
    registry = ProviderRegistry()
    registry.register(_spec("kokoro"))
    registry.register(_spec("chatterbox"))

    assert registry.names(ProviderKind.TTS) == ("kokoro", "chatterbox")
    assert registry.names(ProviderKind.STT) == ()
