"""Provider feedback loop: export accepted/merged annotation *deltas* for a
dataset, joined against the occurrence record, as JSON or DwC-style CSV.

Primary path uses DuckDB's ATTACHed SQLite (one federated join). Falls back to
a Python-side join if the attach is unavailable.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, duck
from ..db import get_session
from ..models import Annotation, User

router = APIRouter(prefix="/api/export", tags=["export"])

EXPORT_COLUMNS = [
    "annotation_id", "occurrence_id", "catalog_number", "scientific_name",
    "field", "original_value", "proposed_value", "status", "contributor", "reviewed_at",
]


async def _rows_federated(dataset_name: str, statuses: list[str]) -> list[dict]:
    placeholders = ", ".join(["?"] * len(statuses))
    sql = f"""
        SELECT a.id AS annotation_id, a.occurrence_id, o.catalog_number,
               o.scientific_name, a.field, a.original_value, a.proposed_value,
               a.status, u.display_name AS contributor, a.reviewed_at
        FROM ann.annotations a
        JOIN occurrences o ON o.id = a.occurrence_id
        LEFT JOIN ann.users u ON u.id = a.contributor_id
        WHERE a.dataset_name = ? AND a.status IN ({placeholders})
        ORDER BY a.reviewed_at DESC NULLS LAST, a.id DESC
    """
    return await duck.query(sql, [dataset_name, *statuses])


def _rows_python(db: Session, dataset_name: str, statuses: list[str]) -> list[dict]:
    anns = db.execute(
        select(Annotation).where(
            Annotation.dataset_name == dataset_name,
            Annotation.status.in_(statuses),
        )
    ).scalars().all()
    out = []
    for a in anns:
        occ = None
        # one-by-one detail lookups are fine here (export is low-volume)
        rec = duck._run("SELECT catalog_number, scientific_name FROM occurrences WHERE id = ?",
                        [a.occurrence_id])
        occ = rec[0] if rec else {}
        u = db.get(User, a.contributor_id)
        out.append({
            "annotation_id": a.id,
            "occurrence_id": a.occurrence_id,
            "catalog_number": occ.get("catalog_number"),
            "scientific_name": occ.get("scientific_name"),
            "field": a.field,
            "original_value": a.original_value,
            "proposed_value": a.proposed_value,
            "status": a.status,
            "contributor": u.display_name if u else None,
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        })
    return out


@router.get("/provider")
async def export_provider(
    dataset_name: str,
    statuses: str = "accepted,merged",
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_session),
    user: User = Depends(auth.require_role("reviewer")),
):
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    if duck.annotations_attached():
        rows = await _rows_federated(dataset_name, status_list)
    else:
        rows = _rows_python(db, dataset_name, status_list)

    if format == "json":
        return {"dataset_name": dataset_name, "count": len(rows), "deltas": rows}

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in EXPORT_COLUMNS})
    buf.seek(0)
    filename = "tbia_annotations_export.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
