"""B0 / VOICE-1 R-1: the shared bearer check is non-ASCII safe, constant-time and fails closed."""

from __future__ import annotations

import pytest

from reva_core.api.auth import bearer_token_matches

TOKEN = "s3cret-token_value"


def test_the_exact_token_is_accepted() -> None:
    assert bearer_token_matches(f"Bearer {TOKEN}", TOKEN)
    assert bearer_token_matches(f"Bearer  {TOKEN}  ", TOKEN)  # surrounding spaces are trimmed


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Bearer    ",
        "bearer " + TOKEN,
        "Basic " + TOKEN,
        TOKEN,
        "Bearer " + TOKEN + "x",
        "Bearer " + TOKEN[:-1],
        "Bearer café-token",
        "Bearer ÿþ",
        "Bearer \ud800",  # a lone surrogate cannot be encoded to UTF-8
        "Bearer " + "é" * 5000,
    ],
)
def test_anything_else_is_refused_without_raising(header: str | None) -> None:
    assert bearer_token_matches(header, TOKEN) is False


@pytest.mark.parametrize("expected", ["", "é-token"])
def test_an_empty_expected_token_never_matches(expected: str) -> None:
    assert bearer_token_matches("Bearer ", expected) is False
    assert bearer_token_matches("Bearer anything", "") is False


def test_a_non_ascii_expected_token_still_compares_correctly() -> None:
    assert bearer_token_matches("Bearer é-token", "é-token")
    assert not bearer_token_matches("Bearer e-token", "é-token")
