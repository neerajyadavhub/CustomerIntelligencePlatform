from app.main import cors_origins_from_env


def test_health_is_json(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"service": "Customer Graph ID API", "status": "ok"}


def test_openapi_exposes_core_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for route in [
        "/identity/lookup",
        "/person/{person_id}",
        "/decision/evaluate",
        "/audience",
        "/audience/{audience_id}/preview",
        "/audience/{audience_id}/sync",
        "/audience/{audience_id}/performance",
    ]:
        assert route in paths, f"missing route {route}"


def test_cors_preflight_allows_browser_clients(client):
    response = client.options(
        "/identity/lookup",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers


def test_cors_defaults_to_wildcard_for_demo(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins_from_env() == ["*"]


def test_cors_origins_can_be_locked_down_by_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://admin.example.com ,")
    assert cors_origins_from_env() == ["https://app.example.com", "https://admin.example.com"]
