"""
Built-in customer models.

These are transparent, formula-based models, not trained machine learning.
They run on the numeric signals you ingest and write ordinary model scores,
so audiences and decisions can use them straight away
(for example: churn_risk > 0.7 AND clv_12m > 500).

Input signals (ingest them as CSV columns or via /ingest/records):
  orders                 number of orders to date
  total_spend            total revenue to date
  days_since_last_order  recency
  tenure_days            days since first order (optional, improves timing)
  promo_orders           orders placed with a discount (optional)

Models and the scores they write:
  rfm            rfm_recency, rfm_frequency, rfm_monetary   (1-5, 5 = best;
                 ranked against everyone scored in the same run)
  churn_risk     churn_risk                                  (0-1)
  clv            clv_12m                                     (expected revenue, next 12 months)
  discount       discount_sensitivity                        (0-1)
  winback        days_past_expected_gap, winback_due         (needs 2+ orders and tenure_days)

Formulas are deliberately simple so you can explain every number:
  expected_gap  = max((tenure_days - days_since_last_order) / (orders - 1), 7)
                  i.e. the average gap between orders; 90 days when it can't be
                  measured (one order, or no tenure_days)
  churn_risk    = min(1, days_since_last_order / (3 * expected_gap))
  clv_12m       = avg_order_value * (365 / expected_gap) * (1 - churn_risk)
  discount_sens = promo_orders / orders
  days_past_expected_gap = days_since_last_order - expected_gap   (negative = not yet due)
  winback_due   = 1 when days_past_expected_gap >= 0 and churn_risk < 1, else 0
"""
from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import models
from .clock import utcnow

MODEL_VERSION = "formula-v1"

CATALOG = {
    "rfm": {
        "description": "Recency / frequency / monetary scores from 1 (worst) to 5 (best), ranked across everyone scored in the run.",
        "requires": ["days_since_last_order", "orders", "total_spend"],
        "writes": ["rfm_recency", "rfm_frequency", "rfm_monetary"],
    },
    "churn_risk": {
        "description": "How overdue a customer is relative to their usual purchase gap (0-1).",
        "requires": ["days_since_last_order", "orders"],
        "optional": ["tenure_days"],
        "writes": ["churn_risk"],
    },
    "clv": {
        "description": "Expected revenue over the next 12 months: average order value x expected orders x (1 - churn risk).",
        "requires": ["days_since_last_order", "orders", "total_spend"],
        "optional": ["tenure_days"],
        "writes": ["clv_12m"],
    },
    "winback": {
        "description": "Win-back timing: days past the customer's usual gap between orders, and a flag for customers who are overdue but not yet lost.",
        "requires": ["days_since_last_order", "orders", "tenure_days"],
        "min_orders": 2,
        "writes": ["days_past_expected_gap", "winback_due"],
    },
    "discount": {
        "description": "Share of orders placed on a promotion (0-1).",
        "requires": ["orders", "promo_orders"],
        "writes": ["discount_sensitivity"],
    },
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def expected_gap(sig: dict) -> float:
    """Average days between orders; 90 when it can't be measured."""
    tenure = sig.get("tenure_days")
    if tenure and sig["orders"] > 1:
        span = tenure - sig["days_since_last_order"]
        return max(span / (sig["orders"] - 1), 7.0)
    return 90.0


def _churn_raw(sig: dict) -> float:
    return _clamp01(sig["days_since_last_order"] / (3 * expected_gap(sig)))


def churn_risk(sig: dict) -> float:
    return round(_churn_raw(sig), 4)


def clv_12m(sig: dict) -> float:
    aov = sig["total_spend"] / sig["orders"]
    return round(aov * (365 / expected_gap(sig)) * (1 - _churn_raw(sig)), 2)


def discount_sensitivity(sig: dict) -> float:
    return round(_clamp01(sig["promo_orders"] / sig["orders"]), 4)


def _quintiles(values: Dict[str, float], higher_is_better: bool) -> Dict[str, int]:
    """Percentile-rank each value within the population, mapped to 1-5."""
    vals = list(values.values())
    n = len(vals)
    out = {}
    for key, v in values.items():
        below = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        pct = (below + 0.5 * equal) / n
        if not higher_is_better:
            pct = 1 - pct
        out[key] = min(5, 1 + int(pct * 5))
    return out


def segment_label(r: float, f: float) -> str:
    if r >= 4 and f >= 4:
        return "champions"
    if f >= 3 and r >= 3:
        return "loyal"
    if r >= 4 and f <= 2:
        return "new"
    if r <= 2 and f >= 3:
        return "at_risk"
    if r <= 2 and f <= 2:
        return "lapsed"
    return "needs_attention"


def _has(sig: dict, names: List[str]) -> bool:
    return all(n in sig for n in names) and ("orders" not in names or sig["orders"] > 0)


def _upsert(person: models.Person, name: str, value: float, now) -> None:
    existing = next((s for s in person.scores if s.model_name == name), None)
    if existing:
        existing.score, existing.model_version, existing.scored_at = value, MODEL_VERSION, now
    else:
        person.scores.append(models.ModelScore(model_name=name, model_version=MODEL_VERSION, score=value, scored_at=now))


def run_models(db: Session, which: Optional[List[str]] = None) -> dict:
    which = which or list(CATALOG)
    unknown = [m for m in which if m not in CATALOG]
    if unknown:
        raise ValueError(f"Unknown model(s): {', '.join(unknown)}. Available: {', '.join(CATALOG)}")

    people = db.query(models.Person).all()
    sigs = {p.person_id: {s.name: s.value for s in p.signals} for p in people}
    by_id = {p.person_id: p for p in people}
    now = utcnow()
    ran = {m: 0 for m in which}
    skipped = {m: 0 for m in which}
    segments: Counter = Counter()
    scored_ids = set()

    if "rfm" in which:
        eligible = {pid: s for pid, s in sigs.items() if _has(s, CATALOG["rfm"]["requires"])}
        skipped["rfm"] = len(people) - len(eligible)
        if eligible:
            r = _quintiles({k: s["days_since_last_order"] for k, s in eligible.items()}, higher_is_better=False)
            f = _quintiles({k: s["orders"] for k, s in eligible.items()}, higher_is_better=True)
            m = _quintiles({k: s["total_spend"] for k, s in eligible.items()}, higher_is_better=True)
            for pid in eligible:
                _upsert(by_id[pid], "rfm_recency", float(r[pid]), now)
                _upsert(by_id[pid], "rfm_frequency", float(f[pid]), now)
                _upsert(by_id[pid], "rfm_monetary", float(m[pid]), now)
                segments[segment_label(r[pid], f[pid])] += 1
                scored_ids.add(pid)
            ran["rfm"] = len(eligible)

    simple = {
        "churn_risk": ("churn_risk", churn_risk),
        "clv": ("clv_12m", clv_12m),
        "discount": ("discount_sensitivity", discount_sensitivity),
    }
    for model, (score_name, fn) in simple.items():
        if model not in which:
            continue
        for pid, s in sigs.items():
            if _has(s, CATALOG[model]["requires"]):
                _upsert(by_id[pid], score_name, fn(s), now)
                ran[model] += 1
                scored_ids.add(pid)
            else:
                skipped[model] += 1

    if "winback" in which:
        spec = CATALOG["winback"]
        for pid, sg in sigs.items():
            if _has(sg, spec["requires"]) and sg["orders"] >= spec["min_orders"]:
                past = round(sg["days_since_last_order"] - expected_gap(sg), 2)
                _upsert(by_id[pid], "days_past_expected_gap", past, now)
                _upsert(by_id[pid], "winback_due", 1.0 if (past >= 0 and _churn_raw(sg) < 1) else 0.0, now)
                ran["winback"] += 1
                scored_ids.add(pid)
            else:
                skipped["winback"] += 1

    db.commit()
    return {
        "people_scored": len(scored_ids),
        "ran": ran,
        "skipped": skipped,
        "rfm_segments": dict(segments),
        "model_version": MODEL_VERSION,
    }
