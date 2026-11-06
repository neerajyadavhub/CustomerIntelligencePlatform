import pytest

from .conftest import create_audience, preview_ids

# Seeded propensity_to_convert: 4471=0.82, 2290=0.71, 8813=0.91, 5541=0.19


def matched(client, rule):
    audience = create_audience(client, "test", rule)
    preview = preview_ids(client, audience["id"])
    return set(preview["sample_person_ids"]), preview["matched_count"]


def test_single_condition_on_a_model_score(client):
    ids, count = matched(client, [{"field": "propensity_to_convert", "op": ">", "value": 0.7}])
    assert ids == {"PER-4471", "PER-2290", "PER-8813"}
    assert count == 3


def test_conditions_are_anded(client):
    ids, _ = matched(client, [
        {"field": "propensity_to_convert", "op": ">", "value": 0.7},
        {"field": "suppressed", "op": "=", "value": 0},
    ])
    assert ids == {"PER-4471", "PER-8813"}


@pytest.mark.parametrize(
    "op, value, expected",
    [
        (">=", 0.82, {"PER-4471", "PER-8813"}),
        ("<", 0.5, {"PER-5541"}),
        ("<=", 0.71, {"PER-2290", "PER-5541"}),
        ("=", 0.91, {"PER-8813"}),
        ("!=", 0.82, {"PER-2290", "PER-8813", "PER-5541"}),
    ],
)
def test_every_operator(client, op, value, expected):
    ids, _ = matched(client, [{"field": "propensity_to_convert", "op": op, "value": value}])
    assert ids == expected


def test_fields_can_reference_signals_as_well_as_scores(client):
    ids, _ = matched(client, [{"field": "lifetime_spend", "op": ">", "value": 5000}])
    assert ids == {"PER-8813"}


def test_unknown_field_matches_nobody(client):
    _, count = matched(client, [{"field": "no_such_field", "op": ">", "value": 0}])
    assert count == 0


def test_invalid_operator_is_rejected_when_created(client):
    response = client.post("/audience", json={
        "name": "bad",
        "rule": [{"field": "propensity_to_convert", "op": "~", "value": 0.7}],
    })
    assert response.status_code == 422


def test_non_numeric_value_is_rejected_when_created(client):
    response = client.post("/audience", json={
        "name": "bad",
        "rule": [{"field": "propensity_to_convert", "op": ">", "value": "high"}],
    })
    assert response.status_code == 422


def test_seeded_demo_audience_is_listed(client):
    names = [a["name"] for a in client.get("/audience").json()]
    assert "Q3 Reactivation" in names


def test_sync_reports_match_rate_against_total(client):
    audience = create_audience(client, "sync me", [{"field": "propensity_to_convert", "op": ">", "value": 0.7}])
    response = client.post(f"/audience/{audience['id']}/sync", json={"channel": "meta_ads"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synced"
    assert body["total_count"] == 3
    assert body["matched_count"] == 2  # int(3 * 0.92): not every record matches on a channel

    syncs = client.get(f"/audience/{audience['id']}/syncs").json()
    assert [s["channel"] for s in syncs] == ["meta_ads"]


def test_syncing_an_empty_audience_fails_instead_of_pretending(client):
    audience = create_audience(client, "nobody", [{"field": "churn_risk", "op": ">", "value": 0.99}])
    body = client.post(f"/audience/{audience['id']}/sync", json={"channel": "email"}).json()
    assert body["status"] == "failed"
    assert body["total_count"] == 0


@pytest.mark.parametrize("path, method", [
    ("/audience/AUD-NOPE/preview", "get"),
    ("/audience/AUD-NOPE/sync", "post"),
])
def test_unknown_audience_is_404(client, path, method):
    kwargs = {"json": {"channel": "email"}} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 404
