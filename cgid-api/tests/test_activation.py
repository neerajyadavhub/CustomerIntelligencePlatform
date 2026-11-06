import csv
import hashlib
import io

from tests.conftest import create_audience


def sha(v):
    return hashlib.sha256(v.encode()).hexdigest()


def load(client, records):
    r = client.post("/ingest/records", json={"records": records})
    assert r.status_code == 200 and r.json()["errors"] == []


def people(client):
    """Three customers: two consented, one not, one with no consent info."""
    load(client, [
        {"email": "yes1@x.com", "phone": "(206) 555-0001", "signals": {"orders": 3, "marketing_consent": 1}},
        {"email": "yes2@x.com", "signals": {"orders": 2, "marketing_consent": 1}},
        {"email": "no@x.com", "signals": {"orders": 5, "marketing_consent": 0}},
        {"email": "unknown@x.com", "signals": {"orders": 4}},
    ])
    return create_audience(client, "customers", [{"field": "orders", "op": ">", "value": 0}])


def parse(resp):
    return list(csv.DictReader(io.StringIO(resp.text)))


# ---------------------------------------------------------------- consent
def test_sync_excludes_people_without_consent(client):
    aud = people(client)
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads"}).json()
    assert r["total_count"] == 2 and r["excluded_no_consent"] == 2
    assert r["status"] == "synced"


def test_sync_can_skip_consent_when_asked(client):
    aud = people(client)
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "meta_ads", "enforce_consent": False}).json()
    assert r["total_count"] == 4 and r["excluded_no_consent"] is None


def test_sync_with_nobody_consented_fails(client):
    load(client, [{"email": "n@x.com", "signals": {"orders": 1, "marketing_consent": 0}}])
    aud = create_audience(client, "n", [{"field": "orders", "op": ">", "value": 0}, {"field": "marketing_consent", "op": "=", "value": 0}])
    r = client.post(f"/audience/{aud['id']}/sync", json={"channel": "email"}).json()
    assert r["status"] == "failed" and r["total_count"] == 0


# ----------------------------------------------------------------- export
def test_export_target_is_hashed_and_consent_filtered(client):
    aud = people(client)
    r = client.get(f"/audience/{aud['id']}/export", params={"purpose": "target"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["x-excluded-no-consent"] == "2" and r.headers["x-people"] == "2"
    rows = parse(r)
    emails = {row["email"] for row in rows}
    assert emails == {sha("yes1@x.com"), sha("yes2@x.com")}
    assert "@" not in r.text                              # nothing in plain text
    phones = {row["phone"] for row in rows if row["phone"]}
    assert phones == {sha("12065550001")}                 # country code added, symbols stripped


def test_export_suppress_includes_everyone(client):
    aud = people(client)
    r = client.get(f"/audience/{aud['id']}/export", params={"purpose": "suppress"})
    assert r.headers["x-excluded-no-consent"] == "0" and r.headers["x-people"] == "4"
    assert {row["email"] for row in parse(r)} >= {sha("no@x.com"), sha("unknown@x.com")}


def test_export_includes_all_linked_identities(client):
    load(client, [{"email": "a@x.com", "phone": "555-111-2222", "signals": {"marketing_consent": 1, "orders": 1}},
                  {"email": "a.work@x.com", "phone": "5551112222"}])
    aud = create_audience(client, "a", [{"field": "orders", "op": ">", "value": 0}])
    emails = {row["email"] for row in parse(client.get(f"/audience/{aud['id']}/export"))}
    assert {sha("a@x.com"), sha("a.work@x.com")} <= emails


def test_export_errors(client):
    aud = people(client)
    assert client.get(f"/audience/{aud['id']}/export", params={"purpose": "x"}).status_code == 400
    assert client.get("/audience/AUD-NOPE/export").status_code == 404


def test_export_requires_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "k")
    assert client.get("/audience/AUD-1/export").status_code == 401


# --------------------------------------------------------------- duplicates
def test_duplicate_report(client):
    base = client.get("/identity/duplicates").json()
    load(client, [
        {"email": "d1@x.com", "phone": "555-333-4444"},
        {"email": "d2@x.com", "phone": "(555) 333 4444"},
        {"email": "d3@x.com", "phone": "5553334444"},
        {"email": "solo@x.com"},
    ])
    rep = client.get("/identity/duplicates").json()
    assert rep["accounts"] - base["accounts"] == 4   # d1, d2, d3 and solo are all kept as accounts
    assert rep["people"] - base["people"] == 2       # trio collapses to one person, plus solo
    assert rep["duplicate_accounts"] - base["duplicate_accounts"] == 2   # 4 accounts, 2 people
    top = rep["largest_groups"][0]
    assert top["accounts"] >= 2
    assert 0 < rep["duplicate_rate"] < 1


# ------------------------------------------------------------------ winback
def test_winback_due_flags_overdue_but_not_lost(client):
    load(client, [
        # gap = (400-100)/3 = 100 days; 130 days since last order -> 30 past, not lost
        {"email": "due@x.com", "signals": {"orders": 4, "total_spend": 400, "days_since_last_order": 130, "tenure_days": 430}},
        # 10 days since last order, usual gap 100 -> not due yet
        {"email": "fresh@x.com", "signals": {"orders": 4, "total_spend": 400, "days_since_last_order": 10, "tenure_days": 310}},
        # far past 3x gap -> lost, not a win-back
        {"email": "lost@x.com", "signals": {"orders": 4, "total_spend": 400, "days_since_last_order": 900, "tenure_days": 1200}},
        # one order: gap unknowable -> skipped
        {"email": "once@x.com", "signals": {"orders": 1, "total_spend": 40, "days_since_last_order": 200, "tenure_days": 200}},
    ])
    out = client.post("/models/run", json={"models": ["winback"]}).json()
    assert out["ran"]["winback"] == 3

    def sc(e):
        pid = client.get("/identity/lookup", params={"identifier": e}).json()["person_id"]
        return {s["model_name"]: s["score"] for s in client.get(f"/person/{pid}").json()["scores"]}

    assert sc("due@x.com")["winback_due"] == 1.0 and sc("due@x.com")["days_past_expected_gap"] == 30
    assert sc("fresh@x.com")["winback_due"] == 0.0 and sc("fresh@x.com")["days_past_expected_gap"] < 0
    assert sc("lost@x.com")["winback_due"] == 0.0
    assert "winback_due" not in sc("once@x.com")
    aud = create_audience(client, "winback", [{"field": "winback_due", "op": "=", "value": 1}])
    pid = client.get("/identity/lookup", params={"identifier": "due@x.com"}).json()["person_id"]
    assert client.get(f"/audience/{aud['id']}/preview").json()["sample_person_ids"] == [pid]
