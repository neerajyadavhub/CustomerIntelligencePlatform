"""
Tiny automatic schema upgrade, so a database created by an older version keeps
working: any column the code defines but the table lacks is added (nullable
columns only), missing indexes are created, and the normalized email/phone
columns are backfilled. It never drops or rewrites anything. For heavier
changes, adopt Alembic.
"""
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from . import models
from .database import Base
from .normalize import normalize_email, normalize_phone


def ensure_columns(engine) -> list:
    insp = inspect(engine)
    added = []
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing or not col.nullable:
                continue
            ddl = col.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
            added.append(f"{table.name}.{col.name}")
        for idx in table.indexes:
            idx.create(bind=engine, checkfirst=True)
    if any(a.startswith("identities.") for a in added):
        with Session(engine) as db:
            for ident in db.query(models.Identity).all():
                ident.email_norm = normalize_email(ident.email)
                ident.phone_norm = normalize_phone(ident.phone)
            db.commit()
    return added
