"""Curated story topics: narrative transcriptions, answered against the store.

A story is a hand-curated JSON file under ``data/`` -- prose, dates and names
taken from a published source -- served back with the numbers the occurrence
store can supply for it: how many records the subject collected during each
documented trip, and how many of each species he described are held here.

Nothing is seeded and no table is written. Unlike the sampling-event chronology
(``api/sampling_events.py``), a story needs no identity resolution beyond its
subject, so the file is read at request time and cached on its mtime -- correct
a transcription and the next request serves it.

The same rule as the chronology applies: **a count is not provenance.** Records
are matched by collector and date window, so a specimen counted under a trip is
one that person collected in those days; the story does not claim the trip
produced it, and nothing links a row to a story.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

from .. import duck
from ..db import RefSessionLocal
from ..models import Collector, CollectorAlias
from ..names import collector_index, fold

router = APIRouter(prefix="/api", tags=["stories"])

# repo root: backend/app/api/stories.py -> app -> backend -> repo
STORY_DIR = Path(__file__).resolve().parents[3] / "data"
STORIES = {"begonia": "story_begonia.json"}

_docs: dict[str, tuple[float, dict]] = {}      # key -> (mtime, parsed)
_answers: dict[str, tuple[float, float, dict]] = {}   # key -> (mtime, at, counts)
_ANSWER_TTL = 600.0
_lock = asyncio.Lock()


def _load(key: str) -> dict:
    """Parse the story file, re-reading only when it changes on disk."""
    path = STORY_DIR / STORIES[key]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Story file missing: {path.name}")
    mtime = path.stat().st_mtime
    cached = _docs.get(key)
    if cached is None or cached[0] != mtime:
        _docs[key] = (mtime, json.loads(path.read_text(encoding="utf-8")))
    return _docs[key][1]


def _label(c: Collector) -> str:
    return " ".join(p for p in (c.name, c.name_en) if p)


def _subject(doc: dict) -> dict | None:
    """The story's collector, resolved against the collector table."""
    s = doc.get("subject") or {}
    names = [n for n in (s.get("name"), s.get("name_en")) if n]
    if not names:
        return None
    with RefSessionLocal() as db:
        c = db.execute(
            select(Collector).where(
                or_(Collector.name.in_(names), Collector.name_en.in_(names))
            )
        ).scalars().first()
        if c is None:
            return None
        aliases = db.execute(
            select(CollectorAlias.recorded_by).where(CollectorAlias.collector_id == c.id)
        ).scalars().all()
    return {
        "id": c.id,
        "name": c.name,
        "name_en": c.name_en,
        "label": _label(c),
        "n_records": c.n_records,
        "aliases": list(aliases),
    }


def _resolve_party(doc: dict) -> dict[str, dict | None]:
    """Every party member named anywhere in the story -> their collector, or None.

    Same conservative matching as the chronology's actors (``app/names.py``): a
    fold of spacing and punctuation, nothing fuzzier. A miss is expected and
    kept — several of these are overseas hosts and students who hold no records
    in a Taiwanese aggregation — and the UI renders it as plain text.
    """
    wanted: dict[str, list[str]] = {}
    for region in doc.get("regions", []):
        for trip in region.get("trips", []):
            for m in trip.get("party", []) or []:
                names = [n for n in (m.get("name"), m.get("name_en")) if n]
                if names:
                    wanted[m["name"]] = names
    if not wanted:
        return {}

    out: dict[str, dict | None] = {}
    with RefSessionLocal() as db:
        index = collector_index(db)
        ids = {}
        for key, names in wanted.items():
            cid = next((index[k] for k in map(fold, names) if k in index), None)
            ids[key] = cid
        found = {
            c.id: {"collector_id": c.id, "collector_label": _label(c)}
            for c in db.execute(
                select(Collector).where(Collector.id.in_({i for i in ids.values() if i}))
            ).scalars()
        }
    for key, cid in ids.items():
        out[key] = found.get(cid) if cid else None
    return out


def _trips(doc: dict) -> list[tuple[str, str, str, str]]:
    """(region key, trip seq, date_start, date_end) for every dated trip."""
    out = []
    for region in doc.get("regions", []):
        for trip in region.get("trips", []):
            if trip.get("date_start") and trip.get("date_end"):
                out.append((region["key"], str(trip["seq"]),
                            trip["date_start"], trip["date_end"]))
    return out


def _species(doc: dict) -> list[str]:
    """Every binomial the story names. Entries with no Latin name are skipped —
    the source gives some species only a Chinese name, and a name we do not have
    cannot be looked up."""
    return sorted({
        s["name"] for region in doc.get("regions", [])
        for s in region.get("species", []) if s.get("name")
    })


def _collector_source(collector_id: int) -> tuple[str, list[Any]]:
    """FROM/WHERE selecting the subject's occurrences, ATTACH or not.

    Mirrors ``collectors._career_source`` — the alias join belongs in DuckDB when
    the sqlite is attached, and is inlined as raw strings when it is not.
    """
    if duck.reference_attached():
        return (
            "FROM occurrence o JOIN ref.collector_alias a ON a.recorded_by = o.recorded_by "
            "WHERE a.collector_id = ?",
            [collector_id],
        )
    with RefSessionLocal() as db:
        aliases = list(db.execute(
            select(CollectorAlias.recorded_by).where(
                CollectorAlias.collector_id == collector_id
            )
        ).scalars())
    if not aliases:
        return "FROM occurrence o WHERE FALSE", []
    ph = ", ".join(["?"] * len(aliases))
    return f"FROM occurrence o WHERE o.recorded_by IN ({ph})", aliases


async def _trip_counts(collector_id: int, trips: list[tuple[str, str, str, str]]) -> dict[str, int]:
    """Records the subject collected inside each trip's dates, keyed 'region/seq'."""
    if not trips:
        return {}
    src, params = _collector_source(collector_id)
    values = ", ".join(["(?, ?, ?)"] * len(trips))
    binds = [v for (rk, seq, d0, d1) in trips for v in (f"{rk}/{seq}", d0, d1)]
    rows = await duck.query(
        f"""WITH tr(key, d0, d1) AS (VALUES {values}),
                 rec AS (SELECT CAST(o.standard_date AS DATE) AS d {src}
                          AND o.standard_date IS NOT NULL)
            SELECT tr.key AS key, count(*) AS n
            FROM rec JOIN tr ON rec.d BETWEEN CAST(tr.d0 AS DATE) AND CAST(tr.d1 AS DATE)
            GROUP BY tr.key""",
        binds + params,
    )
    return {r["key"]: int(r["n"]) for r in rows}


async def _species_counts(names: list[str]) -> dict[str, int]:
    """Records held for each named species, anywhere in the store.

    Matched on the binomial itself or on a name that starts with it, so an
    infraspecific or an authorship-carrying value still counts. Scoped to the
    genus first — that is 5.8k rows out of 1.9M, so the per-name LIKE join is
    cheap.
    """
    if not names:
        return {}
    genera = sorted({n.split(" ")[0] for n in names})
    gph = " OR ".join(["o.scientific_name LIKE ? || ' %'"] * len(genera))
    values = ", ".join(["(?)"] * len(names))
    rows = await duck.query(
        f"""WITH sp(name) AS (VALUES {values}),
                 g AS (SELECT scientific_name FROM occurrence o WHERE {gph})
            SELECT sp.name AS name, count(*) AS n
            FROM g JOIN sp ON g.scientific_name = sp.name
                            OR g.scientific_name LIKE sp.name || ' %'
            GROUP BY sp.name""",
        list(names) + genera,
    )
    return {r["name"]: int(r["n"]) for r in rows}


async def _focus_counts(collector_id: int, genus: str) -> dict[str, int]:
    """The subject's holdings in the story's genus, and how many stop at it.

    ``genus_only`` is the platform's own subject matter showing up inside the
    story: a specimen filed as bare "Begonia" is one of the identification gaps
    /explore exists to close.
    """
    src, params = _collector_source(collector_id)
    row = await duck.query_one(
        f"""SELECT count(*) FILTER (WHERE o.scientific_name = ?
                                       OR o.scientific_name LIKE ? || ' %') AS n_records,
                   count(*) FILTER (WHERE o.scientific_name = ?) AS n_genus_only
            {src}""",
        [genus, genus, genus] + params,
    )
    return {"records": int(row["n_records"]), "genus_only": int(row["n_genus_only"])}


@router.get("/stories")
def list_stories() -> list[dict]:
    """The story index. Cheap — no occurrence query runs here."""
    out = []
    for key in STORIES:
        doc = _load(key)
        regions = doc.get("regions", [])
        out.append({
            "key": key,
            "title": doc.get("source", {}).get("title", key),
            "subject": doc.get("subject", {}),
            "n_regions": len(regions),
            "n_trips": sum(len(r.get("trips", [])) for r in regions),
            "n_species": sum(len(r.get("species", [])) for r in regions),
        })
    return out


@router.get("/stories/{key}")
async def get_story(key: str) -> dict:
    """The transcription, plus what the store holds for it.

    ``trips[].n_records`` counts by collector and date window; ``species[].n_records``
    by name. Both are joins run at request time, not stored associations.
    """
    if key not in STORIES:
        raise HTTPException(status_code=404, detail="Unknown story")
    doc = _load(key)
    subject = _subject(doc)

    mtime = (STORY_DIR / STORIES[key]).stat().st_mtime
    async with _lock:
        cached = _answers.get(key)
        if cached and cached[0] == mtime and time.monotonic() - cached[1] < _ANSWER_TTL:
            answers = cached[2]
        else:
            trips = await _trip_counts(subject["id"], _trips(doc)) if subject else {}
            species = await _species_counts(_species(doc))
            genus = (doc.get("focus") or {}).get("genus")
            focus = (
                await _focus_counts(subject["id"], genus)
                if subject and genus else {"records": 0, "genus_only": 0}
            )
            answers = {"trips": trips, "species": species, "focus": focus}
            _answers[key] = (mtime, time.monotonic(), answers)

    party = _resolve_party(doc)
    regions = []
    for region in doc.get("regions", []):
        r = dict(region)
        r["trips"] = [
            {
                **trip,
                "n_records": answers["trips"].get(f"{region['key']}/{trip['seq']}", 0),
                "party": [
                    {**m, "collector_id": None, "collector_label": None,
                     **(party.get(m.get("name")) or {})}
                    for m in trip.get("party", []) or []
                ],
            }
            for trip in region.get("trips", [])
        ]
        r["species"] = [
            {**s, "n_records": answers["species"].get(s.get("name", ""), 0)}
            for s in region.get("species", [])
        ]
        regions.append(r)

    return {
        "key": key,
        "source": doc.get("source", {}),
        "subject": {**doc.get("subject", {}), "collector": subject},
        "focus": {**(doc.get("focus") or {}), **answers["focus"]},
        "regions": regions,
        "totals": {
            "regions": len(regions),
            "trips": sum(len(r["trips"]) for r in regions),
            "species": sum(len(r["species"]) for r in regions),
            "trip_records": sum(answers["trips"].values()),
            "species_records": sum(answers["species"].values()),
            # Species the store holds under a name the story names.
            "species_present": sum(1 for v in answers["species"].values() if v),
            "party": len(party),
            "party_resolved": sum(1 for v in party.values() if v),
        },
    }
