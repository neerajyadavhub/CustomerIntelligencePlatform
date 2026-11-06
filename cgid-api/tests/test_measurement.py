from types import SimpleNamespace

import pytest

from app import measurement_engine

from .conftest import create_audience


def demo_audience_id(client):
    audiences = client.get("/audience").json()
    return next(a["id"] for a in audiences if a["name"] == "Q3 Reactivation")


def performance(client, audience_id):
    response = client.get(f"/audience/{audience_id}/performance")
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_audience_rolls_up_both_channels(client):
    perf = performance(client, demo_audience_id(client))
    assert perf["audience_name"] == "Q3 Reactivation"
    assert perf["channels"] == ["email", "meta_ads"]
    assert {c["channel"] for c in perf["by_channel"]} == {"email", "meta_ads"}
    assert len(perf["timeseries"]) == 2 * measurement_engine.HISTORY_DAYS


def test_totals_equal_the_sum_of_the_channels(client):
    perf = performance(client, demo_audience_id(client))
    for field in ["impressions", "clicks", "conversions"]:
        assert perf[field] == sum(c[field] for c in perf["by_channel"])
    assert perf["spend"] == pytest.approx(sum(c["spend"] for c in perf["by_channel"]), abs=0.05)
    assert perf["revenue"] == pytest.approx(sum(c["revenue"] for c in perf["by_channel"]), abs=0.05)


def test_derived_rates_are_consistent_with_the_raw_counts(client):
    perf = performance(client, demo_audience_id(client))
    assert perf["ctr"] == pytest.approx(perf["clicks"] / perf["impressions"], abs=1e-4)
    assert perf["cpa"] == pytest.approx(perf["spend"] / perf["conversions"], abs=0.01)
    assert perf["roas"] == pytest.approx(perf["revenue"] / perf["spend"], abs=0.01)


def test_timeseries_is_in_date_order(client):
    dates = [p["date"] for p in performance(client, demo_audience_id(client))["timeseries"]]
    assert dates == sorted(dates)


def test_syncing_a_new_audience_starts_measurement_automatically(client):
    audience = create_audience(client, "fresh", [{"field": "propensity_to_convert", "op": ">", "value": 0.5}])
    client.post(f"/audience/{audience['id']}/sync", json={"channel": "meta_ads"})

    perf = performance(client, audience["id"])
    assert perf["channels"] == ["meta_ads"]
    assert len(perf["timeseries"]) == measurement_engine.HISTORY_DAYS


def test_audience_that_was_never_synced_reports_zeros_not_an_error(client):
    audience = create_audience(client, "idle", [{"field": "propensity_to_convert", "op": ">", "value": 0.5}])
    perf = performance(client, audience["id"])
    assert perf["channels"] == []
    assert perf["timeseries"] == []
    assert perf["impressions"] == 0
    assert perf["roas"] == 0.0


def test_failed_sync_has_no_performance_data(client):
    audience = create_audience(client, "nobody", [{"field": "churn_risk", "op": ">", "value": 0.99}])
    client.post(f"/audience/{audience['id']}/sync", json={"channel": "email"})

    perf = performance(client, audience["id"])
    assert perf["channels"] == []
    assert perf["timeseries"] == []


def test_unknown_audience_is_404(client):
    assert client.get("/audience/AUD-NOPE/performance").status_code == 404


def test_summarize_handles_no_data_without_dividing_by_zero():
    assert measurement_engine.summarize([]) == {
        "impressions": 0, "clicks": 0, "spend": 0.0, "conversions": 0,
        "revenue": 0.0, "ctr": 0.0, "cpa": 0.0, "roas": 0.0,
    }


def test_summarize_computes_rates_from_totals_not_averages_of_rates():
    rows = [
        SimpleNamespace(impressions=1000, clicks=10, spend=10.0, conversions=1, revenue=40.0),
        SimpleNamespace(impressions=9000, clicks=290, spend=90.0, conversions=9, revenue=360.0),
    ]
    summary = measurement_engine.summarize(rows)
    assert summary["ctr"] == 0.03     # 300 / 10000, not the mean of 1% and 3.2%
    assert summary["cpa"] == 10.0     # 100 / 10
    assert summary["roas"] == 4.0     # 400 / 100
