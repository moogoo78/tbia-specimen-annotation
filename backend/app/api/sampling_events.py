"""The curated sampling-event chronology.

The *upper* trip layer: documented collecting events transcribed from published
literature, as opposed to the trips `api/collectors.py` derives by sessionizing a
collector's occurrence dates. The chronology asserts no link to any occurrence
row (see the change's proposal -- Non-Goals): nothing here is stored against a
specimen, and the two endpoints that serve the events themselves read SQLite
only. Any pairing a page shows rests on collector identity plus date overlap,
and is presented as context, never as provenance.

The one exception is `/sampling-events/counts`, which *queries* DuckDB for how
many records each event's collectors hold within its years -- see its docstring
for why a live count is still not an association.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from .. import duck
from ..db import SessionLocal
from ..models import Collector, CollectorAlias, SamplingEvent, SamplingEventActor

router = APIRouter(prefix="/api", tags=["sampling-events"])


def _serialize(ev: SamplingEvent, labels: dict[int, dict]) -> dict:
    return {
        "id": ev.id,
        "event_date": ev.event_date,
        "verbatim_event_date": ev.verbatim_event_date,
        "year_start": ev.year_start,
        "year_end": ev.year_end,
        "verbatim_locality": ev.verbatim_locality,
        "event_remarks": ev.event_remarks,
        "location_according_to": ev.location_according_to,
        "narrative": ev.narrative,
        "source_page": ev.source_page,
        "seq": ev.seq,
        "actors": [
            {
                "recorded_by": a.recorded_by,
                "nationality": a.nationality,
                "position": a.position,
                "collector_id": a.collector_id,
                # Null for an unresolved actor -- the UI renders those as plain
                # text rather than a dead link.
                "collector_label": labels.get(a.collector_id or -1, {}).get("label"),
            }
            for a in ev.actors
        ],
    }


def _labels(db, events: list[SamplingEvent]) -> dict[int, dict]:
    """Collector id -> display label, for the actors that resolved."""
    ids = {a.collector_id for ev in events for a in ev.actors if a.collector_id}
    if not ids:
        return {}
    out: dict[int, dict] = {}
    for c in db.execute(select(Collector).where(Collector.id.in_(ids))).scalars():
        out[c.id] = {"label": " ".join(p for p in (c.name, c.name_en) if p)}
    return out


@router.get("/sampling-events")
def list_sampling_events(
    q: str | None = Query(default=None, description="substring match on names / locality / repository / narrative"),
    year_from: int | None = Query(default=None, description="events overlapping this range"),
    year_to: int | None = None,
    collector_id: int | None = Query(default=None, description="only events naming this collector"),
    limit: int = Query(default=200, le=500),
    offset: int = 0,
):
    """The chronology, earliest first."""
    with SessionLocal() as db:
        stmt = select(SamplingEvent).options(selectinload(SamplingEvent.actors))

        # Overlap, not containment: an event running 1861-1866 must surface for a
        # 1864-1870 window even though it starts before it.
        if year_from is not None:
            stmt = stmt.where(SamplingEvent.year_end >= year_from)
        if year_to is not None:
            stmt = stmt.where(SamplingEvent.year_start <= year_to)

        if collector_id is not None:
            stmt = stmt.where(
                SamplingEvent.id.in_(
                    select(SamplingEventActor.event_id).where(
                        SamplingEventActor.collector_id == collector_id
                    )
                )
            )

        if q and q.strip():
            # Substring/ILIKE, matching the rest of the platform -- there is no
            # CJK tokenizer anywhere in this codebase.
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    SamplingEvent.verbatim_locality.ilike(like),
                    SamplingEvent.event_remarks.ilike(like),
                    SamplingEvent.narrative.ilike(like),
                    SamplingEvent.id.in_(
                        select(SamplingEventActor.event_id).where(
                            SamplingEventActor.recorded_by.ilike(like)
                        )
                    ),
                )
            )

        stmt = (
            stmt.order_by(SamplingEvent.year_start, SamplingEvent.seq)
            .limit(limit)
            .offset(offset)
        )
        events = list(db.execute(stmt).scalars().unique())
        labels = _labels(db, events)
        return [_serialize(ev, labels) for ev in events]


# ── specimen counts ─────────────────────────────────────────────────────────
#
# How many occurrence rows each event's collectors hold within its years. This
# is a *query* over two things the source does state -- who collected, and when
# -- run so the UI can label its link and drop it when the answer is zero. It
# still associates nothing: no row is written, an occurrence in the count may
# well have come from other fieldwork the same person did those years, and the
# page says so. Keep it out of the export path.

_COUNTS: dict | None = None       # {"key": pairs signature, "at": monotonic, "counts": {...}}
_COUNTS_TTL = 600.0
_counts_lock = asyncio.Lock()


def _event_collector_years() -> list[tuple[int, int, int, int]]:
    """(event_id, collector_id, year_start, year_end) for every resolved actor.

    Deduplicated: an event that names the same collector twice must not count
    its records twice.
    """
    with SessionLocal() as db:
        rows = db.execute(
            select(
                SamplingEventActor.event_id,
                SamplingEventActor.collector_id,
                SamplingEvent.year_start,
                SamplingEvent.year_end,
            )
            .join(SamplingEvent, SamplingEvent.id == SamplingEventActor.event_id)
            .where(SamplingEventActor.collector_id.is_not(None))
        ).all()
    return sorted({(int(e), int(c), int(y0), int(y1)) for e, c, y0, y1 in rows})


async def _count_by_event(pairs: list[tuple[int, int, int, int]]) -> dict[int, int]:
    """One scan: every event's records in a single grouped join."""
    if not pairs:
        return {}

    values = ", ".join(["(?, ?, ?, ?)"] * len(pairs))
    params: list = [v for pair in pairs for v in pair]

    if duck.annotations_attached():
        rows = await duck.query(
            f"""WITH ev(event_id, collector_id, y0, y1) AS (VALUES {values})
                SELECT ev.event_id AS event_id, count(*) AS n
                FROM occurrence o
                JOIN ann.collector_alias a ON a.recorded_by = o.recorded_by
                JOIN ev ON ev.collector_id = a.collector_id
                       AND o.year BETWEEN ev.y0 AND ev.y1
                GROUP BY ev.event_id""",
            params,
        )
        return {int(r["event_id"]): int(r["n"]) for r in rows}

    # No ATTACH: bring the alias map over from SQLite and join on the raw string,
    # exactly as `search._collector_clause` and `collectors._occurrence_rollup` do.
    with SessionLocal() as db:
        aliases = db.execute(
            select(CollectorAlias.collector_id, CollectorAlias.recorded_by).where(
                CollectorAlias.collector_id.in_({c for _, c, _, _ in pairs})
            )
        ).all()
    if not aliases:
        return {}
    alias_values = ", ".join(["(?, ?)"] * len(aliases))
    alias_params: list = [v for cid, name in aliases for v in (int(cid), name)]
    rows = await duck.query(
        f"""WITH ev(event_id, collector_id, y0, y1) AS (VALUES {values}),
                 al(collector_id, recorded_by) AS (VALUES {alias_values})
            SELECT ev.event_id AS event_id, count(*) AS n
            FROM occurrence o
            JOIN al ON al.recorded_by = o.recorded_by
            JOIN ev ON ev.collector_id = al.collector_id
                   AND o.year BETWEEN ev.y0 AND ev.y1
            GROUP BY ev.event_id""",
        params + alias_params,
    )
    return {int(r["event_id"]): int(r["n"]) for r in rows}


@router.get("/sampling-events/counts")
async def sampling_event_counts() -> dict[str, int]:
    """Records held by each event's collectors within its years, keyed by event id.

    Every event is present, zeros included, so a caller can tell "none" apart
    from "not loaded yet". Cached on the actor/year signature, so a re-seed after
    a transcription fix is reflected at once while repeat page loads are free.
    """
    global _COUNTS
    pairs = _event_collector_years()
    key = tuple(pairs)

    async with _counts_lock:
        cached = _COUNTS
        if (
            cached is not None
            and cached["key"] == key
            and time.monotonic() - cached["at"] < _COUNTS_TTL
        ):
            counts = cached["counts"]
        else:
            counts = await _count_by_event(pairs)
            _COUNTS = {"key": key, "at": time.monotonic(), "counts": counts}

    with SessionLocal() as db:
        ids = db.execute(select(SamplingEvent.id)).scalars().all()
    return {str(i): counts.get(i, 0) for i in ids}


@router.get("/sampling-events/{event_id}")
def get_sampling_event(event_id: int):
    with SessionLocal() as db:
        ev = db.execute(
            select(SamplingEvent)
            .options(selectinload(SamplingEvent.actors))
            .where(SamplingEvent.id == event_id)
        ).scalar_one_or_none()
        if ev is None:
            raise HTTPException(status_code=404, detail="Sampling event not found")
        return _serialize(ev, _labels(db, [ev]))
