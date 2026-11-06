import pytest

from app import scoring


def load(client, rows):
    r = client.post("/ingest/records", json={"records": [
        {"email": e, "signals": s} for e, s in rows.items()
    ]})
    assert r.status_code == 200 and r.json()["errors"] == []


def scores(client, email):
    pid = client.get("/identity/lookup", params={"identifier": email}).json()["person_id"]
    return {s["model_name"]: s["score"] for s in client.get(f"/person/{pid}").json()["scores"]}


def test_formulas_by_hand():
    sig = {"orders": 4, "total_spend": 800.0, "days_since_last_order": 60, "tenure_days": 360}
    assert scoring.expected_gap(sig) == 100          # (360 - 60) / 3 gaps
    assert scoring.churn_risk(sig) == 0.2            # 60 / 300
    assert scoring.clv_12m(sig) == round(200.0 * 3.65 * 0.8, 2)   # aov 200, 3.65 orders/yr
    assert scoring.discount_sensitivity({"orders": 4, "promo_orders": 1}) == 0.25
    # one order, or no tenure -> default gap; very short gaps floored at 7 days
    assert scoring.expected_gap({"orders": 1, "tenure_days": 500, "days_since_last_order": 500}) == 90
    assert scoring.expected_gap({"orders": 5, "days_since_last_order": 3}) == 90
    assert scoring.expected_gap({"orders": 100, "tenure_days": 100, "days_since_last_order": 1}) == 7


def test_catalog_endpoint(client):
    body = client.get("/models").json()
    assert set(body["models"]) == {"rfm", "churn_risk", "clv", "discount"}


def test_run_writes_scores_and_ranks(client):
    load(client, {
        "best@x.com": {"orders": 20, "total_spend": 5000, "days_since_last_order": 5, "tenure_days": 400, "promo_orders": 2},
        "mid@x.com": {"orders": 5, "total_spend": 600, "days_since_last_order": 60, "tenure_days": 400, "promo_orders": 5},
        "gone@x.com": {"orders": 1, "total_spend": 40, "days_since_last_order": 700, "tenure_days": 700, "promo_orders": 0},
    })
    out = client.post("/models/run", json={}).json()
    assert out["ran"]["rfm"] == 3 and out["ran"]["churn_risk"] == 3
    best, gone = scores(client, "best@x.com"), scores(client, "gone@x.com")
    assert best["rfm_recency"] > gone["rfm_recency"]
    assert best["rfm_frequency"] > gone["rfm_frequency"]
    assert best["churn_risk"] < gone["churn_risk"] == 1.0
    assert gone["clv_12m"] == 0.0 and best["clv_12m"] > 0
    assert best["discount_sensitivity"] == 0.1
    assert out["rfm_segments"]["champions"] == 1
    assert out["rfm_segments"]["lapsed"] == 1


def test_rerun_overwrites_not_duplicates(client):
    load(client, {"a@x.com": {"orders": 2, "total_spend": 100, "days_since_last_order": 10}})
    client.post("/models/run", json={})
    client.post("/models/run", json={})
    pid = client.get("/identity/lookup", params={"identifier": "a@x.com"}).json()["person_id"]
    names = [s["model_name"] for s in client.get(f"/person/{pid}").json()["scores"]]
    assert len(names) == len(set(names))


def test_missing_inputs_skipped(client):
    load(client, {"only@x.com": {"orders": 3}})
    out = client.post("/models/run", json={"models": ["churn_risk", "discount"]}).json()
    assert out["ran"] == {"churn_risk": 0, "discount": 0}
    assert out["skipped"]["churn_risk"] >= 1


def test_zero_orders_not_scored(client):
    load(client, {"z@x.com": {"orders": 0, "total_spend": 0, "days_since_last_order": 30}})
    out = client.post("/models/run", json={"models": ["clv"]}).json()
    assert "clv_12m" not in scores(client, "z@x.com")


def test_unknown_model_400(client):
    r = client.post("/models/run", json={"models": ["nope"]})
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_scores_usable_in_audience(client):
    load(client, {
        "hi@x.com": {"orders": 10, "total_spend": 3000, "days_since_last_order": 5, "tenure_days": 300},
        "lo@x.com": {"orders": 1, "total_spend": 20, "days_since_last_order": 400, "tenure_days": 400},
    })
    client.post("/models/run", json={})
    aud = client.post("/audience", json={"name": "valuable", "rule": [{"field": "clv_12m", "op": ">", "value": 500}]}).json()
    prev = client.get(f"/audience/{aud['id']}/preview").json()
    pid = client.get("/identity/lookup", params={"identifier": "hi@x.com"}).json()["person_id"]
    assert pid in prev["sample_person_ids"]
    lo = client.get("/identity/lookup", params={"identifier": "lo@x.com"}).json()["person_id"]
    assert lo not in prev["sample_person_ids"]


def test_models_require_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "k")
    assert client.post("/models/run", json={}).status_code == 401
    assert client.get("/models").status_code == 401
