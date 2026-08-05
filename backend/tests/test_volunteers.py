"""The public volunteer ranking.

The test DB is shared across modules, so these tests seed their own users and
assert on the *relative* order of those users rather than absolute ranks — other
modules' annotations land in the same table.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import auth_header

CURATOR = "curator@tbia.test"


def _seed(client, name, rows):
    """Create a user with annotations. rows: (occurrence_id, field, status[, created])."""
    from app.db import SessionLocal
    from app.models import Annotation, User

    with SessionLocal() as db:
        user = User(display_name=name, email=f"{name}@vol.test", role="contributor")
        db.add(user)
        db.commit()
        db.refresh(user)
        for row in rows:
            occ, field, status = row[:3]
            ann = Annotation(
                occurrence_id=occ, field=field, status=status,
                proposed_value="x", contributor_id=user.id,
            )
            if len(row) > 3:
                ann.created = row[3]
            db.add(ann)
        db.commit()
        return user.id


@pytest.fixture(scope="module")
def ranked(client):
    """Three volunteers with deliberately shaped contributions.

    a and b tie on accepted, so b must win on distinct records — that is the
    tiebreak the endpoint promises.
    """
    last_month = datetime.now(timezone.utc).replace(day=1) - timedelta(days=5)
    a = _seed(client, "vol-a", [
        ("occ-1", "f1", "accepted"), ("occ-1", "f2", "accepted"),  # same record twice
        ("occ-2", "f1", "merged"), ("occ-2", "f2", "submitted"),
    ])
    b = _seed(client, "vol-b", [
        ("occ-3", "f1", "accepted"), ("occ-4", "f1", "accepted"), ("occ-5", "f1", "merged"),
    ])
    c = _seed(client, "vol-c", [
        ("occ-6", "f1", "accepted"),
        ("occ-7", "f1", "submitted"), ("occ-8", "f1", "submitted"),
        ("occ-9", "f1", "rejected"),
        ("occ-10", "f1", "draft"),                       # never counted
        ("occ-11", "f1", "accepted", last_month),        # outside range=month
    ])
    return {"a": a, "b": b, "c": c}


def _rows(client, ranked, **params):
    res = client.get("/api/volunteers", params={"limit": 100, **params})
    assert res.status_code == 200, res.text
    ids = set(ranked.values())
    return {r["user_id"]: r for r in res.json()["items"] if r["user_id"] in ids}


def test_ranking_counts_and_tiebreak(client, ranked):
    rows = _rows(client, ranked)
    a, b, c = rows[ranked["a"]], rows[ranked["b"]], rows[ranked["c"]]

    # accepted counts merged too; drafts are excluded from every column
    assert (a["n_accepted"], a["n_submitted"], a["n_records"]) == (3, 4, 2)
    assert (b["n_accepted"], b["n_submitted"], b["n_records"]) == (3, 3, 3)
    assert (c["n_accepted"], c["n_submitted"], c["n_records"]) == (2, 5, 5)

    # a and b tie on accepted; b wins on distinct records
    assert b["rank"] < a["rank"] < c["rank"]


def test_drafts_are_never_counted(client, ranked):
    c = _rows(client, ranked)[ranked["c"]]
    # c has 6 annotations, one of them a draft
    assert c["n_submitted"] == 5
    assert "occ-10" not in str(c)


def test_records_counts_distinct_occurrences(client, ranked):
    a = _rows(client, ranked)[ranked["a"]]
    # 4 annotations across 2 records
    assert a["n_submitted"] == 4 and a["n_records"] == 2


def test_month_range_excludes_older_work(client, ranked):
    c = _rows(client, ranked, range="month")[ranked["c"]]
    # the backdated accepted one drops out
    assert c["n_accepted"] == 1
    assert c["n_submitted"] == 4


def test_names_are_withheld_until_opted_in(client, ranked):
    body = client.get("/api/volunteers", params={"limit": 100}).text
    assert "vol-a" not in body and "vol-b" not in body
    row = _rows(client, ranked)[ranked["a"]]
    assert row["name"] is None and row["anonymous"] is True

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        u = db.get(User, ranked["a"])
        u.show_in_ranking = True
        db.add(u)
        db.commit()

    row = _rows(client, ranked)[ranked["a"]]
    assert row["name"] == "vol-a" and row["anonymous"] is False


def test_board_is_public(client):
    """The one annotation-side endpoint that must not 401."""
    assert client.get("/api/volunteers").status_code == 200
    assert client.get("/api/volunteers", params={"range": "month"}).status_code == 200
    # a bad range is rejected rather than silently treated as all-time
    assert client.get("/api/volunteers", params={"range": "week"}).status_code == 422


def test_opt_in_toggle(client):
    h = auth_header(client, CURATOR)
    assert client.get("/api/auth/me", headers=h).json()["show_in_ranking"] is False

    on = client.patch("/api/auth/me", headers=h, json={"show_in_ranking": True})
    assert on.status_code == 200 and on.json()["show_in_ranking"] is True
    assert client.get("/api/auth/me", headers=h).json()["show_in_ranking"] is True

    off = client.patch("/api/auth/me", headers=h, json={"show_in_ranking": False})
    assert off.json()["show_in_ranking"] is False


def test_opt_in_requires_auth(client):
    assert client.patch("/api/auth/me", json={"show_in_ranking": True}).status_code == 401
