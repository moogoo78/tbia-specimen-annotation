"""Collector dropdown + lookup, backed by the SQLite collector tables."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

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
    return {"collector": collector, "summary": summary, "years": years, "trips": trips}
