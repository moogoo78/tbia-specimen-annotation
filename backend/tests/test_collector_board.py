"""The collector board: the merged DuckDB/SQLite rollup, its sorts and filters.

The fixture store maps two collectors — 呂碧鳳 (r1 georeferenced + r2 not, via
two alias spellings) and 許天銓 (r4; the parser keeps the first person of a
multi-name string, so the trailing "Someone Else" is not a third row). The org
value on r3 is deliberately unmapped, so it must not appear here at all.
"""

import pytest

from app.api import collectors as mod


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The board memoizes its rollup; drop it so each test sees the store."""
    mod._BOARD, mod._BOARD_AT = None, 0.0


def board(client, **params):
    params.setdefault("min_records", 1)  # the fixture has no 10-record collector
    r = client.get("/api/collectors/board", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def by_name(items):
    return {i["label"]: i for i in items}


def test_board_lists_mapped_collectors_only(client):
    d = board(client)
    assert d["total"] == 2
    labels = list(by_name(d["items"]))
    assert any("呂碧鳳" in label for label in labels)
    # the organization on r3 was never mapped to a collector
    assert not any("亞洲蔬菜" in label for label in labels)
    assert not any("Someone Else" in label for label in labels)


def test_board_counts_come_from_the_occurrence_rollup(client):
    lu = next(i for i in board(client)["items"] if i["name"] == "呂碧鳳")
    assert lu["n_records"] == 2      # r1 + r2, via two alias spellings
    assert lu["n_geo"] == 1          # only r1 has coordinates
    assert lu["n_unmapped"] == 1
    assert lu["mapped_pct"] == 50.0
    assert lu["year_min"] == lu["year_max"] == 2004
    assert lu["n_aliases"] == 2      # "Pi-Fong Lu (呂碧鳳)" and "呂碧鳳"


def test_min_records_hides_the_tail(client):
    """The default threshold exists because 74% of real collectors have <10."""
    assert board(client, min_records=2)["total"] == 1
    assert client.get("/api/collectors/board").json()["total"] == 0  # default is 10


def test_totals_ignore_the_filters(client):
    d = board(client, min_records=2, q="呂")
    assert d["total"] == 1
    assert d["totals"] == {"collectors": 2, "records": 3, "mapped": 1}


def test_q_matches_either_name(client):
    assert board(client, q="呂碧鳳")["total"] == 1
    assert board(client, q="pi-fong")["total"] == 1   # case-insensitive romanization
    assert board(client, q="nobody")["total"] == 0


def test_sort_records_is_the_default(client):
    items = board(client)["items"]
    assert items[0]["name"] == "呂碧鳳"
    assert [i["n_records"] for i in items] == sorted(
        (i["n_records"] for i in items), reverse=True)


def test_sort_gap_leads_with_the_most_unmapped(client):
    items = board(client, sort="gap")["items"]
    assert [i["n_unmapped"] for i in items] == sorted(
        (i["n_unmapped"] for i in items), reverse=True)
    # both are tied at 1 unmapped, so the record count breaks the tie
    assert items[0]["name"] == "呂碧鳳"


def test_sort_recent_leads_with_the_latest_year(client):
    items = board(client, sort="recent")["items"]
    assert items[0]["year_max"] == 2021        # r4's collectors
    assert items[-1]["name"] == "呂碧鳳"        # last collected 2004


def test_sort_random_samples_the_same_pool(client):
    d = board(client, sort="random", limit=2)
    assert len(d["items"]) == 2
    assert d["total"] == 2                      # the pool, not the sample
    ids = {i["id"] for i in board(client)["items"]}
    assert {i["id"] for i in d["items"]} <= ids
    # a sample never repeats a collector
    assert len({i["id"] for i in d["items"]}) == 2


def test_random_respects_min_records(client):
    d = board(client, sort="random", min_records=2, limit=10)
    assert [i["name"] for i in d["items"]] == ["呂碧鳳"]


def test_paging(client):
    first = board(client, limit=1)
    second = board(client, limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert board(client, limit=1, offset=99)["items"] == []


def test_unknown_sort_is_rejected(client):
    assert client.get("/api/collectors/board", params={"sort": "nope"}).status_code == 422


def test_board_does_not_shadow_the_id_route(client):
    """`/collectors/board` is declared before `/collectors/{id}` — check the
    numeric route still resolves rather than 422-ing on the literal."""
    lu_id = board(client)["items"][0]["id"]
    assert client.get(f"/api/collectors/{lu_id}").json()["id"] == lu_id
