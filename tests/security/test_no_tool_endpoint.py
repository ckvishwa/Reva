"""Phase 1A must not add any tool/action execution surface (ADR-008,
ADR-012) — preserved even while adding real domain routes."""

from tests.conftest import iter_effective_routes

_ALLOWED_DOMAIN_ROUTES = {
    ("POST", "/v1/messages"),
    ("POST", "/v1/memories"),
    ("GET", "/v1/memories"),
    ("GET", "/v1/audit-events"),
    ("POST", "/v1/voice/speech"),
    ("POST", "/v1/voice/transcriptions"),
    ("GET", "/v1/domains"),
    ("GET", "/v1/domains/changes"),
    ("GET", "/v1/domains/{domain}/export"),
    ("GET", "/v1/domains/{domain}/privacy"),
    ("PATCH", "/v1/domains/{domain}/privacy"),
    ("GET", "/v1/domains/finance/conflicts"),
    ("POST", "/v1/domains/finance/conflicts/{conflict_id}/resolve"),
    ("POST", "/v1/domains/{domain}/import"),
    ("GET", "/v1/domains/{domain}/reports/{name}"),
    ("GET", "/v1/domains/{domain}/{collection}"),
    ("POST", "/v1/domains/{domain}/{collection}"),
    ("GET", "/v1/domains/{domain}/{collection}/{item_id}"),
    ("PATCH", "/v1/domains/{domain}/{collection}/{item_id}"),
    ("DELETE", "/v1/domains/{domain}/{collection}/{item_id}"),
    ("POST", "/v1/domains/finance/bills/{item_id}/mark-paid"),
    ("GET", "/v1/today"),
    # Devices page controls for the pairing gateway (SYNC-1b). The phone-facing gateway is a
    # separate app, covered by tests/gateway/test_listener.py.
    ("GET", "/v1/devices"),
    ("PATCH", "/v1/devices/gateway"),
    ("POST", "/v1/devices/pairing"),
    ("POST", "/v1/devices/pairing/approve"),
    ("POST", "/v1/devices/pairing/deny"),
    ("POST", "/v1/devices/{device_id}/revoke"),
    ("GET", "/v1/settings/cloud"),
    ("PUT", "/v1/settings/cloud"),
    ("PUT", "/v1/settings/cloud/key"),
    ("GET", "/v1/settings/privacy"),
    ("PUT", "/v1/settings/privacy"),
    ("DELETE", "/v1/settings/cloud/key"),
    ("POST", "/v1/voice/sessions"),
    ("DELETE", "/v1/voice/sessions/{session_id}"),
    ("GET", "/v1/voice/sessions/{session_id}/audio/{audio_id}"),
    # B3: the typed action broker. Exactly these three paths; every other "action" path stays
    # forbidden (see test_no_tool_or_action_keyword_in_any_route_path).
    ("POST", "/v1/actions/proposals"),
    ("POST", "/v1/actions/{action_id}/approval"),
    ("GET", "/v1/actions/{action_id}"),
    ("PUT", "/v1/actions/{action_id}"),
    # B3c: the allowlist the owner controls, and the read-only Activity list.
    ("GET", "/v1/apps"),
    ("PUT", "/v1/apps/discovered"),
    ("PUT", "/v1/apps/{key}"),
    ("DELETE", "/v1/apps/{key}"),
    ("GET", "/v1/activity"),
}

_ALLOWED_ACTION_PATHS = {
    "/v1/actions/proposals",
    "/v1/actions/{action_id}/approval",
    "/v1/actions/{action_id}",
}

_ALLOWED_NON_DOMAIN_PREFIXES = {
    "/health",
    "/version",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}


def test_only_the_known_v1_endpoints_exist(client):
    found = set()
    for route in iter_effective_routes(client.app):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path is None or path in _ALLOWED_NON_DOMAIN_PREFIXES:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            found.add((method, path))
    assert found == _ALLOWED_DOMAIN_ROUTES


def test_no_tool_or_action_keyword_in_any_route_path(client):
    for route in iter_effective_routes(client.app):
        path = getattr(route, "path", None) or ""
        assert "tool" not in path.lower()
        if path in _ALLOWED_ACTION_PATHS:
            continue
        assert "action" not in path.lower()
        assert "execute" not in path.lower()
        assert "command" not in path.lower()


def test_no_other_action_path_is_routable(client, auth_headers):
    for method, path in [
        ("post", "/v1/actions"),
        ("post", "/v1/actions/execute"),
        ("post", "/v1/actions/some-id/execute"),
        ("post", "/v1/actions/some-id/run"),
        ("delete", "/v1/actions/some-id"),
        ("get", "/v1/actions"),
        ("get", "/v1/actions/some-id/grant"),
    ]:
        response = getattr(client, method)(path, headers=auth_headers)
        assert response.status_code in (404, 405), (method, path, response.status_code)
