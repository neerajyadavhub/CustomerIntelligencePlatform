import pytest

from app import decision_engine, models


def evaluate(client, person_id, action="reactivation_offer"):
    return client.post("/decision/evaluate", json={"person_id": person_id, "action": action})


@pytest.mark.parametrize(
    "person_id, result, conflict",
    [
        ("PER-4471", "eligible", False),       # high propensity, consent, not suppressed
        ("PER-8813", "eligible", False),
        ("PER-2290", "suppressed", True),      # model says yes (0.71) but suppressed
        ("PER-5541", "not_eligible", False),   # low propensity, no consent
    ],
)
def test_reactivation_outcomes(client, person_id, result, conflict):
    response = evaluate(client, person_id)
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == result
    assert body["conflict_detected"] is conflict
    assert body["rule_applied"] == "reactivation_eligibility_v1"


def test_suppression_overrides_the_model_and_says_so(client):
    body = evaluate(client, "PER-2290").json()
    assert "suppression" in body["reason"].lower()
    assert body["model_name"] == "propensity_to_convert"


def test_threshold_is_strictly_greater_than(db):
    person = models.Person(person_id="PER-EDGE")
    db.add(person)
    db.flush()
    db.add(models.Signal(person_id="PER-EDGE", name="marketing_consent", value=1.0))
    db.add(models.ModelScore(person_id="PER-EDGE", model_name="propensity_to_convert", model_version="v1", score=0.70))
    db.commit()

    decision = decision_engine.evaluate(db, person, "reactivation_offer")
    assert decision.result == "not_eligible"


def test_decisions_are_logged_and_visible_on_the_profile(client):
    evaluate(client, "PER-4471")
    evaluate(client, "PER-2290")

    history = client.get("/person/PER-4471/decisions").json()
    assert len(history) == 1
    assert history[0]["result"] == "eligible"

    profile = client.get("/person/PER-4471").json()
    assert len(profile["recent_decisions"]) == 1


def test_unknown_action_is_400_and_names_the_fix(client):
    response = evaluate(client, "PER-4471", action="send_pigeon")
    assert response.status_code == 400
    assert "ACTION_RULES" in response.json()["detail"]


def test_unknown_person_is_404(client):
    assert evaluate(client, "PER-0000").status_code == 404
