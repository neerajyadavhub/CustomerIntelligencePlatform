import pytest


def test_lookup_returns_every_linked_identity(client):
    response = client.get("/identity/lookup", params={"identifier": "jordyn@personalmail.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["person_id"] == "PER-4471"
    assert {i["account_type"] for i in body["identities"]} == {"personal", "business", "anonymous"}


def test_overall_confidence_is_the_weakest_link(client):
    body = client.get("/identity/lookup", params={"identifier": "jordyn@personalmail.com"}).json()
    # Identities score 0.94 / 0.94 / 0.71; one weak link must not be averaged away.
    assert body["match_confidence"] == pytest.approx(0.71)


@pytest.mark.parametrize(
    "identifier",
    ["jordyn@personalmail.com", "jordyn@resellerco.com", "+1-206-555-0111", "U-88213", "U-90441"],
)
def test_every_identifier_type_resolves_to_the_same_person(client, identifier):
    body = client.get("/identity/lookup", params={"identifier": identifier}).json()
    assert body["person_id"] == "PER-4471"


def test_unknown_identifier_is_404_not_empty_200(client):
    response = client.get("/identity/lookup", params={"identifier": "nobody@nowhere.com"})
    assert response.status_code == 404


def test_identifier_is_required(client):
    assert client.get("/identity/lookup").status_code == 422
