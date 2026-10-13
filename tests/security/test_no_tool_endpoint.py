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
        assert "action" not in path.lower()
        assert "execute" not in path.lower()
        assert "command" not in path.lower()
