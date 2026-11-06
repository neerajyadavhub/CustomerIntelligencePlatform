"""
Shared fixtures. Every test runs against a freshly seeded, isolated SQLite
database, so tests can mutate data freely and never touch loomid.db.
"""
import os
import tempfile

import pytest

# app.database reads DATABASE_URL at import time, so the isolated database
# has to be configured before any app module is imported.
#
# Tests run on a throwaway SQLite file by default. Set TEST_DATABASE_URL to run
# the same suite against another database (CI does this with Postgres). The
# suite wipes and reseeds that database, so never point it at real data.
_tmpdir = tempfile.mkdtemp(prefix="loomid-tests-")
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["SEED_ALLOW_RESET"] = "true"
os.environ["RESOLVER_MODE"] = "mock"
os.environ["METRICS_MODE"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(capsys):
    """Reset to the known demo dataset before every test."""
    seed.run()
    capsys.readouterr()  # swallow the seed script's progress print
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_audience(client, name, rule):
    response = client.post("/audience", json={"name": name, "rule": rule})
    assert response.status_code == 200, response.text
    return response.json()


def preview_ids(client, audience_id):
    response = client.get(f"/audience/{audience_id}/preview")
    assert response.status_code == 200, response.text
    return response.json()
