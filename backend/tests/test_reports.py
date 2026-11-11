"""The per-institution annotation report (api/reports.py).

The fixture store puts every record under institution code TEST (discovered,
so it lands in the `aggregators` section): DS-A holds r1/r2/r5, DS-B r3/r4/r6/r7.
The client is session-scoped and other tests write annotations too, so these
assert *relationally* — against counts read before and after their own writes —
rather than against absolute numbers.
"""

import pytest

from app import duck
from app.config import settings
from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"
BASE = "/api/reports/institutions/TEST"


_CREATED: list[int] = []


def _post(client, occ, field, value, status="submitted"):
    res = client.post(f"/api/occurrences/{occ}/annotations",
                      headers=auth_header(client, CURATOR),
                      json={"field": field, "proposed_value": value, "status": status})
    assert res.status_code == 200, res.text
    _CREATED.append(res.json()["id"])
    return res.json()


@pytest.fixture(scope="module")
def seeded(client):
    before = client.get(BASE).json()
    sub = _post(client, "r2", "recordedBy", "Someone Report")
    draft = _post(client, "r4", "locality", "Draft Only", status="draft")
    acc = _post(client, "r6", "locality", "Accepted Place")
    res = client.patch(f"/api/annotations/{acc['id']}", headers=auth_header(client, REVIEWER),
                       json={"status": "accepted"})
    assert res.status_code == 200, res.text
    yield {"before": before, "sub": sub, "draft": draft, "acc": acc}
    # Other suites assert particular records (r4 among them) carry no
    # annotations, and the client is shared — leave the table as found.
    from app.db import SessionLocal
    from app.models import Annotation
    with SessionLocal() as db:
        db.query(Annotation).filter(Annotation.id.in_(_CREATED)).delete()
        db.commit()


def test_summary_counts_exclude_drafts(client, seeded):
    after = client.get(BASE).json()
    before = seeded["before"]
    assert after["by_status"]["total"] == before["by_status"]["total"] + 2
    assert after["by_status"]["submitted"] == before["by_status"]["submitted"] + 1
    assert after["by_status"]["accepted"] == before["by_status"]["accepted"] + 1
    assert "draft" not in after["by_status"]
    assert after["n_records_pending"] >= 1
    # Every count the summary prints is over the same rows.
    assert sum(f["total"] for f in after["by_field"]) == after["by_status"]["total"]
    assert sum(d["total"] for d in after["by_dataset"]) == after["by_status"]["total"]
    assert sum(c["n_annotations"] for c in after["contributors"]) == after["by_status"]["total"]
    assert {d["tbia_dataset_id"] for d in after["by_dataset"]} <= {"DS-A", "DS-B"}


def test_records_list_never_shows_a_draft(client, seeded):
    items = client.get(f"{BASE}/records?limit=200").json()["items"]
    ids = {i["occurrence_id"] for i in items}
    assert {"r2", "r6"} <= ids
    assert all("draft" not in it["by_status"] for it in items)


def test_records_filters(client, seeded):
    acc = client.get(f"{BASE}/records?status=accepted&limit=200").json()["items"]
    assert "r6" in {i["occurrence_id"] for i in acc}
    assert all(i["by_status"]["accepted"] == i["by_status"]["total"] for i in acc)

    ds = client.get(f"{BASE}/records?tbia_dataset_id=DS-A&limit=200").json()["items"]
    assert ds and all(i["tbia_dataset_id"] == "DS-A" for i in ds)
    assert "r6" not in {i["occurrence_id"] for i in ds}

    fld = client.get(f"{BASE}/records?field=recordedBy&limit=200").json()["items"]
    assert "r2" in {i["occurrence_id"] for i in fld}
    assert all(i["fields"] == ["recordedBy"] for i in fld)

    assert client.get(f"{BASE}/records?status=draft").status_code == 400


def test_pending_records_sort_first(client, seeded):
    items = client.get(f"{BASE}/records?limit=200").json()["items"]
    pending = [i["by_status"]["submitted"] > 0 for i in items]
    assert pending == sorted(pending, reverse=True)


def test_record_row_carries_a_thumbnail(client, seeded):
    # r4 carries two media URLs in the fixture (cleaned up after the module).
    _post(client, "r4", "recordNumber", "TAI-9a")
    r4 = next(i for i in client.get(f"{BASE}/records?limit=200").json()["items"]
              if i["occurrence_id"] == "r4")
    assert r4["thumbnail"] == "http://x/img4.jpg"
    assert r4["n_media"] == 2
    # Listed for the submitted row, never for the draft beside it.
    assert r4["fields"] == ["recordNumber"]


def test_contributor_names_follow_the_opt_in(client, seeded):
    cid = seeded["sub"]["contributor_id"]
    row = next(c for c in client.get(BASE).json()["contributors"] if c["contributor_id"] == cid)
    assert row["contributor_name"] is None
    cur = auth_header(client, CURATOR)
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    try:
        row = next(c for c in client.get(BASE).json()["contributors"]
                   if c["contributor_id"] == cid)
        assert row["contributor_name"] == "Ada Curator"
    finally:
        client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})


def test_index_lists_the_institution(client, seeded):
    items = client.get("/api/reports/institutions").json()["items"]
    row = next(i for i in items if i["code"] == "TEST")
    assert row["n_annotations"] == client.get(BASE).json()["by_status"]["total"]
    # The kind-qualified key resolves to the same source.
    assert client.get(f"/api/reports/institutions/{row['kind']}:TEST").status_code == 200


def test_unknown_institution_is_404(client):
    assert client.get("/api/reports/institutions/NOPE").status_code == 404
    assert client.get("/api/reports/institutions/NOPE/records").status_code == 404


def test_fallback_path_agrees_with_the_federated_one(client, seeded, monkeypatch):
    federated = client.get(BASE).json()
    fed_records = client.get(f"{BASE}/records?limit=200").json()
    monkeypatch.setattr(duck, "annotations_attached", lambda: False)
    fallback = client.get(BASE).json()
    for k in federated:
        assert fallback[k] == federated[k], k
    assert client.get(f"{BASE}/records?limit=200").json() == fed_records


def test_report_is_cacheable_at_the_live_ttl(client, seeded):
    for path in (BASE, f"{BASE}/records", "/api/reports/institutions"):
        cc = client.get(path).headers["cache-control"]
        assert "public" in cc and f"s-maxage={settings.cache_live_ttl}" in cc


# ── the institution-wide CSV ────────────────────────────────────────────────

def _csv(client, monkeypatch=None):
    import csv
    import io
    res = client.get(f"{BASE}/export", headers=auth_header(client, REVIEWER))
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")  # BOM, for Excel
    return list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))


def test_export_needs_a_reviewer(client, seeded):
    assert client.get(f"{BASE}/export").status_code == 401
    res = client.get(f"{BASE}/export", headers=auth_header(client, CURATOR))
    assert res.status_code == 403


def test_export_rows_match_the_report_and_carry_every_id(client, seeded):
    rows = _csv(client)
    # Every non-draft annotation, all statuses — the same set the report counts.
    assert len(rows) == client.get(BASE).json()["by_status"]["total"]
    by_id = {int(r["annotation_id"]): r for r in rows}
    assert seeded["draft"]["id"] not in by_id
    sub, acc = by_id[seeded["sub"]["id"]], by_id[seeded["acc"]["id"]]
    assert sub["status"] == "submitted" and acc["status"] == "accepted"
    # Ours, the provider's occurrenceID, and the catalog number, kept apart.
    assert sub["tbia_id"] == "r2"
    assert sub["occurrenceID"] == "urn:test:r2"
    assert sub["catalogNumber"] == "C-002"
    assert acc["occurrenceID"] == ""  # r6 publishes none; never a guess
    assert acc["proposed_value"] == "Accepted Place" and acc["reviewed_at"]
    assert sub["license_uri"].startswith("https://creativecommons.org/")


def test_export_names_contributors_by_orcid_regardless_of_opt_in(client, seeded):
    # The curator has not opted in, so the public report withholds the name —
    # the export is the attribution the licence asks for, and still names them.
    cid = seeded["sub"]["contributor_id"]
    pub = next(c for c in client.get(BASE).json()["contributors"] if c["contributor_id"] == cid)
    assert pub["contributor_name"] is None
    row = next(r for r in _csv(client) if int(r["annotation_id"]) == seeded["sub"]["id"])
    assert row["contributor"] == "Ada Curator"


def test_export_fallback_path_agrees(client, seeded, monkeypatch):
    federated = _csv(client)
    monkeypatch.setattr(duck, "annotations_attached", lambda: False)
    assert _csv(client) == federated


def test_export_is_never_cached(client, seeded):
    res = client.get(f"{BASE}/export", headers=auth_header(client, REVIEWER))
    assert "no-store" in res.headers["cache-control"]
