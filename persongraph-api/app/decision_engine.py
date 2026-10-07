"""
Decision engine: turns a (person, requested action) pair into a logged,
explainable decision.

v1 is deliberately a small, readable rules table rather than a generic
rules-engine framework. Add new actions by adding a new function and
registering it in ACTION_RULES.
"""
import datetime as dt
from sqlalchemy.orm import Session
from . import models


def _get_signal(db: Session, person_id: str, name: str, default: float = 0.0) -> float:
    row = (
        db.query(models.Signal)
        .filter(models.Signal.person_id == person_id, models.Signal.name == name)
        .order_by(models.Signal.updated_at.desc())
        .first()
    )
    return row.value if row else default


def _get_score(db: Session, person_id: str, model_name: str):
    return (
        db.query(models.ModelScore)
        .filter(models.ModelScore.person_id == person_id, models.ModelScore.model_name == model_name)
        .order_by(models.ModelScore.scored_at.desc())
        .first()
    )


def _is_suppressed(db: Session, person_id: str) -> bool:
    return _get_signal(db, person_id, "suppressed", default=0.0) == 1.0


def evaluate_reactivation_offer(db: Session, person: models.Person) -> models.Decision:
    score_row = _get_score(db, person.person_id, "propensity_to_convert")
    propensity = score_row.score if score_row else 0.0
    consent = _get_signal(db, person.person_id, "marketing_consent", default=0.0) == 1.0
    suppressed = _is_suppressed(db, person.person_id)

    if suppressed:
        result, reason = "suppressed", "Person is on the suppression list; this overrides any model recommendation."
        conflict = propensity > 0.70  # model would have said yes - that is the conflict
    elif propensity > 0.70 and consent:
        result, reason = (
            "eligible",
            f"Propensity to convert scored {propensity:.2f} (above 0.70 threshold) and marketing consent is on file.",
        )
        conflict = False
    else:
        result, reason = "not_eligible", f"Propensity {propensity:.2f} or consent did not meet the bar for this action."
        conflict = False

    decision = models.Decision(
        person_id=person.person_id,
        action="reactivation_offer",
        result=result,
        reason=reason,
        rule_applied="reactivation_eligibility_v1",
        model_name=score_row.model_name if score_row else None,
        model_version=score_row.model_version if score_row else None,
        conflict_detected=conflict,
        created_at=dt.datetime.utcnow(),
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


ACTION_RULES = {
    "reactivation_offer": evaluate_reactivation_offer,
}


def evaluate(db: Session, person: models.Person, action: str) -> models.Decision:
    fn = ACTION_RULES.get(action)
    if not fn:
        raise ValueError(f"No rule registered for action '{action}'. Add one to decision_engine.ACTION_RULES.")
    return fn(db, person)
