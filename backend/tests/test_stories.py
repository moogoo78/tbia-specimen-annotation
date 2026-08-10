"""Curated stories: the transcription served back with the store's answers.

The fixture story is shaped like ``data/story_begonia.json`` but points at the
fixture occurrences, so the counts are checkable: 呂碧鳳 holds r1 (2004-09-16)
and r2 (undated), and the store holds one *Rosa canina*.
"""

import json

import pytest

from app.api import stories


FIXTURE = {
    "source": {"title": "Test curation", "citation": "測試策展 [https://example.org/x]（瀏覽）。"},
    "subject": {"name": "呂碧鳳", "name_en": "Pi-Fong Lu"},
    "focus": {"genus": "Pocillopora", "name_zh": "測試屬"},
    "regions": [
        {
            "key": "here", "name": "此地", "name_en": "Here",
            "summary": "測試地區。",
            "trips": [
                # r1 falls inside; r2 has no date and can fall in nothing.
                {"seq": 1, "verbatim_date": "2004.09", "date_start": "2004-09-01",
                 "date_end": "2004-09-30", "precision": "month", "narrative": "n1",
                 "party": [{"name": "呂碧鳳"}, {"name": "Someone"}]},
                {"seq": 2, "verbatim_date": "2019.08.14", "date_start": "2019-08-14",
                 "date_end": "2019-08-14", "precision": "day", "narrative": "n2"},
            ],
            "species": [
                {"name": "Rosa canina", "authorship": "L.", "name_zh": "測試薔薇"},
                {"name": "Begonia nowhere", "authorship": "C.I Peng"},
                {"name": "", "name_zh": "只有中文名"},
            ],
        },
    ],
}


@pytest.fixture
def story(client, tmp_path, monkeypatch):
    """Point the router at a throwaway story file and clear its caches."""
    path = tmp_path / "story_test.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(stories, "STORY_DIR", tmp_path)
    monkeypatch.setattr(stories, "STORIES", {"test": path.name})
    stories._docs.clear()
    stories._answers.clear()
    yield path
    stories._docs.clear()
    stories._answers.clear()


def test_index_summarizes_without_touching_the_occurrence_store(client, story):
    rows = client.get("/api/stories").json()
    assert [r["key"] for r in rows] == ["test"]
    assert rows[0]["n_trips"] == 2 and rows[0]["n_regions"] == 1 and rows[0]["n_species"] == 3


def test_unknown_story_is_a_404(client, story):
    assert client.get("/api/stories/nope").status_code == 404


def test_subject_resolves_to_a_collector(client, story):
    s = client.get("/api/stories/test").json()
    assert s["subject"]["collector"]["id"] is not None
    assert "呂碧鳳" in s["subject"]["collector"]["label"]


def test_trip_counts_are_the_collector_and_date_window(client, story):
    trips = client.get("/api/stories/test").json()["regions"][0]["trips"]
    assert trips[0]["n_records"] == 1   # r1, collected inside the month
    assert trips[1]["n_records"] == 0   # that day belongs to another collector
    # The transcription itself comes back untouched.
    assert trips[0]["narrative"] == "n1" and trips[0]["precision"] == "month"


def test_party_members_resolve_to_collectors_where_they_can(client, story):
    """A name that matches a collector becomes a link; a name that does not is
    kept verbatim rather than dropped — the overseas hosts hold no records here."""
    party = client.get("/api/stories/test").json()["regions"][0]["trips"][0]["party"]
    known, unknown = party[0], party[1]
    assert known["name"] == "呂碧鳳" and known["collector_id"] is not None
    assert "呂碧鳳" in known["collector_label"]
    assert unknown["name"] == "Someone"
    assert unknown["collector_id"] is None and unknown["collector_label"] is None

    totals = client.get("/api/stories/test").json()["totals"]
    assert totals["party"] == 2 and totals["party_resolved"] == 1


def test_species_counts_are_store_wide_and_absent_names_are_zero(client, story):
    species = client.get("/api/stories/test").json()["regions"][0]["species"]
    by_name = {s.get("name"): s["n_records"] for s in species}
    assert by_name["Rosa canina"] == 1        # held, though by another collector
    assert by_name["Begonia nowhere"] == 0    # described elsewhere, not held here
    assert by_name[""] == 0                   # Chinese-only name: nothing to look up


def test_focus_counts_separate_the_genus_from_the_genus_only_gap(client, story):
    s = client.get("/api/stories/test").json()
    # r1 is 'Pocillopora damicornis' by this collector — in the genus, identified.
    assert s["focus"]["records"] == 1
    assert s["focus"]["genus_only"] == 0
    assert s["totals"]["species_present"] == 1


def test_a_corrected_transcription_is_served_without_a_restart(client, story):
    assert client.get("/api/stories/test").json()["regions"][0]["name"] == "此地"
    doc = json.loads(story.read_text(encoding="utf-8"))
    doc["regions"][0]["name"] = "改過的地名"
    story.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert client.get("/api/stories/test").json()["regions"][0]["name"] == "改過的地名"


def test_a_story_associates_no_record_with_a_trip(client, story):
    """Counts only: nothing hands back the occurrence ids behind a number."""
    s = client.get("/api/stories/test").json()
    trip = s["regions"][0]["trips"][0]
    assert "occurrences" not in trip and "occurrence_ids" not in trip
    assert client.get("/api/stories/test/occurrences").status_code == 404


# ── the shipped file ────────────────────────────────────────────────────────

def test_the_begonia_transcription_parses_and_is_well_formed():
    """Guards the hand-edited file: every trip needs dates the query can use."""
    doc = json.loads((stories.STORY_DIR / "story_begonia.json").read_text(encoding="utf-8"))
    assert doc["subject"]["name"] == "彭鏡毅"
    assert doc["source"]["citation"] and doc["focus"]["genus"] == "Begonia"
    for region in doc["regions"]:
        assert region["key"] and region["name"]
        for trip in region["trips"]:
            assert trip["date_start"] <= trip["date_end"]
            assert trip["precision"] in ("day", "month")
            assert trip["narrative"].strip()
        for sp in region["species"]:
            # A species entry is worth nothing without one name or the other.
            assert sp.get("name") or sp.get("name_zh")
