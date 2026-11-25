"""Identifications: a person's determination of a specimen (DwC Identification),
under the same workflow rules as an annotation (app/workflow.py)."""

import csv
import io

import pytest

from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"
ADMIN = "admin@tbia.test"
OCC = "r5"  # DS-A, genus-level in the fixture: the gap a determination closes

BODY = {
    "scientific_name": "Chilodontia laevis",
    "taxon_rank": "species",
    "identification_qualifier": "cf.",
    "verbatim_identification": "Chilodontia cf. laevis",
    "identified_by": "Ada Curator",
    "identified_by_id": "https://orcid.org/0000-0002-1825-0097",
    "date_identified": "2026-11",
    "identification_references": "Flora of Taiwan 2nd ed. | TaiCOL",
    "identification_remarks": "compared with type images",
    # Hand-typed name (no TaiCOL id), so the contributor names the source.
    "name_according_to": "Flora of Taiwan, 2nd ed. (2003)",
}


@pytest.fixture
def made(client):
    """Ids created by a test, deleted after it so the session store stays clean."""
    ids: list[int] = []
    yield ids
    from app.db import SessionLocal
    from app.models import Identification

    with SessionLocal() as db:
        for i in ids:
            row = db.get(Identification, i)
            if row:
                db.delete(row)
        db.commit()


def _create(client, headers, made, **over):
    res = client.post(f"/api/occurrences/{OCC}/identifications", headers=headers,
                      json={**BODY, **over})
    if res.status_code == 200:
        made.append(res.json()["id"])
    return res


def test_create_stores_every_term(client, made):
    cur = auth_header(client, CURATOR)
    res = _create(client, cur, made)
    assert res.status_code == 200, res.text
    out = res.json()
    for k, v in BODY.items():
        assert out[k] == v
    assert out["status"] == "submitted"
    assert out["dataset_name"] == "DS-A"
    assert out["license"] == "CC-BY-NC-4.0"       # the user's default
    detail = client.get(f"/api/occurrences/{OCC}").json()
    assert out["id"] in {i["id"] for i in detail["identifications"]}


def test_only_the_name_is_required(client, made):
    cur = auth_header(client, CURATOR)
    res = client.post(f"/api/occurrences/{OCC}/identifications", headers=cur,
                      json={"scientific_name": "  Pocillopora  ", "identified_by": " ",
                            "name_according_to": "Veron 2000"})
    assert res.status_code == 200, res.text
    made.append(res.json()["id"])
    assert res.json()["scientific_name"] == "Pocillopora"
    assert res.json()["identified_by"] is None       # blank is no value


@pytest.mark.parametrize("over,status", [
    ({"scientific_name": "   "}, 400),
    ({"date_identified": "11/2026"}, 400),
    ({"date_identified": "2026-13-01"}, 400),
    ({"status": "accepted"}, 400),              # cannot create already reviewed
    ({"license": "ARR"}, 400),
])
def test_bad_input_is_refused(client, made, over, status):
    cur = auth_header(client, CURATOR)
    assert _create(client, cur, made, **over).status_code == status


@pytest.mark.parametrize("date", ["1932", "1932-04", "1932-04-07", "1930/1932-04"])
def test_partial_and_interval_dates_accepted(client, made, date):
    cur = auth_header(client, CURATOR)
    assert _create(client, cur, made, date_identified=date).status_code == 200


def test_anonymous_cannot_identify(client):
    res = client.post(f"/api/occurrences/{OCC}/identifications", json=BODY)
    assert res.status_code == 401


def test_unknown_occurrence_404(client):
    cur = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/nope/identifications", headers=cur, json=BODY)
    assert res.status_code == 404


def test_review_lifecycle(client, made):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    iid = _create(client, cur, made).json()["id"]

    # Owner edits while pending.
    res = client.patch(f"/api/identifications/{iid}", headers=cur,
                       json={"identification_remarks": "", "taxon_rank": "variety"})
    assert res.status_code == 200
    assert res.json()["identification_remarks"] is None
    assert res.json()["taxon_rank"] == "variety"
    # Name cannot be cleared.
    assert client.patch(f"/api/identifications/{iid}", headers=cur,
                        json={"scientific_name": ""}).status_code == 400
    # Contributor cannot review.
    assert client.patch(f"/api/identifications/{iid}", headers=cur,
                        json={"status": "accepted"}).status_code == 403
    res = client.patch(f"/api/identifications/{iid}", headers=rev, json={"status": "accepted"})
    assert res.status_code == 200
    assert res.json()["reviewed_by"] is not None
    # After review the owner may no longer edit content...
    assert client.patch(f"/api/identifications/{iid}", headers=cur,
                        json={"identification_remarks": "late"}).status_code == 403
    # ...but may still relicense, which the reviewer may not.
    assert client.patch(f"/api/identifications/{iid}", headers=rev,
                        json={"license": "CC0-1.0"}).status_code == 403
    res = client.patch(f"/api/identifications/{iid}", headers=cur, json={"license": "CC0-1.0"})
    assert res.status_code == 200 and res.json()["license"] == "CC0-1.0"
    # No way back to draft.
    assert client.patch(f"/api/identifications/{iid}", headers=rev,
                        json={"status": "draft"}).status_code == 400


def test_no_drafts(client, made):
    cur = auth_header(client, CURATOR)
    res = _create(client, cur, made, status="draft")
    assert res.status_code == 400 and "no drafts" in res.json()["detail"]


def test_legacy_drafts_stay_private_until_submitted(client, made):
    """Rows saved as drafts before the rule: still private, still submittable."""
    from app.db import SessionLocal
    from app.models import Identification

    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    draft = _create(client, cur, made).json()["id"]
    with SessionLocal() as db:
        db.get(Identification, draft).status = "draft"
        db.commit()
    for headers in ({}, cur):
        idents = client.get(f"/api/occurrences/{OCC}", headers=headers).json()["identifications"]
        assert draft not in {i["id"] for i in idents}
    mine = client.get("/api/identifications?mine=true&status=draft", headers=cur).json()
    assert draft in {i["id"] for i in mine["items"]}
    others = client.get("/api/identifications", headers=rev).json()
    assert draft not in {i["id"] for i in others["items"]}
    # Submitting publishes it.
    assert client.patch(f"/api/identifications/{draft}", headers=cur,
                        json={"status": "submitted"}).status_code == 200
    idents = client.get(f"/api/occurrences/{OCC}").json()["identifications"]
    assert draft in {i["id"] for i in idents}


def test_contributor_named_only_when_opted_in(client, made):
    cur = auth_header(client, CURATOR)
    iid = _create(client, cur, made).json()["id"]

    def named():
        idents = client.get(f"/api/occurrences/{OCC}").json()["identifications"]
        row = next(i for i in idents if i["id"] == iid)
        assert row["contributor_id"]
        return row["contributor_name"]

    assert named() is None
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    try:
        assert named() == "Ada Curator"
    finally:
        client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})


def test_export_is_reviewer_only_and_dwc_shaped(client, made):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    iid = _create(client, cur, made, license="CC-BY-4.0").json()["id"]
    url = "/api/export/identifications?dataset_name=DS-A"
    assert client.get(url, headers=cur).status_code == 403

    # Not exported until reviewed.
    rows = client.get(url, headers=rev).json()["identifications"]
    assert iid not in {r["identification_id"] for r in rows}
    client.patch(f"/api/identifications/{iid}", headers=rev, json={"status": "accepted"})

    rows = client.get(url, headers=rev).json()["identifications"]
    row = next(r for r in rows if r["identification_id"] == iid)
    assert row["tbia_id"] == OCC
    assert row["scientificName"] == "Chilodontia laevis"
    assert row["identifiedByID"] == BODY["identified_by_id"]
    assert row["dateIdentified"] == "2026-11"
    assert row["contributor"] == "Ada Curator"     # ORCID name: the attribution
    assert row["license_uri"] == "https://creativecommons.org/licenses/by/4.0/"

    res = client.get(url + "&format=csv", headers=rev)
    assert res.status_code == 200
    reader = csv.DictReader(io.StringIO(res.text))
    assert reader.fieldnames[:5] == [
        "identification_id", "tbia_id", "occurrenceID", "catalogNumber", "scientificName",
    ]
    assert any(r["identification_id"] == str(iid) for r in reader)


# ── TaiCOL-picked names ────────────────────────────────────────────────────
TAICOL_ID = "https://taicol.tw/name/26079"
ACCORDING = "TaiCOL (Catalogue of Life in Taiwan), https://taicol.tw/taxon/t0040360, version 2026-09-23"


def test_picked_name_keeps_its_taicol_id(client, made):
    cur = auth_header(client, CURATOR)
    rev = auth_header(client, REVIEWER)
    res = _create(client, cur, made, scientific_name="Begonia formosana",
                  scientific_name_id=TAICOL_ID, name_according_to=ACCORDING)
    assert res.status_code == 200, res.text
    iid = res.json()["id"]
    assert res.json()["scientific_name_id"] == TAICOL_ID
    assert res.json()["name_according_to"] == ACCORDING

    client.patch(f"/api/identifications/{iid}", headers=rev, json={"status": "accepted"})
    rows = client.get("/api/export/identifications?dataset_name=DS-A", headers=rev).json()["identifications"]
    row = next(r for r in rows if r["identification_id"] == iid)
    assert row["scientificNameID"] == TAICOL_ID and row["nameAccordingTo"] == ACCORDING


def test_only_taicol_ids_are_accepted(client, made):
    cur = auth_header(client, CURATOR)
    res = _create(client, cur, made, scientific_name_id="https://example.org/name/1")
    assert res.status_code == 400


def test_hand_typed_name_needs_name_according_to(client, made):
    cur = auth_header(client, CURATOR)
    # Submitted without a source: refused.
    assert _create(client, cur, made, name_according_to="").status_code == 400
    assert _create(client, cur, made, name_according_to="   ").status_code == 400
    # Kept as given when supplied, with no TaiCOL id.
    res = _create(client, cur, made, name_according_to="Flora of Taiwan, 2nd ed. (2003)")
    assert res.status_code == 200
    assert res.json()["scientific_name_id"] is None
    assert res.json()["name_according_to"] == "Flora of Taiwan, 2nd ed. (2003)"
    # A legacy draft without one cannot be submitted until it is filled.
    from app.db import SessionLocal
    from app.models import Identification
    did = _create(client, cur, made).json()["id"]
    with SessionLocal() as db:
        row = db.get(Identification, did)
        row.status, row.name_according_to = "draft", None
        db.commit()
    assert client.patch(f"/api/identifications/{did}", headers=cur,
                        json={"status": "submitted"}).status_code == 400
    res = client.patch(f"/api/identifications/{did}", headers=cur,
                       json={"name_according_to": "Lu & Yang 2022", "status": "submitted"})
    assert res.status_code == 200 and res.json()["status"] == "submitted"


def test_picked_name_needs_no_hand_citation(client, made):
    cur = auth_header(client, CURATOR)
    res = _create(client, cur, made, scientific_name="Begonia formosana",
                  scientific_name_id=TAICOL_ID, name_according_to=ACCORDING)
    assert res.status_code == 200 and res.json()["name_according_to"] == ACCORDING


def test_retyping_the_name_clears_the_taicol_id(client, made):
    cur = auth_header(client, CURATOR)
    iid = _create(client, cur, made, scientific_name="Begonia formosana",
                  scientific_name_id=TAICOL_ID, name_according_to=ACCORDING).json()["id"]
    # Same name again: untouched.
    res = client.patch(f"/api/identifications/{iid}", headers=cur, json={"scientific_name": "Begonia formosana"})
    assert res.json()["scientific_name_id"] == TAICOL_ID
    # A different name typed by hand: the id described the old one.
    res = client.patch(f"/api/identifications/{iid}", headers=cur, json={"scientific_name": "Begonia sp."})
    assert res.json()["scientific_name_id"] is None and res.json()["name_according_to"] is None


def test_taicol_routes(client, monkeypatch):
    from app import taicol

    async def fake_suggest(q, lang="zh-hant"):
        return [{"taxon_id": "t0040360", "name": "Begonia formosana",
                 "name_parts": [{"text": "Begonia formosana", "italic": True}],
                 "common_names": ["白斑水鴨腳"]}]

    async def fake_taxon(tid):
        return None if tid != "t0040360" else {"taxon_id": tid, "scientific_name_id": TAICOL_ID,
                                                "name_according_to": ACCORDING}

    monkeypatch.setattr(taicol, "suggest", fake_suggest)
    monkeypatch.setattr(taicol, "taxon", fake_taxon)
    res = client.get("/api/taicol/suggest?q=Begonia")
    assert res.status_code == 200 and res.json()[0]["taxon_id"] == "t0040360"
    assert "public" in res.headers["cache-control"]
    assert client.get("/api/taicol/taxon/t0040360").json()["scientific_name_id"] == TAICOL_ID
    assert client.get("/api/taicol/taxon/t9999999").status_code == 404

    async def down(*a, **k):
        raise taicol.TaicolUnavailable("TaiCOL: ConnectError")
    monkeypatch.setattr(taicol, "suggest", down)
    res = client.get("/api/taicol/suggest?q=Begonia")
    assert res.status_code == 502
    assert "public" not in res.headers.get("cache-control", "")


def test_parse_label_never_keeps_markup():
    from app.taicol import parse_label
    out = parse_label("<i>Begonia formosana</i> fo. <i>albomaculata</i> 白斑水鴨腳,水鴨腳")
    assert out["name"] == "Begonia formosana fo. albomaculata"
    assert out["common_names"] == ["白斑水鴨腳", "水鴨腳"]
    assert [p["italic"] for p in out["name_parts"]] == [True, False, True]
    assert all("<" not in p["text"] for p in out["name_parts"])
