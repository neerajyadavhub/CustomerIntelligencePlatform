"""
Identity resolution adapter.

This is the one module you touch to go from "mock data" to "real Segment
integration." Everything else in the app (API routes, decision logic,
audiences) only ever talks to the IdentityResolver interface below — it
never calls Segment directly. That means swapping MockResolver for
SegmentResolver is a one-line change in main.py.

--------------------------------------------------------------------------
HOW THE REAL SYNC JOB WORKS (what SegmentResolver.sync() should do):

  1. Pull updated Profiles from Segment's Profile API or your warehouse
     mirror of it (Segment -> BigQuery/Snowflake is the common pattern).
     Docs: https://segment.com/docs/unify/profile-api/

  2. For each Profile, get its linked external_ids (user_id, email,
     phone, anonymous_id, etc).

  3. Match those external_ids against your own `identities` table by
     email and/or your own user_id.

  4. Validate the matched user ids actually exist in your product's
     user database (do not trust Segment's merge blindly).

  5. Upsert a Person row (or reuse an existing one) and write/update
     Identity rows with the resulting match_confidence and
     last_synced timestamp.

  6. Run this on a schedule (cron) or as a streaming consumer (Kafka)
     depending on how fresh you need the data.
--------------------------------------------------------------------------
"""
import os
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from . import models


class IdentityResolver(ABC):
    @abstractmethod
    def resolve(self, db: Session, identifier: str):
        """Given any identifier (email, phone, external_user_id), return
        the Person it belongs to, or None if unresolved."""
        raise NotImplementedError

    @abstractmethod
    def sync(self, db: Session) -> int:
        """Pull the latest merges from the identity source and upsert
        Person/Identity rows. Returns the number of people updated."""
        raise NotImplementedError


class MockResolver(IdentityResolver):
    """Demo/dev resolver. Looks up identities already seeded in the local
    database — see seed.py for the fixture data. Use this until you have
    real Segment credentials."""

    def resolve(self, db: Session, identifier: str):
        identity = (
            db.query(models.Identity)
            .filter(
                (models.Identity.email == identifier)
                | (models.Identity.phone == identifier)
                | (models.Identity.external_user_id == identifier)
            )
            .first()
        )
        if not identity:
            return None
        return db.query(models.Person).filter(models.Person.person_id == identity.person_id).first()

    def sync(self, db: Session) -> int:
        return 0


class SegmentResolver(IdentityResolver):
    """Real resolver. Fill in SEGMENT_API_KEY and SEGMENT_SPACE_ID as env
    vars, then implement the two TODOs below against Segment's Profile
    API (or your warehouse mirror). Swap MockResolver() for
    SegmentResolver() in main.py once this is wired up."""

    def __init__(self):
        self.api_key = os.getenv("SEGMENT_API_KEY")
        self.space_id = os.getenv("SEGMENT_SPACE_ID")

    def resolve(self, db: Session, identifier: str):
        # TODO: call Segment's Profile API with this identifier, or (recommended)
        # look it up locally if sync() below already keeps `identities` current.
        raise NotImplementedError("Wire this up to Segment's Profile API or your warehouse mirror.")

    def sync(self, db: Session) -> int:
        # TODO: 1. pull updated profiles since last run
        #       2. match -> validate -> upsert Person/Identity rows
        #       3. return count updated
        raise NotImplementedError("Implement against Segment's Profile API. See module docstring.")


def get_resolver() -> IdentityResolver:
    mode = os.getenv("RESOLVER_MODE", "mock")
    if mode == "segment":
        return SegmentResolver()
    return MockResolver()
