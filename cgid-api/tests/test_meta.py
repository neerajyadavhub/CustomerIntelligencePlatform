import json
import os

import httpx
import pytest

from app import channels, doctor, measurement_engine, meta, migrate, models
from tests.conftest import create_audience


# ------------------------------------------------------------- fake Meta
class FakeMeta:
    """Stands in for graph.facebook.com. Records requests; answers from `routes`."""

    def __init__(self):
        self.requests = []
        self.routes = {}
        self.audience_counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode())) if request.content else {}
        entry = {"method": request.method, "path": request.url.path, "query": dict(request.url.params), "body": body}
        self.requests.append(entry)
        for (method, suffix), responder in self.routes.items():
            if request.method == method and request.url.path.endswith(suffix):
                out = responder(entry) if callable(responder) else responder
                if isinstance(out, httpx.Response):
                    return out
                return httpx.Response(200, json=out)
        return httpx.Response(404, json={"error": {"message": f"no route {request.method} {request.url.path}", "code": 803}})

    def client(self, sleeps=None):
        return meta.MetaClient("TOKEN", "123456", transport=httpx.MockTransport(self.handler),
                               sleep=(sleeps.append if sleeps is not None else lambda s: None))


def err(code, message="boom", sub=None, status=400):
    e = {"message": message, "code": code}
    if sub:
        e["error_subcode"] = sub
    return httpx.Response(status, json={"error": e})


@pytest.fixture()
def fake(monkeypatch):
    f = FakeMeta()

    def create(entry):
        f.audience_counter += 1
        return {"id": f"AUD{f.audience_counter}"}

    f.routes[("POST", "/customaudiences")] = create
    f.routes[("POST", "/usersreplace")] = lambda e: {"num_received": 1, "num_invalid_entries": 0}
    f.routes[("GET", "/act_123456")] = {"name": "Acme Ads", "account_status": 1, "currency": "USD"}
    f.routes[("DELETE", "/AUD1")] = {"success": True}
    monkeypatch.setenv("META_MODE", "live")
    monkeypatch.setenv("META_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "123456")
    monkeypatch.setenv("META_PULL_MIN_MINUTES", "0")
    monkeypatch.setattr(meta, "get_client", lambda: f.client())
    import app.main as main
    monkeypatch.setattr(main, "metrics_provider", measurement_engine.get_metrics_provider())
    measurement_engine.MetaInsightsProvider._last_pull.clear()
    return f


def customers(client, n=3):
    recs = [{"email": f"p{i}@x.com", "signals": {"orders": 1, "marketing_consent": 1}} for i in range(n)]
    recs.append({"email": "noconsent@x.com", "signals": {"orders": 1, "marketing_consent": 0}})
    assert client.post("/ingest/records", json={"records": recs}).json()["errors"] == []
    return create_audience(client, "buyers", [{"field": "orders", "op": ">", "value": 0}])


# ---------------------------------------------------------------- client
def test_account_id_normalized():
    assert meta.normalize_account_id("123") == "act_123"
    assert meta.normalize_account_id("act_123") == "act_123"


def test_check_account(fake):
    info = fake.client().check()
    assert info["active"] and info["name"] == "Acme Ads"
    assert fake.requests[0]["query"]["access_token"] == "TOKEN"
    assert "/v25.0/act_123456" in fake.requests[0]["path"]


def test_upload_batches_of_10000_share_a_session(fake):
    rows = [(f"e{i}", "") for i in range(25_000)]
    out = fake.client().replace_users("AUD1", rows)
    posts = [r for r in fake.requests if r["path"].endswith("/usersreplace")]
    assert out["batches"] == 3 and len(posts) == 3
    sessions = [json.loads(p["body"]["session"]) for p in posts]
    assert [s["batch_seq"] for s in sessions] == [1, 2, 3]
    assert [s["last_batch_flag"] for s in sessions] == [False, False, True]
    assert len({s["session_id"] for s in sessions}) == 1
    assert all(s["estimated_num_total"] == 25_000 for s in sessions)
    sizes = [len(json.loads(p["body"]["payload"])["data"]) for p in posts]
    assert sizes == [10_000, 10_000, 5_000]
    assert json.loads(posts[0]["body"]["payload"])["schema"] == ["EMAIL_SHA256", "PHONE_SHA256"]


def test_empty_upload_refused(fake):
    with pytest.raises(meta.MetaError):
        fake.client().replace_users("AUD1", [])


@pytest.mark.parametrize("code,sub,needle", [
    (190, None, "expired"),
    (200, None, "ads_management"),
    (100, 1870090, "Custom Audience Terms"),
    (100, 1870050, "Business Manager"),
])
def test_errors_get_plain_english_hints(fake, code, sub, needle):
    fake.routes[("GET", "/act_123456")] = err(code, "raw meta message", sub)
    with pytest.raises(meta.MetaError) as e:
        fake.client().check()
    assert needle in str(e.value) and "raw meta message" in str(e.value)


def test_rate_limit_retries_with_backoff_then_succeeds(fake):
    calls = {"n": 0}

    def flaky(entry):
        calls["n"] += 1
        return err(17, "too many calls") if calls["n"] < 3 else {"name": "A", "account_status": 1, "currency": "USD"}

    fake.routes[("GET", "/act_123456")] = flaky
    sleeps = []
    assert fake.client(sleeps).check()["name"] == "A"
    assert calls["n"] == 3 and sleeps == [1, 2]


def test_rate_limit_gives_up(fake):
    fake.routes[("GET", "/act_123456")] = err(4, "app limit")
    with pytest.raises(meta.MetaError) as e:
        fake.client().check()
    assert "rate-limiting" in str(e.value)


def test_adsets_filtered_by_audience_with_paging(fake):
    page2 = "https://graph.facebook.com/v25.0/act_123456/adsets?after=XYZ"
    fake.routes[("GET", "/act_123456/adsets")] = lambda e: (
        {"data": [{"id": "S2", "name": "Other", "targeting": {"custom_audiences": [{"id": "AUD9"}]}},
                  {"id": "S3", "name": "Hit B", "targeting": {"custom_audiences": [{"id": "AUD1"}, {"id": "AUD9"}]}}]}
        if "after" in e["query"] else
        {"data": [{"id": "S1", "name": "Hit A", "targeting": {"custom_audiences": [{"id": "AUD1"}]}},
                  {"id": "S0", "name": "No targeting", "targeting": {}}],
         "paging": {"next": page2}}
    )
    found = fake.client().adsets_using_audience("AUD1")
    assert [a["id"] for a in found] == ["S1", "S3"]


def test_insights_parse_conversions_and_revenue(fake):
    fake.routes[("GET", "/S1/insights")] = {"data": [{
        "date_start": "2026-11-01", "impressions": "1000", "clicks": "40", "spend": "55.25",
        "actions": [{"action_type": "link_click", "value": "40"}, {"action_type": "purchase", "value": "3"}],
        "action_values": [{"action_type": "purchase", "value": "210.50"}],
    }]}
    rows = fake.client().adset_insights("S1", "2026-11-01", "2026-11-05")
    assert rows == [{"date": "2026-11-01", "impressions": 1000, "clicks": 40, "spend": 55.25, "conversions": 3, "revenue": 210.5}]


# ------------------------------------------------------------ sync flow
def test_sync_uploads_only_consented_hashed_people(client, fake):
    aud = customers(client)
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"}).json()
    assert r["status"] == "synced" and r["external_audience_id"] == "AUD1"
    assert r["excluded_no_consent"] == 1 and r["total_count"] == 3
    upload = next(x for x in fake.requests if x["path"].endswith("/usersreplace"))
    data = json.loads(upload["body"]["payload"])["data"]
    assert len(data) == 3 and all(len(e) == 64 for e, _ in data)
    assert "@" not in upload["body"]["payload"]


def test_resync_replaces_same_meta_audience(client, fake):
    aud = customers(client)
    first = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"}).json()
    second = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"}).json()
    assert first["external_audience_id"] == second["external_audience_id"] == "AUD1"
    assert sum(1 for x in fake.requests if x["path"].endswith("/customaudiences")) == 1


def test_meta_failure_recorded_not_raised(client, fake):
    fake.routes[("POST", "/customaudiences")] = err(100, "terms", 1870090)
    aud = customers(client)
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed" and "Custom Audience Terms" in body["external_status"]
    assert client.get(f"/audience/{aud['id']}/performance").json()["impressions"] == 0


def test_other_channels_stay_simulated_in_live_mode(client, fake):
    aud = customers(client)
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "email"}).json()
    assert r["status"] == "synced" and r["external_audience_id"] is None
    assert not any(x["path"].endswith("/customaudiences") for x in fake.requests)


def test_performance_pulls_real_insights_and_upserts(client, fake):
    aud = customers(client)
    fake.routes[("GET", "/act_123456/adsets")] = {"data": [
        {"id": "S1", "name": "A", "targeting": {"custom_audiences": [{"id": "AUD1"}]}},
        {"id": "S2", "name": "B", "targeting": {"custom_audiences": [{"id": "AUD1"}]}},
    ]}
    day = lambda imp, spend, n, rev: {"data": [{"date_start": "2026-11-02", "impressions": str(imp), "clicks": "10", "spend": str(spend),
                                                "actions": [{"action_type": "purchase", "value": str(n)}],
                                                "action_values": [{"action_type": "purchase", "value": str(rev)}]}]}
    fake.routes[("GET", "/S1/insights")] = day(1000, 20, 2, 100)
    fake.routes[("GET", "/S2/insights")] = day(500, 10, 1, 50)
    client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"})
    totals = client.get(f"/audience/{aud['id']}/performance").json()
    assert totals["impressions"] == 1500 and totals["spend"] == 30.0 and totals["conversions"] == 3 and totals["revenue"] == 150.0
    assert totals["roas"] == 5.0
    again = client.get(f"/audience/{aud['id']}/performance").json()  # re-pull overwrites, never doubles
    assert again["impressions"] == 1500


def test_no_adsets_yet_explains_next_step(client, fake):
    aud = customers(client)
    fake.routes[("GET", "/act_123456/adsets")] = {"data": []}
    client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"})
    client.get(f"/audience/{aud['id']}/performance")
    syncs = client.get(f"/audience/{aud['id']}/syncs").json()
    assert "No ad sets target" in syncs[-1]["external_status"]


def test_refresh_reads_matched_size(client, fake):
    aud = customers(client)
    sync = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"}).json()
    fake.routes[("GET", "/AUD1")] = {"name": "x", "approximate_count_lower_bound": 2400, "operation_status": {"description": "Normal"}}
    r = client.post(f"/syncs/{sync['id']}/refresh").json()
    assert r["matched_count"] == 2400 and "2,400" in r["external_status"]


def test_refresh_errors(client, fake):
    assert client.post("/syncs/999/refresh").status_code == 404
    aud = customers(client)
    client.post(f"/audience/{aud['id']}/sync", json={"channel": "email"})
    sid = client.get(f"/audience/{aud['id']}/syncs").json()[0]["id"]
    assert client.post(f"/syncs/{sid}/refresh").status_code == 400


def test_channel_status_endpoint(client, fake, monkeypatch):
    body = client.get("/channels/meta").json()
    assert body["connected"] and body["account"]["name"] == "Acme Ads"
    monkeypatch.setenv("META_MODE", "mock")
    assert client.get("/channels/meta").json()["connected"] is False


def test_meta_endpoints_need_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "k")
    assert client.get("/channels/meta").status_code == 401
    assert client.post("/syncs/1/refresh").status_code == 401


def test_legacy_metrics_mode_switch(monkeypatch):
    monkeypatch.delenv("META_MODE", raising=False)
    monkeypatch.setenv("METRICS_MODE", "meta")
    assert meta.is_live()
    monkeypatch.setenv("METRICS_MODE", "mock")
    assert not meta.is_live()


# -------------------------------------------------------------- doctor
def test_doctor_all_good(fake, monkeypatch):
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    res = doctor.run_checks(meta_write_test=True, client_factory=lambda: fake.client())
    by = {name: status for status, name, _ in res}
    assert by["Meta ad account"] == "PASS" and by["Meta write access"] == "PASS" and by["API key required"] == "PASS"
    assert any(r["method"] == "DELETE" for r in fake.requests)  # test audience cleaned up


def test_doctor_flags_problems(fake, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    fake.routes[("POST", "/customaudiences")] = err(100, "terms", 1870090)
    res = doctor.run_checks(meta_write_test=True, client_factory=lambda: fake.client())
    by = {name: (status, detail) for status, name, detail in res}
    assert by["API key required"][0] == "FAIL"
    assert by["Meta write access"][0] == "FAIL" and "Custom Audience Terms" in by["Meta write access"][1]
    assert doctor.main(["--meta-write-test"]) in (0, 1)


def test_doctor_without_credentials(monkeypatch):
    monkeypatch.setenv("META_MODE", "live")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    res = doctor.run_checks()
    assert any(s == "FAIL" and n == "Meta credentials" for s, n, _ in res)


def test_doctor_mock_mode_warns(monkeypatch):
    monkeypatch.setenv("META_MODE", "mock")
    res = doctor.run_checks()
    assert any(s == "WARN" and n == "Meta" for s, n, _ in res)


# ------------------------------------------------------------ migration
def test_migration_upgrades_old_database(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    eng = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with eng.begin() as c:  # the schema as shipped before normalization and Meta columns
        c.execute(text("CREATE TABLE persons (person_id VARCHAR PRIMARY KEY, created_at DATETIME)"))
        c.execute(text("CREATE TABLE identities (id INTEGER PRIMARY KEY AUTOINCREMENT, person_id VARCHAR, external_user_id VARCHAR, email VARCHAR, phone VARCHAR, account_type VARCHAR, match_confidence FLOAT, source VARCHAR, last_synced DATETIME)"))
        c.execute(text("CREATE TABLE channel_syncs (id INTEGER PRIMARY KEY AUTOINCREMENT, audience_id VARCHAR, channel VARCHAR, status VARCHAR, matched_count INTEGER, total_count INTEGER, synced_at DATETIME)"))
        c.execute(text("INSERT INTO persons VALUES ('P1', '2026-01-01')"))
        c.execute(text("INSERT INTO identities (person_id, email, phone) VALUES ('P1', 'Ada@Example.com', '+1 (206) 555-0100')"))
    added = migrate.ensure_columns(eng)
    assert {"identities.email_norm", "identities.phone_norm", "channel_syncs.external_audience_id", "channel_syncs.external_status"} <= set(added)
    with eng.connect() as c:
        row = c.execute(text("SELECT email_norm, phone_norm FROM identities")).one()
    assert tuple(row) == ("ada@example.com", "2065550100")
    assert migrate.ensure_columns(eng) == []  # idempotent
    assert any(i["name"].endswith("email_norm") for i in inspect(eng).get_indexes("identities"))
