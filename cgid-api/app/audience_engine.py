"""
Audience rule engine. Rules are a flat list of conditions, ANDed together
(v1 scope — grouped AND/OR logic is a natural v2 extension).

Each condition's `field` can reference either a Signal name or a
ModelScore's model_name; we check both. `op` is one of > < >= <= = !=.
"""
import operator
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from . import models

OPS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "=": operator.eq,
    "!=": operator.ne,
}


def _latest_value(db: Session, person_id: str, field: str):
    sig = (
        db.query(models.Signal)
        .filter(models.Signal.person_id == person_id, models.Signal.name == field)
        .order_by(models.Signal.updated_at.desc())
        .first()
    )
    if sig:
        return sig.value
    score = (
        db.query(models.ModelScore)
        .filter(models.ModelScore.person_id == person_id, models.ModelScore.model_name == field)
        .order_by(models.ModelScore.scored_at.desc())
        .first()
    )
    if score:
        return score.score
    return None


def person_matches(db: Session, person_id: str, rule: List[Dict[str, Any]]) -> bool:
    for cond in rule:
        field, op, value = cond["field"], cond["op"], cond["value"]
        actual = _latest_value(db, person_id, field)
        if actual is None:
            return False
        if op not in OPS:
            raise ValueError(f"Unsupported operator '{op}'. Use one of {list(OPS)}.")
        if not OPS[op](actual, value):
            return False
    return True


def evaluate_audience(db: Session, rule: List[Dict[str, Any]]) -> List[str]:
    """Returns the list of person_ids matching the rule. Naive full-scan —
    fine for a demo/MVP; a real deployment would push this into the
    warehouse/feature store as volumes grow."""
    all_person_ids = [p.person_id for p in db.query(models.Person.person_id).all()]
    return [pid for pid in all_person_ids if person_matches(db, pid, rule)]
