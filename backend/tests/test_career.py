"""Collector career: trip sessionization, the coordinate gap, and date filters.

The trip SQL is exercised directly against synthetic dates (``trips_sql`` is the
same string the endpoint runs), because the shared fixture store has only five
rows and other modules assert its exact totals. The endpoint itself is then
tested end to end against that fixture.
"""

import duckdb
import pytest

from app.api.collectors import trips_sql

# The fixture's r1/r2 both map to 呂碧鳳 (one romanized, one not) — r1 is dated
# 2004-09-16 with coordinates, r2 has neither.
LU = "呂碧鳳"


def run_trips(rows, gap=7):
    """Run the production trip SQL over synthetic (date, county, locality, geo) rows."""
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE occurrence (
        standard_date TIMESTAMP, county VARCHAR, locality VARCHAR, has_coordinates BOOLEAN)""")
    con.executemany("INSERT INTO occurrence VALUES (?, ?, ?, ?)", rows)
    try:
        return con.execute(trips_sql("FROM occurrence o WHERE TRUE"), [gap]).fetchall()
    finally:
        con.close()


def test_days_within_the_gap_stay_one_trip():
    rows = [(f"2020-01-0{d}", "", "", False) for d in (1, 2, 3)]
    trips = run_trips(rows)
    assert len(trips) == 1
    start, end, n_days, n_records = trips[0][:4]
    assert (str(start), str(end), n_days, n_records) == ("2020-01-01", "2020-01-03", 3, 3)


def test_a_larger_gap_splits_the_trip():
    # 3 days, then 17 idle days (> 7), then two days 5 apart (<= 7, same trip).
    rows = [("2020-01-01", "", "", False), ("2020-01-02", "", "", False),
            ("2020-01-03", "", "", False),
            ("2020-01-20", "", "", False), ("2020-01-25", "", "", False)]
    trips = run_trips(rows, gap=7)
    assert len(trips) == 2
    assert (str(trips[0][0]), str(trips[0][1])) == ("2020-01-01", "2020-01-03")
    assert (str(trips[1][0]), str(trips[1][1])) == ("2020-01-20", "2020-01-25")
    assert trips[1][2] == 2  # n_days — the 5-day gap did not split


def test_gap_is_configurable():
    rows = [("2020-01-01", "", "", False), ("2020-01-10", "", "", False)]
    assert len(run_trips(rows, gap=7)) == 2    # 9 days apart -> split
    assert len(run_trips(rows, gap=30)) == 1   # same days, wider gap -> one trip


def test_single_day_trip():
    trips = run_trips([("2020-05-05", "", "", False)])
    start, end, n_days, n_records = trips[0][:4]
    assert str(start) == str(end) == "2020-05-05" and n_days == 1 and n_records == 1


def test_n_mapped_counts_only_georeferenced():
    rows = [("2020-01-01", "", "", True), ("2020-01-01", "", "", False),
            ("2020-01-02", "", "", False)]
    trips = run_trips(rows)
    assert trips[0][3] == 3  # n_records
    assert trips[0][4] == 1  # n_mapped


def test_place_falls_back_to_locality():
    """The 呂碧鳳 case: county empty on every row, locality present."""
    rows = [("2020-01-01", "", "Mt. Hsueh (雪山)", False),
            ("2020-01-02", "", "Mt. Hsueh (雪山)", False)]
    assert run_trips(rows)[0][5] == "Mt. Hsueh (雪山)"


def test_place_prefers_county_when_present():
    rows = [("2020-01-01", "南投縣", "蓮華池", False),
            ("2020-01-02", "南投縣", "蓮華池", False)]
    assert run_trips(rows)[0][5] == "南投縣"


def test_place_is_null_when_neither_is_recorded():
    assert run_trips([("2020-01-01", "", "", False)])[0][5] is None


def test_undated_rows_form_no_trip():
    rows = [("2020-01-01", "", "", False), (None, "", "", False)]
    trips = run_trips(rows)
    assert len(trips) == 1 and trips[0][3] == 1  # the undated row is not counted


# ── endpoint ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def lu_id(client):
    """The fixture collector 呂碧鳳, whose two aliases cover r1 and r2."""
    rows = client.get("/api/collectors", params={"q": LU}).json()
    assert rows, "collector seeding did not run in conftest"
    return rows[0]["id"]


def test_career_summary_counts_undated_separately(client, lu_id):
    d = client.get(f"/api/collectors/{lu_id}/career").json()
    s = d["summary"]
    # r1 (dated 2004-09-16, has coords) + r2 (no date, no coords)
    assert s["n_records"] == 2
    assert s["n_dated"] == 1
    assert s["n_undated"] == 1      # still reported, not silently dropped
    assert s["n_geo"] == 1
    assert s["n_trips"] == 1
    assert d["collector"]["id"] == lu_id


def test_career_trip_matches_the_dated_record(client, lu_id):
    t = client.get(f"/api/collectors/{lu_id}/career").json()["trips"][0]
    assert t["start"] == t["end"] == "2004-09-16"
    assert t["n_records"] == 1 and t["n_mapped"] == 1


def test_career_years_buckets(client, lu_id):
    years = client.get(f"/api/collectors/{lu_id}/career").json()["years"]
    assert [y["year"] for y in years] == [2004]
    assert years[0]["count"] == 1 and years[0]["mapped"] == 1


def test_career_is_public_and_404s_on_unknown(client):
    assert client.get("/api/collectors/999999/career").status_code == 404
    # no auth header anywhere in this module — the board is public like /collectors


def test_career_echoes_the_gap_it_used(client, lu_id):
    """The page states the rule, so it needs the threshold, not the default."""
    assert client.get(f"/api/collectors/{lu_id}/career").json()["gap"] == 7
    assert client.get(f"/api/collectors/{lu_id}/career",
                      params={"gap": 30}).json()["gap"] == 30


def test_career_gap_param_is_bounded(client, lu_id):
    assert client.get(f"/api/collectors/{lu_id}/career", params={"gap": 0}).status_code == 422
    assert client.get(f"/api/collectors/{lu_id}/career", params={"gap": 400}).status_code == 422
    assert client.get(f"/api/collectors/{lu_id}/career", params={"gap": 30}).status_code == 200


# ── date_from / date_to ─────────────────────────────────────────────────────


def test_date_range_filters_occurrences(client):
    """r1 2004-09-16, r3 2019-08-14, r6 2018-05-02, r7 2020-07-01,
    r4 2021-06-03; r2/r5 undated."""
    def ids(**params):
        return {r["id"] for r in client.get("/api/occurrences", params=params).json()["items"]}

    assert ids(date_from="2019-01-01") == {"r3", "r4", "r7"}
    assert ids(date_to="2019-12-31") == {"r1", "r3", "r6"}
    assert ids(date_from="2019-01-01", date_to="2019-12-31") == {"r3"}
    # inclusive on both ends
    assert ids(date_from="2004-09-16", date_to="2004-09-16") == {"r1"}
    # undated rows never match a date range
    assert "r2" not in ids(date_from="1900-01-01", date_to="2100-01-01")


def test_date_range_composes_with_collector(client, lu_id):
    def total(**params):
        return client.get("/api/occurrences", params=params).json()["total"]

    assert total(collector_id=lu_id) == 2                      # r1 + r2
    assert total(collector_id=lu_id, date_from="2004-09-16",
                 date_to="2004-09-16") == 1                    # just the trip's record
    assert total(collector_id=lu_id, date_from="2030-01-01") == 0
