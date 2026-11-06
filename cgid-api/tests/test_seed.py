from types import SimpleNamespace

import pytest

from app import models, seed


def test_seed_is_idempotent(db):
    seed.run()
    seed.run()
    assert db.query(models.Person).count() == 4
    assert db.query(models.Audience).count() == 1
    assert db.query(models.ChannelSync).count() == 2


def test_seed_refuses_to_wipe_a_non_sqlite_database(monkeypatch, db):
    monkeypatch.delenv("SEED_ALLOW_RESET", raising=False)
    monkeypatch.setattr(seed, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    with pytest.raises(SystemExit) as exc:
        seed.run()

    assert "SEED_ALLOW_RESET" in str(exc.value)
    assert db.query(models.Person).count() == 4  # nothing was deleted
