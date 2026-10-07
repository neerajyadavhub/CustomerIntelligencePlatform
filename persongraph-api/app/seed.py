"""
Seeds the database with demo data so you can hit every endpoint
immediately after a fresh install. Run with: python -m app.seed
"""
import datetime as dt
from .database import Base, engine, SessionLocal
from . import models


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    for model in [models.ChannelSync, models.Audience, models.Decision, models.ModelScore, models.Signal, models.Identity, models.Person]:
        db.query(model).delete()
    db.commit()

    people = [
        {
            "person_id": "PER-4471",
            "identities": [
                {"external_user_id": "U-88213", "email": "jordyn@personalmail.com", "account_type": "personal", "match_confidence": 0.94},
                {"external_user_id": "U-90441", "email": "jordyn@resellerco.com", "account_type": "business", "match_confidence": 0.94},
                {"external_user_id": None, "email": None, "phone": "+1-206-555-0111", "account_type": "anonymous", "match_confidence": 0.71},
            ],
            "signals": {"days_since_last_activity": 42.0, "channel_fatigue": 0.5, "marketing_consent": 1.0, "suppressed": 0.0, "lifetime_spend": 4920.0},
            "scores": {"propensity_to_convert": 0.82, "churn_risk": 0.41},
        },
        {
            "person_id": "PER-2290",
            "identities": [
                {"external_user_id": "U-77120", "email": "sam.r@mail.com", "account_type": "personal", "match_confidence": 0.98},
            ],
            "signals": {"days_since_last_activity": 10.0, "channel_fatigue": 0.8, "marketing_consent": 1.0, "suppressed": 1.0, "lifetime_spend": 1210.0},
            "scores": {"propensity_to_convert": 0.71, "churn_risk": 0.66},
        },
        {
            "person_id": "PER-8813",
            "identities": [
                {"external_user_id": "U-91004", "email": "priya.k@mail.com", "account_type": "personal", "match_confidence": 0.99},
            ],
            "signals": {"days_since_last_activity": 3.0, "channel_fatigue": 0.2, "marketing_consent": 1.0, "suppressed": 0.0, "lifetime_spend": 9120.0},
            "scores": {"propensity_to_convert": 0.91, "churn_risk": 0.08},
        },
        {
            "person_id": "PER-5541",
            "identities": [
                {"external_user_id": "U-40881", "email": "dormant.user@mail.com", "account_type": "personal", "match_confidence": 0.95},
            ],
            "signals": {"days_since_last_activity": 92.0, "channel_fatigue": 0.1, "marketing_consent": 0.0, "suppressed": 0.0, "lifetime_spend": 310.0},
            "scores": {"propensity_to_convert": 0.19, "churn_risk": 0.85},
        },
    ]

    for p in people:
        person = models.Person(person_id=p["person_id"])
        db.add(person)
        db.flush()

        for ident in p["identities"]:
            db.add(models.Identity(
                person_id=person.person_id,
                external_user_id=ident.get("external_user_id"),
                email=ident.get("email"),
                phone=ident.get("phone"),
                account_type=ident["account_type"],
                match_confidence=ident["match_confidence"],
                source="segment",
                last_synced=dt.datetime.utcnow(),
            ))

        for name, value in p["signals"].items():
            db.add(models.Signal(person_id=person.person_id, name=name, value=value))

        for model_name, score in p["scores"].items():
            db.add(models.ModelScore(person_id=person.person_id, model_name=model_name, model_version="v1", score=score))

    db.commit()
    db.close()
    print("Seed complete: 4 people, with identities, signals, and model scores.")


if __name__ == "__main__":
    run()
