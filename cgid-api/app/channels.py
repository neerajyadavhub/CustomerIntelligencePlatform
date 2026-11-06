"""
Real channel activation. Today: Meta Custom Audiences.

push_to_meta() uploads an audience's people (hashed emails/phones only) to a
Meta Custom Audience. The first sync creates the audience; later syncs of the
same Customer Graph ID audience replace its members, so the Meta audience
stays current and keeps its id (and any ad sets that target it).
"""
from typing import List

from sqlalchemy.orm import Session

from . import exports, models
from .meta import MetaClient

CHANNEL = "meta_ads"


def previous_meta_audience_id(db: Session, audience_id: str):
    prior = (
        db.query(models.ChannelSync)
        .filter(
            models.ChannelSync.audience_id == audience_id,
            models.ChannelSync.channel == CHANNEL,
            models.ChannelSync.status == "synced",
            models.ChannelSync.external_audience_id.isnot(None),
        )
        .order_by(models.ChannelSync.id.desc())
        .first()
    )
    return prior.external_audience_id if prior else None


def push_to_meta(db: Session, client: MetaClient, audience: models.Audience, person_ids: List[str]) -> dict:
    rows = exports.hashed_rows(db, person_ids)
    external_id = previous_meta_audience_id(db, audience.id)
    created = external_id is None
    if created:
        external_id = client.create_audience(
            f"CGID - {audience.name}",
            f"Managed by Customer Graph ID (audience {audience.id}). Members are replaced on each sync.",
        )
    result = client.replace_users(external_id, rows)
    accepted = result["received"] - result["invalid"]
    return {
        "external_audience_id": external_id,
        "created": created,
        "uploaded": accepted,
        "invalid": result["invalid"],
        "status": (
            f"Uploaded {accepted} hashed records to Meta audience {external_id}. "
            "Meta processes uploads for up to 24 hours; refresh to see the matched size. "
            f"To see results here, run an ad set in Ads Manager that targets this audience."
        ),
    }
