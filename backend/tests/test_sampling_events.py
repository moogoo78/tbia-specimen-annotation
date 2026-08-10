"""The curated sampling-event chronology: seeding, filters, and the career anchor.

The fixture chronology (``conftest.SAMPLING_EVENTS``) is three events chosen to
cover what the real transcription contains — a single year, a range, an elided
century, a party of two, and actors that do and do not resolve to a collector.
"""

import json

import pytest

from app.db import SessionLocal
from app.models import SamplingEvent, SamplingEventActor
from app.seed_sampling_events import SeedError, _norm, parse_years
from app.seed_sampling_events import populate as populate_events
from tests.conftest import SAMPLING_EVENTS, write_sampling_events


# ── the chronology endpoint ─────────────────────────────────────────────────

def test_events_come_back_earliest_first(client):
    rows = client.get("/api/sampling-events").json()
    assert [e["verbatim_event_date"] for e in rows] == ["1901", "1905-1910", "1960-62"]


def test_event_carries_the_darwin_core_fields(client):
    ev = client.get("/api/sampling-events").json()[0]
    assert ev["event_date"] == "1901"                   # eventDate
    assert ev["verbatim_event_date"] == "1901"          # verbatimEventDate
    assert ev["verbatim_locality"] == "淡水"             # verbatimLocality
    assert ev["event_remarks"] == "英國"                 # eventRemarks -> 標本存放處
    assert ev["location_according_to"] == "測試來源, 1975; 測試, 1983"  # locationAccordingTo
    assert ev["narrative"] == "採集於淡水。"              # the full 主要記事


def test_per_row_citation_overrides_the_source_default(client):
    """A second chronology can be transcribed later without a code change."""
    rows = client.get("/api/sampling-events").json()
    assert rows[-1]["location_according_to"] == "另一來源, 1990"


def test_year_range_filters_on_overlap_not_containment(client):
    """1905-1910 starts before the window and must still surface."""
    rows = client.get("/api/sampling-events", params={"year_from": 1908, "year_to": 1920}).json()
    assert [e["verbatim_event_date"] for e in rows] == ["1905-1910"]


def test_year_range_open_ended(client):
    rows = client.get("/api/sampling-events", params={"year_from": 1950}).json()
    assert [e["verbatim_event_date"] for e in rows] == ["1960-62"]
    rows = client.get("/api/sampling-events", params={"year_to": 1901}).json()
    assert [e["verbatim_event_date"] for e in rows] == ["1901"]


def test_free_text_matches_locality_repository_narrative_and_names(client):
    def dates(q):
        return [e["verbatim_event_date"] for e in
                client.get("/api/sampling-events", params={"q": q}).json()]

    assert dates("淡水") == ["1901"]          # locality
    assert dates("林業部") == ["1960-62"]      # repository
    assert dates("遠征") == ["1905-1910"]      # narrative
    assert dates("呂碧鳳") == ["1901", "1905-1910"]   # actor name
    assert dates("Ghost") == ["1905-1910"]    # unresolved actor still searchable
    assert dates("nothing-matches-this") == []


def test_collector_filter_uses_resolved_actors(client):
    lu = client.get("/api/collectors/resolve", params={"recorded_by": "呂碧鳳"}).json()
    rows = client.get("/api/sampling-events", params={"collector_id": lu["id"]}).json()
    assert [e["verbatim_event_date"] for e in rows] == ["1901", "1905-1910"]


def test_single_event_and_404(client):
    first = client.get("/api/sampling-events").json()[0]
    assert client.get(f"/api/sampling-events/{first['id']}").json()["id"] == first["id"]
    assert client.get("/api/sampling-events/999999").status_code == 404


# ── specimen counts ─────────────────────────────────────────────────────────

def test_counts_cover_every_event_including_the_empty_ones(client):
    counts = client.get("/api/sampling-events/counts").json()
    ids = {str(e["id"]) for e in client.get("/api/sampling-events").json()}
    assert set(counts) == ids
    # The fixture chronology is 1901-1962; the fixture records are 2004-2021.
    assert set(counts.values()) == {0}


def test_counts_are_the_collector_and_year_query(client):
    """An event over the years its collector actually worked counts those rows.

    r1 (2004, 'Pi-Fong Lu (呂碧鳳)') and r2 (no date, '呂碧鳳') are the same
    collector; only the dated one can fall inside a year range.
    """
    doc = {"source": {"citation": "x"}, "events": [
        {"seq": 1, "verbatim_event_date": "2000-2010", "narrative": "n",
         "actors": [{"recorded_by": "呂碧鳳"}]},
        {"seq": 2, "verbatim_event_date": "1990", "narrative": "n",
         "actors": [{"recorded_by": "呂碧鳳"}]},
        {"seq": 3, "verbatim_event_date": "2000-2010", "narrative": "n",
         "actors": [{"recorded_by": "Ghost Collector"}]},
    ]}
    populate_events(write_sampling_events(doc))
    try:
        events = {e["seq"]: e for e in client.get("/api/sampling-events").json()}
        counts = client.get("/api/sampling-events/counts").json()
        assert counts[str(events[1]["id"])] == 1   # the dated record, in range
        assert counts[str(events[2]["id"])] == 0   # right person, wrong years
        assert counts[str(events[3]["id"])] == 0   # unresolved actor counts nothing
    finally:
        populate_events(write_sampling_events())  # restore


def test_counts_follow_a_reseed_rather_than_the_cache(client):
    """A transcription fix must show up without a restart."""
    before = client.get("/api/sampling-events/counts").json()
    assert set(before.values()) == {0}

    doc = {"source": {"citation": "x"}, "events": [
        {"seq": 1, "verbatim_event_date": "2000-2010", "narrative": "n",
         "actors": [{"recorded_by": "呂碧鳳"}]},
    ]}
    populate_events(write_sampling_events(doc))
    try:
        assert set(client.get("/api/sampling-events/counts").json().values()) == {1}
    finally:
        populate_events(write_sampling_events())
    assert set(client.get("/api/sampling-events/counts").json().values()) == {0}


def test_counts_survive_a_missing_sqlite_attach(client, monkeypatch):
    """Same answer through the Python-side alias fallback."""
    from app import duck
    from app.api import sampling_events as se

    doc = {"source": {"citation": "x"}, "events": [
        {"seq": 1, "verbatim_event_date": "2000-2010", "narrative": "n",
         "actors": [{"recorded_by": "呂碧鳳"}]},
    ]}
    populate_events(write_sampling_events(doc))
    monkeypatch.setattr(duck, "annotations_attached", lambda: False)
    se._COUNTS = None       # the cache would otherwise answer from the ATTACHed run
    try:
        assert set(client.get("/api/sampling-events/counts").json().values()) == {1}
    finally:
        se._COUNTS = None
        populate_events(write_sampling_events())


def test_counting_does_not_associate_a_record_with_an_event(client):
    """The count is a query, not a link: no endpoint hands back occurrence ids
    for an event, and the event payload gains no occurrence field."""
    ev = client.get("/api/sampling-events").json()[0]
    assert "occurrences" not in ev and "occurrence_ids" not in ev
    assert client.get(f"/api/sampling-events/{ev['id']}/occurrences").status_code == 404


# ── actors ──────────────────────────────────────────────────────────────────

def test_a_party_keeps_every_participant_in_source_order(client):
    ev = client.get("/api/sampling-events").json()[1]
    assert [a["recorded_by"] for a in ev["actors"]] == ["呂碧鳳", "Ghost Collector"]
    assert [a["position"] for a in ev["actors"]] == [0, 1]


def test_actors_keep_their_own_nationality(client):
    """1898-1902 in the real chronology pairs 松村任三 (日) with V. Faurie (英)."""
    ev = client.get("/api/sampling-events").json()[1]
    assert [a["nationality"] for a in ev["actors"]] == ["中", "英"]


def test_unmatched_actor_is_kept_with_a_null_collector(client):
    """Most 19th-century botanists hold no TBIA records; that is not a reason to
    drop them from the chronology."""
    ev = client.get("/api/sampling-events").json()[1]
    ghost = next(a for a in ev["actors"] if a["recorded_by"] == "Ghost Collector")
    assert ghost["collector_id"] is None
    assert ghost["collector_label"] is None

    known = next(a for a in ev["actors"] if a["recorded_by"] == "呂碧鳳")
    assert known["collector_id"] is not None
    assert "呂碧鳳" in known["collector_label"]


# ── the career anchor ───────────────────────────────────────────────────────

def test_career_carries_reference_events_without_disturbing_trips(client):
    lu = client.get("/api/collectors/resolve", params={"recorded_by": "呂碧鳳"}).json()
    career = client.get(f"/api/collectors/{lu['id']}/career").json()

    assert [e["verbatim_event_date"] for e in career["reference_events"]] == ["1901", "1905-1910"]
    # The derived half is untouched in shape.
    assert set(career) >= {"collector", "gap", "summary", "years", "trips", "reference_events"}
    assert isinstance(career["trips"], list)
    assert "n_trips" in career["summary"]


def test_career_of_an_undocumented_collector_has_no_reference_events(client):
    """A collector the chronology never names still gets a well-formed career."""
    named = {
        a["collector_id"]
        for ev in client.get("/api/sampling-events").json()
        for a in ev["actors"] if a["collector_id"] is not None
    }
    other = next(
        (c for c in client.get("/api/collectors").json() if c["id"] not in named), None
    )
    assert other is not None, "fixture must hold a collector the chronology omits"

    career = client.get(f"/api/collectors/{other['id']}/career").json()
    assert career["reference_events"] == []
    assert isinstance(career["trips"], list)      # the derived half is unaffected


# ── seeding ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verbatim, expected", [
    ("1854", (1854, 1854)),          # single year
    ("1861-1866", (1861, 1866)),     # full range
    ("1960-62", (1960, 1962)),       # elided century
    ("1972-1979", (1972, 1979)),
    ("1905 - 1908", (1905, 1908)),   # spaced
    ("1913–1915", (1913, 1915)),     # en dash
    ("", None),
    ("1980s", None),
    ("about 1900", None),
])
def test_parse_years(verbatim, expected):
    assert parse_years(verbatim) == expected


def test_years_are_derived_when_the_row_omits_them(client):
    """A hand-added entry only has to carry the 年代 cell as printed."""
    doc = {"source": {"citation": "x"}, "events": [{
        "seq": 1, "source_page": 1, "verbatim_event_date": "1960-62",
        "narrative": "n", "actors": [{"recorded_by": "Someone"}],
    }]}
    r = populate_events(write_sampling_events(doc), dry_run=True)
    assert r["events"] == 1
    populate_events(write_sampling_events())  # restore


def test_mistyped_year_pair_is_refused(client):
    """The pair must agree with the cell it was transcribed from."""
    doc = {"source": {"citation": "x"}, "events": [{
        "seq": 1, "verbatim_event_date": "1861-1866",
        "year_start": 1861, "year_end": 1899,
        "actors": [{"recorded_by": "Someone"}],
    }]}
    with pytest.raises(SeedError, match="implies 1861-1866"):
        populate_events(write_sampling_events(doc))
    populate_events(write_sampling_events())  # restore


def test_date_parsing_covers_single_range_and_elided_century(client):
    """The three 年代 shapes the source prints."""
    rows = client.get("/api/sampling-events").json()
    got = {e["verbatim_event_date"]: (e["event_date"], e["year_start"], e["year_end"])
           for e in rows}
    assert got["1901"] == ("1901", 1901, 1901)
    assert got["1905-1910"] == ("1905/1910", 1905, 1910)
    assert got["1960-62"] == ("1960/1962", 1960, 1962)


def test_reseeding_is_idempotent(client):
    """Re-running after a hand correction must leave exactly the file's contents."""
    def snapshot():
        with SessionLocal() as db:
            return [
                (e.seq, e.event_date, e.verbatim_locality, e.event_remarks,
                 tuple((a.recorded_by, a.position, a.collector_id) for a in e.actors))
                for e in db.query(SamplingEvent).order_by(SamplingEvent.seq).all()
            ]

    before = snapshot()
    r = populate_events(write_sampling_events())
    assert r["events"] == 3 and r["actors"] == 4
    assert snapshot() == before

    with SessionLocal() as db:
        assert db.query(SamplingEvent).count() == 3
        assert db.query(SamplingEventActor).count() == 4


def test_seed_reports_resolution_and_names_the_misses(client):
    r = populate_events(write_sampling_events())
    assert r["resolved"] == 2                     # 呂碧鳳, twice
    assert r["unmatched"] == ["Ghost Collector", "群體計劃"]


def test_dry_run_writes_nothing(client):
    with SessionLocal() as db:
        before = db.query(SamplingEvent).count()
    doc = {"source": {"citation": "x"}, "events": [dict(SAMPLING_EVENTS["events"][0], seq=99)]}
    r = populate_events(write_sampling_events(doc), dry_run=True)
    assert r["dry_run"] and r["events"] == 1
    with SessionLocal() as db:
        assert db.query(SamplingEvent).count() == before
    populate_events(write_sampling_events())  # restore the fixture state


@pytest.mark.parametrize("doc, msg", [
    ({"events": []}, "no events"),
    ({"nope": 1}, "'events'"),
    ({"events": [{"year_start": 1900}]}, "year_end"),
    ({"events": [{"year_start": 1900, "year_end": 1890, "actors": [{"recorded_by": "x"}]}]},
     "precedes"),
    ({"events": [{"year_start": 1900, "year_end": 1900, "actors": []}]}, "at least one actor"),
    ({"events": [{"year_start": 1900, "year_end": 1900, "actors": [{"recorded_by": " "}]}]},
     "no recorded_by"),
])
def test_malformed_chronology_is_refused(client, doc, msg):
    """Refuse the file rather than seed a partial chronology."""
    with pytest.raises(SeedError) as exc:
        populate_events(write_sampling_events(doc))
    assert msg in str(exc.value)
    populate_events(write_sampling_events())  # restore


def test_invalid_json_and_missing_file_are_refused(client, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SeedError, match="not valid JSON"):
        populate_events(bad)
    with pytest.raises(SeedError, match="not found"):
        populate_events(tmp_path / "absent.json")


def test_name_folding_is_conservative():
    """Closes spacing and punctuation, and nothing more."""
    assert _norm("R. Fortune") == _norm("R.Fortune") == _norm("r fortune")
    assert _norm("牧野富太郎") == _norm("牧野 富太郎")
    assert _norm("A. Henry") != _norm("B. Henry")


# ── the curated file itself ─────────────────────────────────────────────────

def test_shipped_chronology_is_wellformed():
    """data/sampling_events.json is hand-edited, so guard its shape in CI."""
    from app.seed_sampling_events import DEFAULT_JSON, _load, _validate

    if not DEFAULT_JSON.exists():
        pytest.skip("chronology not present in this checkout")
    source, events = _load(DEFAULT_JSON)
    _validate(events)                       # raises on a bad hand edit
    assert source.get("citation")
    assert len(events) >= 30
    # Every event traces back to a scan page, so a transcription can be checked.
    assert all(e.get("source_page") for e in events)
    # The party that motivated the actor table.
    biggest = max(events, key=lambda e: len(e["actors"]))
    assert len(biggest["actors"]) == 15
