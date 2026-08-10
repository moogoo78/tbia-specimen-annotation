"""The curated sampling-event chronology.

The *upper* trip layer: documented collecting events transcribed from published
literature, as opposed to the trips `api/collectors.py` derives by sessionizing a
collector's occurrence dates. Pure SQLite -- there is no DuckDB join here,
because the chronology asserts no link to any occurrence row (see the change's
proposal -- Non-Goals). Any pairing a page shows rests on collector identity plus
date overlap, and is presented as context, never as provenance.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..db import SessionLocal
from ..models import Collector, SamplingEvent, SamplingEventActor

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
