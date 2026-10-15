"""B4: one typed error shape everywhere; an unknown protocol major is refused (AR-CORE-006)."""

from __future__ import annotations

import re

import pytest

from reva_core.shared.error_codes import _BY_ERROR, _BY_STATUS, ErrorCode, code_for
from reva_core.shared.versioning import UnsupportedSchemaVersion, ensure_supported, parse_major

SECRET = "sk-ant-api03-must-never-be-echoed-0123456789"
CODE = re.compile(r"^[A-Z]+\.[A-Z_]+$")


# ------------------------------------------------------------------- the mapping


def test_every_known_error_string_and_status_maps_to_a_taxonomy_code() -> None:
    for error, code in _BY_ERROR.items():
        assert code_for(error, 500) == code and CODE.match(code.value), error
    for status, code in _BY_STATUS.items():
        assert code_for("something_new", status) == code
    assert code_for("something_new", 418) == ErrorCode.CORE_INTERNAL


def test_the_taxonomy_has_the_codes_the_apps_switch_on() -> None:
    values = {c.value for c in ErrorCode}

    assert {
        "DOMAIN.VALIDATION",
        "DOMAIN.LOCKED",
        "DOMAIN.MIGRATION_FAILED",
        "DOMAIN.CONSENT_REQUIRED",
        "AVATAR.UNAVAILABLE",
    } <= values
    assert all(CODE.match(v) for v in values)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ("domain_locked", "DOMAIN.LOCKED"),
        ("domain_wrong_key", "DOMAIN.LOCKED"),
        ("domain_migration_failed", "DOMAIN.MIGRATION_FAILED"),
        ("validation_error", "DOMAIN.VALIDATION"),
        ("sync_rejected", "DOMAIN.CONSENT_REQUIRED"),
        ("key_required", "DOMAIN.CONSENT_REQUIRED"),
        ("Unauthorized", "AUTH.REQUIRED"),
    ],
)
def test_the_named_codes(error: str, code: str) -> None:
    assert code_for(error, 400).value == code


# ------------------------------------------------------------------- over HTTP


def test_a_missing_token_is_auth_required_in_the_one_shape(client) -> None:
    response = client.get("/v1/devices")

    body = response.json()
    assert response.status_code == 401
    assert body["error"] == "Unauthorized" and body["code"] == "AUTH.REQUIRED"
    assert set(body) <= {"error", "code", "correlation_id"}


def test_an_unknown_route_is_not_found_in_the_same_shape(client, auth_headers) -> None:
    response = client.get("/v1/nothing-here", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "CORE.NOT_FOUND"


def test_a_bad_body_is_a_typed_validation_error_and_never_echoes_the_input(
    client, auth_headers
) -> None:
    response = client.post(
        "/v1/actions/proposals",
        headers=auth_headers,
        json={"capability": 5, "args": SECRET, "note": SECRET},
    )

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "DOMAIN.VALIDATION" or body["code"] == "CORE.VALIDATION"
    assert body["error"] == "validation_error" and "field" in body
    assert SECRET not in response.text and "input" not in body and "detail" not in body


def test_every_error_response_has_error_and_code_and_nothing_private(client, auth_headers) -> None:
    probes = [
        client.get("/v1/actions/does-not-exist", headers=auth_headers),
        client.post(
            "/v1/actions/nope/approval", headers=auth_headers, json={"decision": "approve"}
        ),
        client.post("/v1/voice/sessions", headers=auth_headers, json={"x": SECRET}),
        client.put("/v1/settings/cloud", headers=auth_headers, json={"enabled": "maybe"}),
        client.get("/v1/devices"),
    ]

    for response in probes:
        body = response.json()
        assert response.status_code >= 400
        assert "error" in body and CODE.match(body["code"]), (response.url, body)
        assert SECRET not in response.text
        assert "Traceback" not in response.text and "\\" not in body["error"]


# ------------------------------------------------------------------ versions


@pytest.mark.parametrize("version", [None, "2", "2.0", "2.7", 2, "2.0.1"])
def test_the_supported_major_and_newer_minors_are_accepted(version) -> None:
    ensure_supported(version)


@pytest.mark.parametrize(
    "version", ["1", "3", "3.0", 1, 3, "0", "x", "", "2x", True, [2], {"a": 1}]
)
def test_any_other_major_or_a_non_version_is_refused(version) -> None:
    with pytest.raises(UnsupportedSchemaVersion):
        ensure_supported(version)


def test_parse_major_is_strict_about_what_a_version_is() -> None:
    assert parse_major("2.1") == 2 and parse_major(" 3 ") == 3
    for bad in ("two", "-1", "2e1", "٢", "99999", None):
        with pytest.raises(UnsupportedSchemaVersion):
            parse_major(bad)


@pytest.mark.parametrize("path", ["/v1/voice/sessions"])
def test_a_request_for_another_major_is_refused_with_its_own_code(
    client, auth_headers, path
) -> None:
    refused = client.post(path, headers=auth_headers, json={"schema_version": "3"})
    older = client.post(path, headers=auth_headers, json={"schema_version": "1.9"})
    junk = client.post(path, headers=auth_headers, json={"schema_version": "banana"})
    fine = client.post(path, headers=auth_headers, json={"schema_version": "2.4"})
    absent = client.post(path, headers=auth_headers, json={})

    for response in (refused, older, junk):
        assert response.status_code == 422
        assert response.json()["code"] == "CORE.UNSUPPORTED_VERSION"
        assert response.json()["field"] == "schema_version"
    assert fine.status_code == 201 and absent.status_code == 201


def test_action_requests_check_the_version_too(client, auth_headers) -> None:
    body = {"capability": "windows.app.open", "args": {"app_key": "notepad"}}

    refused = client.post(
        "/v1/actions/proposals", headers=auth_headers, json={**body, "schema_version": "9"}
    )

    assert refused.status_code == 422
    assert refused.json()["code"] == "CORE.UNSUPPORTED_VERSION"


def test_a_websocket_control_message_for_another_major_is_a_typed_error(
    client, auth_headers
) -> None:
    session = client.post("/v1/voice/sessions", headers=auth_headers, json={}).json()
    url = f"/v1/voice/sessions/{session['session_id']}/events"

    with client.websocket_connect(url, headers=auth_headers) as ws:
        ws.receive_json()
        ws.send_json({"type": "capture.requested", "schema_version": "3"})
        refused = ws.receive_json()
        ws.send_json({"type": "capture.requested", "schema_version": "2.2"})
        accepted = ws.receive_json()

    assert refused["payload"]["code"] == "BAD_CONTROL_MESSAGE"
    assert accepted["kind"] == "session.state"
