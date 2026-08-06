"""Collector dropdown + lookup, backed by the SQLite collector tables."""

from __future__ import annotations

import asyncio
import random
import time

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from .. import duck
from ..db import SessionLocal
from ..models import Collector, CollectorAlias

router = APIRouter(prefix="/api", tags=["collectors"])


def _label(c: Collector) -> str:
    return " ".join(p for p in (c.name, c.name_en) if p)


@router.get("/collectors")
def list_collectors(
    q: str | None = Query(default=None, description="substring match on name / name_en"),
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    """Collectors for the dropdown, most-prolific first."""
    with SessionLocal() as db:
        stmt = select(Collector)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Collector.name.ilike(like), Collector.name_en.ilike(like)))
        stmt = (
            stmt.order_by(Collector.n_records.desc(), Collector.name)
            .limit(limit)
            .offset(offset)
        )
        return [
            {
                "id": c.id,
                "name": c.name,
                "name_en": c.name_en,
                "label": _label(c),
                "n_records": c.n_records,
            }
            for c in db.execute(stmt).scalars()
        ]


@router.get("/collectors/resolve")
def resolve_collector(recorded_by: str):
    """The collector a raw ``recorded_by`` value maps to, or null if unmapped
    (organization / unknown). Used to make the record-detail collector clickable."""
    with SessionLocal() as db:
        alias = db.get(CollectorAlias, recorded_by)
        if alias is None:
            return None
        c = db.get(Collector, alias.collector_id)
        if c is None:
            return None
        return {
            "id": c.id,
            "name": c.name,
            "name_en": c.name_en,
            "label": _label(c),
            "n_records": c.n_records,
        }


# ── the board ───────────────────────────────────────────────────────────────
#
# Coordinate coverage and year span live in DuckDB, names and aliases in SQLite.
# Rolling up all ~17k collectors at once is a single 0.2s scan, so the board
# sorts on any column with no per-page query and no precomputed table. Cached
# with a TTL so a `make sync-collectors` lands without a restart.

_BOARD: list[dict] | None = None
_BOARD_AT = 0.0
_BOARD_TTL = 600.0
_board_lock = asyncio.Lock()

BOARD_SORTS = ("records", "gap", "recent", "random")


async def _occurrence_rollup() -> dict[int, dict]:
    """Per-collector record / georeferenced / year-span counts, keyed by id."""
    if duck.annotations_attached():
        rows = await duck.query(
            """SELECT a.collector_id AS id, count(*) AS n_records,
                      count(*) FILTER (WHERE o.has_coordinates) AS n_geo,
                      min(o.year) AS year_min, max(o.year) AS year_max
               FROM occurrence o JOIN ann.collector_alias a ON a.recorded_by = o.recorded_by
               GROUP BY a.collector_id"""
        )
        return {r["id"]: r for r in rows}

    # No ATTACH: roll up by the raw string instead, then fold in the alias map.
    raw = await duck.query(
        """SELECT recorded_by, count(*) AS n_records,
                  count(*) FILTER (WHERE has_coordinates) AS n_geo,
                  min(year) AS year_min, max(year) AS year_max
           FROM occurrence WHERE recorded_by IS NOT NULL GROUP BY recorded_by"""
    )
    by_raw = {r["recorded_by"]: r for r in raw}
    out: dict[int, dict] = {}
    with SessionLocal() as db:
        aliases = db.execute(
            select(CollectorAlias.collector_id, CollectorAlias.recorded_by)
        ).all()
    for cid, recorded_by in aliases:
        r = by_raw.get(recorded_by)
        if r is None:
            continue
        acc = out.setdefault(
            cid, {"id": cid, "n_records": 0, "n_geo": 0, "year_min": None, "year_max": None}
        )
        acc["n_records"] += r["n_records"]
        acc["n_geo"] += r["n_geo"]
        for key, pick in (("year_min", min), ("year_max", max)):
            if r[key] is not None:
                acc[key] = r[key] if acc[key] is None else pick(acc[key], r[key])
    return out


async def _board_rows() -> list[dict]:
    """Every collector with its counts, names and alias count. Cached."""
    global _BOARD, _BOARD_AT
    async with _board_lock:
        if _BOARD is not None and time.monotonic() - _BOARD_AT < _BOARD_TTL:
            return _BOARD

        stats = await _occurrence_rollup()
        with SessionLocal() as db:
            collectors = db.execute(
                select(Collector.id, Collector.name, Collector.name_en, Collector.n_records)
            ).all()
            n_aliases = dict(
                db.execute(
                    select(CollectorAlias.collector_id, func.count())
                    .group_by(CollectorAlias.collector_id)
                ).all()
            )

        rows = []
        for cid, name, name_en, seeded in collectors:
            s = stats.get(cid) or {}
            # The rollup is authoritative — the seeded count can predate a
            # refresh — but keep it as the floor when a collector is missing
            # from the store entirely.
            n_records = s.get("n_records") or seeded or 0
            n_geo = s.get("n_geo") or 0
            rows.append({
                "id": cid,
                "name": name or "",
                "name_en": name_en or "",
                "label": " ".join(p for p in (name, name_en) if p),
                "n_records": n_records,
                "n_geo": n_geo,
                "n_unmapped": n_records - n_geo,
                "mapped_pct": round(100.0 * n_geo / n_records, 1) if n_records else 0.0,
                "year_min": s.get("year_min"),
                "year_max": s.get("year_max"),
                "n_aliases": n_aliases.get(cid, 0),
            })
        _BOARD, _BOARD_AT = rows, time.monotonic()
        return rows


@router.get("/collectors/board")
async def collector_board(
    q: str | None = Query(default=None, description="substring match on name / name_en"),
    sort: str = Query(default="records", description=" | ".join(BOARD_SORTS)),
    min_records: int = Query(default=10, ge=1, description="hide the one-record tail"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Browsable index of every collector, with their coordinate gap.

    ``sort=gap`` puts whoever has the most records *without* coordinates first,
    which is the georeferencing queue by person. ``sort=random`` samples the
    same filtered pool instead, so the page can show someone other than the
    same 50 names every visit (``offset`` is ignored — a random page has no
    stable order to page through).
    """
    if sort not in BOARD_SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {BOARD_SORTS}")

    rows = await _board_rows()
    totals = {
        "collectors": len(rows),
        "records": sum(r["n_records"] for r in rows),
        "mapped": sum(r["n_geo"] for r in rows),
    }

    pool = [r for r in rows if r["n_records"] >= min_records]
    if q and q.strip():
        needle = q.strip().lower()
        pool = [r for r in pool if needle in r["name"].lower() or needle in r["name_en"].lower()]

    if sort == "random":
        items = random.sample(pool, min(limit, len(pool)))
        offset = 0
    else:
        if sort == "gap":
            pool.sort(key=lambda r: (-r["n_unmapped"], -r["n_records"]))
        elif sort == "recent":
            pool.sort(key=lambda r: (-(r["year_max"] or -9999), -r["n_records"]))
        else:
            pool.sort(key=lambda r: (-r["n_records"], r["label"]))
        items = pool[offset:offset + limit]

    return {"total": len(pool), "items": items, "limit": limit, "offset": offset,
            "totals": totals}


@router.get("/collectors/{collector_id}")
def get_collector(collector_id: int):
    """A collector plus its raw ``recorded_by`` aliases (use these to filter
    occurrences: ``WHERE recorded_by IN (aliases)``)."""
    with SessionLocal() as db:
        c = db.get(Collector, collector_id)
        if c is None:
            raise HTTPException(status_code=404, detail="Collector not found")
        aliases = db.execute(
            select(CollectorAlias.recorded_by).where(
                CollectorAlias.collector_id == collector_id
            )
        ).scalars().all()
        return {
            "id": c.id,
            "name": c.name,
            "name_en": c.name_en,
            "label": _label(c),
            "n_records": c.n_records,
            "verified": c.verified,
            "aliases": aliases,
        }


def _career_source(collector_id: int) -> tuple[str, list]:
    """(FROM/WHERE fragment, params) selecting this collector's occurrences.

    Prefers the ATTACHed sqlite so the alias join happens inside DuckDB; falls
    back to inlining the raw strings, exactly as ``search._collector_clause``.
    """
    if duck.annotations_attached():
        return (
            "FROM occurrence o JOIN ann.collector_alias a ON a.recorded_by = o.recorded_by "
            "WHERE a.collector_id = ?",
            [collector_id],
        )
    with SessionLocal() as db:
        aliases = list(db.execute(
            select(CollectorAlias.recorded_by).where(
                CollectorAlias.collector_id == collector_id
            )
        ).scalars())
    if not aliases:
        return "FROM occurrence o WHERE FALSE", []
    ph = ", ".join(["?"] * len(aliases))
    return f"FROM occurrence o WHERE o.recorded_by IN ({ph})", aliases


def trips_sql(src: str) -> str:
    """Sessionize a collector's dated records into trips.

    Break the ordered distinct collecting days wherever more than ``?`` idle days
    separate two of them; a running sum over those breaks numbers the trips. The
    gap is the last parameter, after whatever ``src`` binds.

    Kept as a function so tests can run the real query against synthetic dates.
    """
    return f"""
        WITH rec AS (
          SELECT CAST(o.standard_date AS DATE) AS d, o.county, o.locality, o.has_coordinates
          {src} AND o.standard_date IS NOT NULL
        ),
        days AS (SELECT DISTINCT d FROM rec),
        gaps AS (
          SELECT d, CASE WHEN date_diff('day', lag(d) OVER (ORDER BY d), d) > ?
                         THEN 1 ELSE 0 END AS brk
          FROM days
        ),
        trip AS (SELECT d, sum(brk) OVER (ORDER BY d) AS trip_id FROM gaps)
        SELECT min(r.d) AS start, max(r.d) AS "end",
               count(DISTINCT r.d) AS n_days, count(*) AS n_records,
               count(*) FILTER (WHERE r.has_coordinates) AS n_mapped,
               -- county is empty for most collectors; locality is ~99% present.
               coalesce(
                 mode(r.county)   FILTER (WHERE r.county   IS NOT NULL AND r.county   <> ''),
                 mode(r.locality) FILTER (WHERE r.locality IS NOT NULL AND r.locality <> '')
               ) AS place
        FROM rec r JOIN trip t ON t.d = r.d
        GROUP BY t.trip_id ORDER BY start
    """


@router.get("/collectors/{collector_id}/career")
async def collector_career(collector_id: int, gap: int = Query(default=7, ge=1, le=365)):
    """A collector's lifetime of work: totals, plus their collecting trips.

    A *trip* is a run of collecting days separated by more than ``gap`` idle days
    — dates are the one field that is nearly always present (98.7% of records),
    whereas coordinates usually are not, so the trip list is what carries this
    view and the map reports the gap.

    Undated records cannot belong to a trip; they stay in ``summary`` as
    ``n_undated`` rather than disappearing.
    """
    with SessionLocal() as db:
        c = db.get(Collector, collector_id)
        if c is None:
            raise HTTPException(status_code=404, detail="Collector not found")
        collector = {"id": c.id, "name": c.name, "name_en": c.name_en, "label": _label(c)}

    src, params = _career_source(collector_id)

    summary = await duck.query_one(
        f"""SELECT count(*) AS n_records,
                   count(*) FILTER (WHERE o.has_date) AS n_dated,
                   count(*) FILTER (WHERE o.has_coordinates) AS n_geo,
                   count(DISTINCT CAST(o.standard_date AS DATE)) AS n_days,
                   min(o.year) AS year_min, max(o.year) AS year_max
            {src}""",
        params,
    ) or {}
    summary["n_undated"] = (summary.get("n_records") or 0) - (summary.get("n_dated") or 0)

    # Per-year counts for the timeline. Cheap, and present even when no record
    # has coordinates.
    years = await duck.query(
        f"""SELECT o.year AS year, count(*) AS count,
                   count(*) FILTER (WHERE o.has_coordinates) AS mapped
            {src} AND o.year IS NOT NULL GROUP BY o.year ORDER BY o.year""",
        params,
    )

    trips = await duck.query(trips_sql(src), [*params, gap])

    summary["n_trips"] = len(trips)
    # Echo the threshold: the page states the rule, and it must state the one
    # actually used rather than assume the default.
    return {"collector": collector, "gap": gap, "summary": summary,
            "years": years, "trips": trips}
