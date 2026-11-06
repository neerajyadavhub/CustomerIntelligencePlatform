"""
Hashed audience exports for ad platforms.

Produces a CSV of SHA-256 hashed emails and phone numbers that you can upload
by hand to Meta (Custom Audiences, lookalike seeds, exclusions) or Google
(Customer Match). Hashing follows the common spec: emails trimmed and
lowercased, phones as digits with country code, no symbols, then SHA-256 hex.
Platform specs change, so check the current Meta/Google upload docs before a
production upload. This is a file export, not a live push to the platform.

Two purposes:
  target    people you want to reach (lookalike seeds, custom audiences).
            Only people with marketing consent are included.
  suppress  people you want to exclude from campaigns (e.g. existing customers
            in an acquisition campaign). Consent is not required, because
            excluding someone from ads is not marketing to them.
"""
import hashlib
import os
from typing import Iterable, List, Tuple

from sqlalchemy.orm import Session

from . import models

PURPOSES = ("target", "suppress")


def _country_code() -> str:
    return os.getenv("DEFAULT_PHONE_COUNTRY_CODE", "1")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_phone(phone_norm: str) -> str:
    digits = phone_norm
    if len(digits) == 10:  # normalized US-style number without country code
        digits = _country_code() + digits
    return sha256_hex(digits)


def hashed_rows(db: Session, person_ids: Iterable[str]) -> List[Tuple[str, str]]:
    """One (email_hash, phone_hash) row per distinct identity; blanks allowed."""
    ids = list(person_ids)
    seen = set()
    rows: List[Tuple[str, str]] = []
    if not ids:
        return rows
    identities = db.query(models.Identity).filter(models.Identity.person_id.in_(ids)).all()
    for ident in sorted(identities, key=lambda i: i.id):
        e = sha256_hex(ident.email_norm) if ident.email_norm else ""
        p = hash_phone(ident.phone_norm) if ident.phone_norm else ""
        if (e or p) and (e, p) not in seen:
            seen.add((e, p))
            rows.append((e, p))
    return rows


def to_csv(rows: List[Tuple[str, str]]) -> str:
    return "email,phone\n" + "".join(f"{e},{p}\n" for e, p in rows)
