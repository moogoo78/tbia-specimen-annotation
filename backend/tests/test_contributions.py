"""A contributor's own work as a public page and as a private list.

`api/contributions` splits on who is asking: the public pair is the recognition
surface (no drafts, no name unless opted in), the private one is the
contributor's own view (drafts included, real totals).
"""

import pytest

from app import cache
from app.config import settings
from tests.conftest import auth_header

CURATOR = "curator@tbia.test"
REVIEWER = "reviewer@tbia.test"


@pytest.fixture(scope="module")
def contributor(client):
    """The curator's id, with at least one submitted annotation to their name.

    The client fixture is session-scoped, so this leans on whatever other tests
    have written rather than trying to own the table; it only guarantees the
    curator is *present*.
    """
    cur = auth_header(client, CURATOR)
    res = client.post("/api/occurrences/r3/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Nantou", "status": "submitted",
    })
    assert res.status_code == 200, res.text
    return res.json()["contributor_id"]


def test_profile_is_public_and_unnamed_until_opted_in(client, contributor):
    """The board is already public and already carries per-user counts; this page
    only regroups work that each record already shows. The *name* is the part
    that stays opt-in."""
    res = client.get(f"/api/contributors/{contributor}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user_id"] == contributor
    assert body["n_submitted"] >= 1
    assert body["first"] and body["last"]

    # Off by default: no name, and no ORCID iD either — the iD is an identity, so
    # publishing it for someone who withheld their name would name them.
    assert body["name"] is None
    assert body["anonymous"] is True
    assert body["orcid"] is None

    cur = auth_header(client, CURATOR)
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    try:
        named = client.get(f"/api/contributors/{contributor}").json()
        assert named["name"] == "Ada Curator"
        assert named["anonymous"] is False
        # Once named, the iD is whatever the account actually holds (the demo
        # rows are seeded without one — the rule under test is that it tracks
        # the opt-in, not that a fixture happens to have an iD).
        assert named["orcid"] == client.get("/api/auth/me", headers=cur).json()["orcid"]
    finally:
        client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})


def test_profile_counts_match_the_board(client, contributor):
    """The whole point of the shared `contributions_store.count_columns`: a board
    row and the page it opens must not print different numbers."""
    profile = client.get(f"/api/contributors/{contributor}").json()
    board = client.get("/api/volunteers?limit=100").json()["items"]
    row = next(v for v in board if v["user_id"] == contributor)
    for key in ("n_submitted", "n_accepted", "n_records"):
        assert profile[key] == row[key], key


def test_profile_is_cacheable_at_the_live_ttl(client, contributor):
    cc = client.get(f"/api/contributors/{contributor}").headers["cache-control"]
    assert "public" in cc
    assert f"s-maxage={settings.cache_live_ttl}" in cc


def test_no_page_for_an_account_that_never_contributed(client):
    """A signed-in account with no work has no page — otherwise the user table
    becomes a public directory of everyone who ever logged in."""
    admin_id = client.get("/api/auth/me", headers=auth_header(client, "admin@tbia.test")).json()["id"]
    listed = client.get("/api/volunteers?limit=100").json()["items"]
    if any(v["user_id"] == admin_id for v in listed):
        pytest.skip("the admin has contributed in this session")
    assert client.get(f"/api/contributors/{admin_id}").status_code == 404
    assert client.get("/api/contributors/999999").status_code == 404


def test_contributions_carry_their_specimen(client, contributor):
    """A field name and a dataset do not tell you which specimen you improved."""
    cur = auth_header(client, CURATOR)
    client.post("/api/occurrences/r2/annotations", headers=cur, json={
        "field": "annotationScientificName", "proposed_value": "Rosa sp.", "status": "submitted",
    })
    items = client.get(f"/api/contributors/{contributor}/annotations?limit=100").json()["items"]

    on_r2 = next(a for a in items if a["occurrence_id"] == "r2")
    assert on_r2["catalog_number"] == "C-002"
    assert on_r2["scientific_name"] is None      # r2 is the unidentified row

    on_r3 = next(a for a in items if a["occurrence_id"] == "r3")
    assert on_r3["scientific_name"] == "Helianthus annuus"
    assert on_r3["catalog_number"] == "C-003"


def test_an_annotation_whose_specimen_is_gone_still_lists(client, contributor):
    """A re-ingested store may no longer hold the row. The keys come back null;
    the contribution is not dropped the way an inner join would drop it.

    Written straight to the table because that is the only way this state
    arises: `POST .../annotations` 404s on an id the store does not hold, so the
    row can only become an orphan *after* the fact, when an ETL refresh drops
    the occurrence out from under it.
    """
    from app.db import SessionLocal
    from app.models import Annotation

    with SessionLocal() as db:
        db.add(Annotation(
            occurrence_id="vanished", dataset_name="DS-A", field="locality",
            proposed_value="Somewhere", status="submitted", contributor_id=contributor,
        ))
        db.commit()

    items = client.get(f"/api/contributors/{contributor}/annotations?limit=100").json()["items"]
    row = next(a for a in items if a["occurrence_id"] == "vanished")
    assert row["scientific_name"] is None
    assert row["catalog_number"] is None


def test_drafts_are_private_working_state(client, contributor):
    """Excluded from the public page exactly as they are from the ranking, and
    visible on the contributor's own — which is the difference between the two."""
    cur = auth_header(client, CURATOR)
    draft = client.post("/api/occurrences/r5/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "Kenting draft", "status": "draft",
    }).json()

    public = client.get(f"/api/contributors/{contributor}/annotations?limit=100").json()
    assert all(a["status"] != "draft" for a in public["items"])
    assert draft["id"] not in [a["id"] for a in public["items"]]
    # And it cannot be asked for by name either.
    assert client.get(f"/api/contributors/{contributor}/annotations?status=draft").status_code == 400

    mine = client.get("/api/annotations/mine?limit=100", headers=cur).json()
    assert draft["id"] in [a["id"] for a in mine["items"]]


def test_my_annotations_requires_a_session(client):
    assert client.get("/api/annotations/mine").status_code == 401


def test_my_summary_counts_past_the_page(client, contributor):
    """The Dashboard counted statuses by filtering whichever 500 rows it fetched.
    This is a GROUP BY over all of them, so it stays right on page one."""
    cur = auth_header(client, CURATOR)
    body = client.get("/api/annotations/mine?limit=1", headers=cur).json()
    assert len(body["items"]) == 1
    assert body["summary"]["total"] == body["total"]
    assert body["summary"]["total"] > 1
    assert body["summary"]["submitted"] >= 1


def test_my_annotations_are_only_mine(client, contributor):
    rev = auth_header(client, REVIEWER)
    mine = client.get("/api/annotations/mine?limit=100", headers=rev).json()
    assert all(a["contributor_id"] != contributor for a in mine["items"])
    assert client.get("/api/annotations/mine", headers=rev).headers["cache-control"] == cache.PRIVATE


def test_the_dashboard_list_carries_specimens_too(client, contributor):
    """`GET /api/annotations` is the dashboard's list, and it grouped by nothing
    because its rows named no specimen — only a field and a dataset. Same
    `attach_records` as the contributor pages, so "an annotation with its
    record" has one meaning across all three."""
    cur = auth_header(client, CURATOR)
    items = client.get("/api/annotations?mine=true&limit=500", headers=cur).json()["items"]
    on_r3 = next(a for a in items if a["occurrence_id"] == "r3")
    assert on_r3["scientific_name"] == "Helianthus annuus"
    assert on_r3["catalog_number"] == "C-003"
    # Grouping needs every row to answer, including the ones with no specimen.
    assert all("scientific_name" in a and "catalog_number" in a for a in items)


def test_dashboard_counts_are_counted_in_sql(client, contributor):
    """The tiles used to be `items.filter(...)` over whichever 500 rows the page
    fetched, so they were wrong past row 500 and said nothing about it."""
    cur = auth_header(client, CURATOR)
    one = client.get("/api/annotations?mine=true&limit=1", headers=cur).json()
    assert len(one["items"]) == 1
    # A page of one still reports every row.
    assert one["summary"]["total"] == one["total"] > 1
    assert one["summary"]["submitted"] >= 1

    everything = client.get("/api/annotations?mine=true&limit=500", headers=cur).json()
    counted = {}
    for a in everything["items"]:
        counted[a["status"]] = counted.get(a["status"], 0) + 1
    assert {k: v for k, v in one["summary"].items() if k != "total"} == counted


def test_the_breakdown_survives_a_status_filter(client, contributor):
    """Narrowing the list to one status must not make the other tiles read zero
    — the breakdown is what you are choosing between."""
    cur = auth_header(client, CURATOR)
    whole = client.get("/api/annotations?mine=true", headers=cur).json()["summary"]
    body = client.get("/api/annotations?mine=true&status=submitted", headers=cur).json()
    assert body["summary"] == whole
    assert body["total"] == whole["submitted"] < whole["total"]
    assert all(a["status"] == "submitted" for a in body["items"])


def test_scope_changes_the_counts(client, contributor):
    """`mine` is a real filter on the summary, not just on the list."""
    cur = auth_header(client, CURATOR)
    # Someone else's work, so the two scopes have something to differ by.
    assert client.post("/api/occurrences/r6/annotations",
                       headers=auth_header(client, REVIEWER),
                       json={"field": "locality", "proposed_value": "Elsewhere",
                             "status": "submitted"}).status_code == 200

    mine = client.get("/api/annotations?mine=true", headers=cur).json()["summary"]
    everyone = client.get("/api/annotations", headers=cur).json()["summary"]
    assert everyone["total"] > mine["total"]
    # And "mine" really is a subset, status by status.
    assert all(everyone.get(k, 0) >= v for k, v in mine.items())


def test_the_activity_feed_is_public(client, contributor):
    """What the community has been doing was behind a login on the dashboard,
    though every row of it is already on its own record page."""
    res = client.get("/api/contributions?limit=100")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["items"], body
    # Mixed contributors, each named by their own opt-in.
    assert len({a["contributor_id"] for a in body["items"]}) >= 1
    assert all(a["contributor_name"] is None for a in body["items"])  # nobody opted in
    # Specimens come with them, so the feed can group by record.
    assert any(a["scientific_name"] or a["catalog_number"] for a in body["items"])
    assert f"s-maxage={settings.cache_live_ttl}" in res.headers["cache-control"]


def test_the_feed_never_shows_drafts(client, contributor):
    cur = auth_header(client, CURATOR)
    draft = client.post("/api/occurrences/r7/annotations", headers=cur, json={
        "field": "locality", "proposed_value": "A private draft", "status": "draft",
    }).json()
    body = client.get("/api/contributions?limit=100").json()
    assert draft["id"] not in [a["id"] for a in body["items"]]
    assert "draft" not in body["summary"]
    assert client.get("/api/contributions?status=draft").status_code == 400
    # And the public total is the private one minus the drafts.
    everyone = client.get("/api/annotations", headers=cur).json()["summary"]
    assert body["summary"]["total"] == everyone["total"] - everyone.get("draft", 0)


def test_the_feed_names_whoever_opted_in(client, contributor):
    cur = auth_header(client, CURATOR)
    client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": True})
    try:
        items = client.get("/api/contributions?limit=100").json()["items"]
        theirs = [a for a in items if a["contributor_id"] == contributor]
        assert theirs and all(a["contributor_name"] == "Ada Curator" for a in theirs)
        # Everyone else is still withheld — the opt-in is per person, not global.
        assert all(a["contributor_name"] is None
                   for a in items if a["contributor_id"] != contributor)
    finally:
        client.patch("/api/auth/me", headers=cur, json={"show_in_ranking": False})
