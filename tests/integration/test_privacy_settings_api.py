"""B4: /v1/settings/privacy: sync / devices / hosted-model switches, one truth, fail closed."""

from __future__ import annotations

import json

import pytest

from reva_core.providers.cloud import DEFAULT_OFF_DOMAINS, HOSTED_DOMAINS, ConsentFilter

URL = "/v1/settings/privacy"


def test_defaults_are_hosted_model_off_everywhere_and_finance_syncs(client, auth_headers) -> None:
    body = client.get(URL, headers=auth_headers).json()

    assert set(body["domains"]) == set(HOSTED_DOMAINS)
    assert not any(d["hosted_model"] for d in body["domains"].values())
    assert body["domains"]["finance"] == {"sync": True, "devices": True, "hosted_model": False}
    # A domain that is not built has nothing to share.
    assert body["domains"]["health"] == {"sync": False, "devices": False, "hosted_model": False}
    for name in DEFAULT_OFF_DOMAINS:
        assert body["domains"][name]["hosted_model"] is False


def test_it_needs_the_bearer_token(client) -> None:
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"domains": {}}).status_code == 401


def test_one_write_changes_the_switches_where_they_are_enforced(client, auth_headers, core) -> None:
    response = client.put(
        URL,
        headers=auth_headers,
        json={
            "domains": {
                "finance": {"sync": False, "hosted_model": True},
                "coach": {"hosted_model": True},
            }
        },
    )

    body = response.json()["domains"]
    assert response.status_code == 200
    assert body["finance"] == {"sync": False, "devices": True, "hosted_model": True}
    assert body["coach"]["hosted_model"] is True
    # The same switches, read from the places that enforce them.
    assert core.domain_privacy.get("finance") == {"sync": False, "hosted_model_access": True}
    assert core.cloud_settings_store.load().domains["finance"] is True
    assert core.cloud_settings_store.load().domains["coach"] is True


def test_the_hosted_model_switch_and_the_domain_privacy_record_stay_the_same_switch(
    client, auth_headers, core
) -> None:
    client.patch(
        "/v1/domains/finance/privacy", headers=auth_headers, json={"hosted_model_access": True}
    )
    after_domain_patch = client.get(URL, headers=auth_headers).json()["domains"]["finance"]
    client.put("/v1/settings/cloud", headers=auth_headers, json={"domains": {"finance": False}})
    after_cloud_put = client.get(URL, headers=auth_headers).json()["domains"]["finance"]

    assert after_domain_patch["hosted_model"] is True
    assert after_cloud_put["hosted_model"] is False
    assert core.domain_privacy.get("finance")["hosted_model_access"] is False


def test_the_consent_filter_follows_the_unified_switch(client, auth_headers, core) -> None:
    client.put(URL, headers=auth_headers, json={"domains": {"career": {"hosted_model": True}}})
    # The master cloud switch stays off, so even a consented domain is not sent.
    settings = core.cloud_settings_store.load()
    assert ConsentFilter(settings).apply({"career": "x"}).included == {}
    settings.enabled = True
    filtered = ConsentFilter(settings).apply({"career": "x", "finance": "y", "unknown": "z"})
    assert filtered.included == {"career": "x"}
    assert set(filtered.omitted) == {"finance", "unknown"}


@pytest.mark.parametrize(
    ("patch", "status", "field"),
    [
        ({}, 422, None),
        ({"finance": {}}, 422, None),
        ({"finance": {"sync": "yes"}}, 422, "sync"),
        ({"finance": {"telepathy": True}}, 422, "telepathy"),
        ({"health": {"sync": True}}, 422, "sync"),
        ({"health": {"devices": True}}, 422, "devices"),
        ({"nowhere": {"hosted_model": True}}, 404, None),
        ({"finance": "on"}, 422, None),
    ],
)
def test_bad_updates_are_typed_errors_and_change_nothing(
    client, auth_headers, core, patch, status, field
) -> None:
    before = client.get(URL, headers=auth_headers).json()

    response = client.put(URL, headers=auth_headers, json={"domains": patch})

    assert response.status_code == status
    assert response.json()["code"].startswith(("DOMAIN.", "CORE."))
    if field:
        assert response.json().get("field") == field
    assert client.get(URL, headers=auth_headers).json() == before


def test_a_mixed_update_with_one_bad_entry_applies_nothing(client, auth_headers) -> None:
    before = client.get(URL, headers=auth_headers).json()

    response = client.put(
        URL,
        headers=auth_headers,
        json={"domains": {"career": {"hosted_model": True}, "finance": {"sync": "no"}}},
    )

    assert response.status_code == 422
    assert client.get(URL, headers=auth_headers).json() == before


def test_the_privacy_file_never_holds_more_than_switches(client, auth_headers, core) -> None:
    client.put(URL, headers=auth_headers, json={"domains": {"finance": {"devices": False}}})

    text = (core.settings.data_dir / "domain_privacy.json").read_text(encoding="utf-8")

    assert json.loads(text)["finance"]["devices"] is False
    assert set(json.loads(text)["finance"]) <= {"sync", "hosted_model_access", "devices"}


def test_an_unsupported_schema_version_is_refused(client, auth_headers) -> None:
    response = client.put(URL, headers=auth_headers, json={"schema_version": "3", "domains": {}})

    assert response.status_code == 422
    assert response.json()["code"] == "CORE.UNSUPPORTED_VERSION"
