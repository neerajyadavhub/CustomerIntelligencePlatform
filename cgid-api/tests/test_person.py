import pytest


def test_profile_combines_identities_signals_and_scores(client):
    body = client.get("/person/PER-4471").json()
    assert len(body["identities"]) == 3

    signals = {s["name"]: s["value"] for s in body["signals"]}
    assert signals["lifetime_spend"] == 4920.0
    assert signals["marketing_consent"] == 1.0

    scores = {s["model_name"]: s["score"] for s in body["scores"]}
    assert scores["propensity_to_convert"] == pytest.approx(0.82)
    assert scores["churn_risk"] == pytest.approx(0.41)


def test_profile_starts_with_no_decisions(client):
    assert client.get("/person/PER-4471").json()["recent_decisions"] == []


def test_unknown_person_is_404(client):
    assert client.get("/person/PER-0000").status_code == 404
