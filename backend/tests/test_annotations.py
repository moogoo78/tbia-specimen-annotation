from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"


def test_ai_extract_stub(client):
    h = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r2/extract", headers=h)
    assert res.status_code == 200
    data = res.json()
    # r2 lacks identification -> stub proposes scientificName from source name
    fields = {f["field"] for f in data["fields"]}
    assert "scientificName" in fields
    assert data["model"]


def test_annotation_lifecycle_and_role_gating(client):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)

    # contributor creates an annotation
    create = client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "scientificName", "proposed_value": "Chilodontia laevis",
        "original_value": None, "note": "from label", "status": "submitted",
    })
    assert create.status_code == 200, create.text
    ann_id = create.json()["id"]
    assert create.json()["dataset_name"] == "DS-A"

    # contributor cannot accept (reviewer-only)
    forbidden = client.patch(f"/api/annotations/{ann_id}", headers=cur, json={"status": "accepted"})
    assert forbidden.status_code == 403

    # reviewer accepts
    accept = client.patch(f"/api/annotations/{ann_id}", headers=rev, json={"status": "accepted"})
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"
    assert accept.json()["reviewed_by"] is not None

    # appears on the occurrence detail
    detail = client.get("/api/occurrences/r2").json()
    assert any(a["id"] == ann_id and a["status"] == "accepted" for a in detail["annotations"])


def test_anonymous_cannot_annotate(client):
    res = client.post("/api/occurrences/r2/annotations", json={
        "field": "scientificName", "proposed_value": "x", "status": "submitted"})
    assert res.status_code == 401


def test_provider_export_reviewer_only(client):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    # contributor forbidden
    assert client.get("/api/export/provider?dataset_name=DS-A", headers=cur).status_code == 403
    # reviewer gets deltas (accepted annotation from previous test)
    res = client.get("/api/export/provider?dataset_name=DS-A", headers=rev)
    assert res.status_code == 200
    body = res.json()
    assert body["count"] >= 1
    assert body["deltas"][0]["proposed_value"] == "Chilodontia laevis"
