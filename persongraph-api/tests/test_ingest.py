from app.normalize import normalize_email, normalize_phone


def test_normalization():
    assert normalize_email("  Jordyn@PersonalMail.com ") == "jordyn@personalmail.com"
    assert normalize_email("not-an-email") is None
    assert normalize_phone("+1 (206) 555-0111") == "2065550111"
    assert normalize_phone("206.555.0111") == "2065550111"
    assert normalize_phone("123") is None


def ingest(client, records, **params):
    return client.post("/ingest/records", params=params, json={"records": records, **params})


def test_new_person_created_and_resolvable(client):
    r = ingest(client, [{"email": "New.Person@Example.com", "signals": {"orders": 3}, "scores": {"propensity_to_convert": 0.9}}])
    assert r.status_code == 200
    assert r.json()["created"] == 1 and r.json()["errors"] == []
    look = client.get("/identity/lookup", params={"identifier": "new.person@example.com"})
    assert look.status_code == 200
    pid = look.json()["person_id"]
    prof = client.get(f"/person/{pid}").json()
    assert any(s["name"] == "orders" and s["value"] == 3 for s in prof["signals"])


def test_existing_person_matched_by_normalized_phone(client):
    # Seeded identity has phone "+1-206-555-0111"
    before = client.get("/identity/lookup", params={"identifier": "206-555-0111"}).json()["person_id"]
    r = ingest(client, [{"phone": "(206) 555 0111", "email": "extra@example.com", "signals": {"vip": True}}]).json()
    assert r["created"] == 0 and r["updated"] == 1
    after = client.get("/identity/lookup", params={"identifier": "extra@example.com"}).json()["person_id"]
    assert after == before


def test_records_sharing_an_identifier_merge(client):
    ingest(client, [{"email": "a@example.com", "signals": {"x": 1}}, {"email": "b@example.com", "signals": {"y": 2}}])
    a = client.get("/identity/lookup", params={"identifier": "a@example.com"}).json()["person_id"]
    b = client.get("/identity/lookup", params={"identifier": "b@example.com"}).json()["person_id"]
    assert a != b
    r = ingest(client, [{"email": "a@example.com", "phone": "555-123-4567"}, {"email": "b@example.com", "phone": "5551234567"}]).json()
    assert r["errors"] == []
    # first record attaches the phone to A; second record then bridges B and A
    a2 = client.get("/identity/lookup", params={"identifier": "a@example.com"}).json()["person_id"]
    b2 = client.get("/identity/lookup", params={"identifier": "b@example.com"}).json()["person_id"]
    assert a2 == b2 and a2 in (a, b)
    prof = client.get(f"/person/{a2}").json()
    names = {s["name"] for s in prof["signals"]}
    assert {"x", "y"} <= names  # signals from both people survive the merge
    assert r["merged"] == 1


def test_auto_merge_off_reports_conflict(client):
    ingest(client, [{"email": "c@example.com"}, {"email": "d@example.com"}])
    ingest(client, [{"email": "c@example.com", "phone": "555-987-6543"}])
    resp = client.post("/ingest/records", json={"auto_merge": False, "records": [{"email": "d@example.com", "phone": "555-987-6543"}]}).json()
    assert resp["merged"] == 0 and resp["updated"] == 0
    assert "conflict" in resp["errors"][0]["error"]


def test_bad_records_reported_not_fatal(client):
    r = ingest(client, [{}, {"email": "bad"}, {"email": "ok@example.com", "signals": {"n": "abc"}}, {"email": "fine@example.com"}]).json()
    assert r["received"] == 4 and r["created"] == 1
    assert [e["index"] for e in r["errors"]] == [0, 1, 2]


def test_signal_update_overwrites(client):
    ingest(client, [{"email": "u@example.com", "signals": {"orders": 1}}])
    ingest(client, [{"email": "u@example.com", "signals": {"orders": 5}}])
    pid = client.get("/identity/lookup", params={"identifier": "u@example.com"}).json()["person_id"]
    sigs = [s for s in client.get(f"/person/{pid}").json()["signals"] if s["name"] == "orders"]
    assert len(sigs) == 1 and sigs[0]["value"] == 5


def test_csv_ingest_and_audience_uses_it(client):
    aud = client.post("/audience", json={"name": "hi", "rule": [{"field": "propensity_to_convert", "op": ">", "value": 0.9}]}).json()
    before = client.get(f"/audience/{aud['id']}/preview").json()["matched_count"]
    csv_body = "email,phone,orders,score:propensity_to_convert\nz1@example.com,,4,0.95\nz2@example.com,555-222-3333,1,0.2\n"
    r = client.post("/ingest/csv", content=csv_body, headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["created"] == 2
    assert client.get(f"/audience/{aud['id']}/preview").json()["matched_count"] == before + 1


def test_csv_empty_body_400(client):
    assert client.post("/ingest/csv", content="email\n", headers={"content-type": "text/csv"}).status_code == 400


def test_api_key_auth(client, monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret-one,secret-two")
    assert client.get("/health").status_code == 200  # stays public
    assert client.get("/audience").status_code == 401
    assert client.get("/audience", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/audience", headers={"Authorization": "Bearer secret-two"}).status_code == 200
    assert client.get("/audience", headers={"X-API-Key": "secret-one"}).status_code == 200
    assert client.post("/ingest/records", json={"records": []}).status_code == 401
    assert client.options("/audience", headers={"Origin": "http://x", "Access-Control-Request-Method": "GET"}).status_code == 200


def test_open_when_no_keys(client, monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    assert client.get("/audience").status_code == 200
