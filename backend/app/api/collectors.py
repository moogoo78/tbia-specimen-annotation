"""Collector dropdown + lookup, backed by the SQLite collector tables."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

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
