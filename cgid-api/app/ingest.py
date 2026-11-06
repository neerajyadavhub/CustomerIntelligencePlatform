"""
Bring-your-own-data ingestion with deterministic identity resolution.

Each record carries identifiers (external_user_id, email, phone) plus optional
signals and model scores. Records are matched to existing people on normalized
identifiers:

  - no match            -> new Person
  - one person matches  -> identifiers/signals/scores are added or updated
  - several match       -> the people are merged into the oldest one
                           (unless auto_merge=False, which reports a conflict)

Matching is exact on normalized identifiers; there is no fuzzy or
probabilistic matching. Note that a shared identifier (e.g. a household phone)
will link people - use auto_merge=False if your data has those.
"""
import csv
import io
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .clock import utcnow
from .normalize import normalize_email, normalize_phone

KNOWN_COLUMNS = {"external_user_id", "email", "phone", "account_type", "source"}
SCORE_PREFIX = "score:"


def _find_people(db: Session, external_user_id, email_n, phone_n) -> list:
    ids = set()
    q = db.query(models.Identity)
    if external_user_id:
        ids.update(i.person_id for i in q.filter(models.Identity.external_user_id == external_user_id))
    if email_n:
        ids.update(i.person_id for i in q.filter(models.Identity.email_norm == email_n))
    if phone_n:
        ids.update(i.person_id for i in q.filter(models.Identity.phone_norm == phone_n))
    if not ids:
        return []
    people = db.query(models.Person).filter(models.Person.person_id.in_(ids)).all()
    return sorted(people, key=lambda p: (p.created_at, p.person_id))


def _merge(db: Session, survivor: models.Person, loser: models.Person) -> None:
    for ident in list(loser.identities):
        ident.person = survivor
    for dec in list(loser.decisions):
        dec.person = survivor
    have_signals = {s.name: s for s in survivor.signals}
    for sig in list(loser.signals):
        mine = have_signals.get(sig.name)
        if mine is None:
            sig.person = survivor
        elif sig.updated_at > mine.updated_at:
            mine.value, mine.updated_at = sig.value, sig.updated_at
    have_scores = {s.model_name: s for s in survivor.scores}
    for sc in list(loser.scores):
        mine = have_scores.get(sc.model_name)
        if mine is None:
            sc.person = survivor
        elif sc.scored_at > mine.scored_at:
            mine.score, mine.scored_at = sc.score, sc.scored_at
    db.flush()
    db.expire(loser)
    db.delete(loser)
    db.flush()


def _conflicts(existing, incoming) -> bool:
    return bool(existing and incoming and existing != incoming)


def _upsert_identity(person: models.Person, rec: dict, email_n, phone_n) -> None:
    """Update the account this record describes, or add it as a new linked
    account. An existing account is only reused when none of its identifiers
    conflict with the record's: a record with a new email but a shared phone
    is a different account of the same person, so its email must be kept."""
    ext = rec.get("external_user_id")
    for ident in person.identities:
        matches = (
            (ext and ident.external_user_id == ext)
            or (email_n and ident.email_norm == email_n)
            or (phone_n and ident.phone_norm == phone_n)
        )
        conflict = (
            _conflicts(ident.external_user_id, ext)
            or _conflicts(ident.email_norm, email_n)
            or _conflicts(ident.phone_norm, phone_n)
        )
        if matches and not conflict:
            ident.external_user_id = ident.external_user_id or ext
            ident.email = ident.email or rec.get("email")
            ident.phone = ident.phone or rec.get("phone")
            ident.last_synced = utcnow()
            return
    person.identities.append(
        models.Identity(
            external_user_id=ext,
            email=rec.get("email"),
            phone=rec.get("phone"),
            account_type=rec.get("account_type") or "unknown",
            match_confidence=1.0,
            source=rec.get("source") or "ingest",
        )
    )


def _num(value, label):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be numeric, got {value!r}")


def _apply_signals_scores(person: models.Person, rec: dict) -> None:
    now = utcnow()
    for name, value in (rec.get("signals") or {}).items():
        val = _num(value, f"signal '{name}'")
        existing = next((s for s in person.signals if s.name == name), None)
        if existing:
            existing.value, existing.updated_at = val, now
        else:
            person.signals.append(models.Signal(name=name, value=val, updated_at=now))
    for model_name, value in (rec.get("scores") or {}).items():
        val = _num(value, f"score '{model_name}'")
        existing = next((s for s in person.scores if s.model_name == model_name), None)
        if existing:
            existing.score, existing.scored_at = val, now
        else:
            person.scores.append(models.ModelScore(model_name=model_name, score=val, scored_at=now))


def ingest_records(db: Session, records: list, auto_merge: bool = True) -> dict:
    result = {"received": len(records), "created": 0, "updated": 0, "merged": 0, "errors": []}
    for index, rec in enumerate(records):
        try:
            ext = (rec.get("external_user_id") or "").strip() or None
            email_n = normalize_email(rec.get("email"))
            phone_n = normalize_phone(rec.get("phone"))
            if rec.get("email") and not email_n:
                raise ValueError(f"invalid email {rec.get('email')!r}")
            if rec.get("phone") and not phone_n:
                raise ValueError(f"invalid phone {rec.get('phone')!r}")
            if not (ext or email_n or phone_n):
                raise ValueError("record needs at least one of external_user_id, email, phone")
            rec = {**rec, "external_user_id": ext}

            people = _find_people(db, ext, email_n, phone_n)
            if len(people) > 1 and not auto_merge:
                raise ValueError(
                    "conflict: identifiers match " + ", ".join(p.person_id for p in people) + " (auto_merge is off)"
                )
            created = merged = 0
            with db.begin_nested():
                if not people:
                    person = models.Person()
                    db.add(person)
                    db.flush()
                    created = 1
                else:
                    person = people[0]
                    for other in people[1:]:
                        _merge(db, person, other)
                        merged += 1
                _upsert_identity(person, rec, email_n, phone_n)
                _apply_signals_scores(person, rec)
                db.flush()
            # count only after the record fully succeeded
            result["created"] += created
            result["merged"] += merged
            result["updated"] += 0 if created else 1
        except ValueError as exc:
            result["errors"].append({"index": index, "error": str(exc)})
    db.commit()
    return result


def parse_csv(text: str) -> list:
    """Columns: external_user_id, email, phone, account_type, source, plus any
    other column as a numeric signal. Columns named score:<model> become model
    scores. Empty cells are ignored."""
    records = []
    for row in csv.DictReader(io.StringIO(text)):
        rec: dict = {"signals": {}, "scores": {}}
        for key, value in row.items():
            if key is None or value is None or not value.strip():
                continue
            key, value = key.strip(), value.strip()
            if key in KNOWN_COLUMNS:
                rec[key] = value
            elif key.startswith(SCORE_PREFIX):
                rec["scores"][key[len(SCORE_PREFIX):]] = value
            else:
                rec["signals"][key] = value
        records.append(rec)
    return records
