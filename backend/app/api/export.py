"""Provider feedback loop: export accepted/merged annotation *deltas* for a
dataset, joined against the occurrence record, as JSON or DwC-style CSV.

Primary path uses DuckDB's ATTACHed SQLite (one federated join). Falls back to
a Python-side join if the attach is unavailable.

**An export is a snapshot of the terms, not a subscription to them.** Each row
carries the licence in force when the file was produced; a contributor who
relicenses afterwards changes what the *next* export says and nothing about the
file a provider already holds. That is the licensing rule itself — a grant
someone acted on cannot be revoked — expressed as the obvious implementation
rather than as a special case, which is why nothing here pins or versions a
licence: reading the current value is correct precisely because the delivered
file kept its own copy.
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
from ..models import LICENSE_URIS, Annotation, Identification, User

router = APIRouter(prefix="/api/export", tags=["export"])

EXPORT_COLUMNS = [
    # `tbia_id` is ours (`occurrence.id`); `occurrenceID` is the provider's own
    # DwC id, the one their system can match on — empty when they publish none.
    # The first used to ship as `occurrence_id`, which a provider would read as
    # the second and match nothing, or the wrong records, with.
    "annotation_id", "tbia_id", "occurrenceID", "catalogNumber", "scientific_name",
    "field", "original_value", "proposed_value", "status", "contributor", "reviewed_at",
    # The terms each delta is released under. Both forms: the SPDX id the
    # platform stores, and the deed URI DwC's `license` wants. A provider
    # deciding whether it may republish a value is the reason this export
    # exists at all, so it ships per row rather than as a blanket statement —
    # contributors choose per annotation, so a file can hold three of them.
    "license", "license_uri",
]


# `contributor` is the ORCID `display_name` in both query paths, and deliberately
# honours neither `users.show_in_ranking` nor `users.public_display_name` — i.e.
# not `models.public_name`. Those two decide what the *site* shows and under what
# name; this file is the hand-off to a data provider, where the name is the
# attribution the row's own licence asks for — CC-BY-4.0 and CC-BY-NC-4.0 both
# require it, the contributor picked them, and it is the ORCID-verified name that
# makes the attribution checkable against an iD.


async def _rows_federated(dataset_name: str, statuses: list[str]) -> list[dict]:
    placeholders = ", ".join(["?"] * len(statuses))
    sql = f"""
        SELECT a.id AS annotation_id, a.occurrence_id AS tbia_id,
               o.occurrence_id AS "occurrenceID", o.catalog_number AS "catalogNumber",
               o.scientific_name, a.field, a.original_value, a.proposed_value,
               a.status, u.display_name AS contributor, a.reviewed_at, a.license
        FROM ann.annotations a
        JOIN occurrence o ON o.id = a.occurrence_id
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
        rec = duck._run("SELECT catalog_number, scientific_name, occurrence_id "
                        "FROM occurrence WHERE id = ?", [a.occurrence_id])
        occ = rec[0] if rec else {}
        u = db.get(User, a.contributor_id)
        out.append({
            "annotation_id": a.id,
            "tbia_id": a.occurrence_id,
            "occurrenceID": occ.get("occurrence_id"),
            "catalogNumber": occ.get("catalog_number"),
            "scientific_name": occ.get("scientific_name"),
            "field": a.field,
            "original_value": a.original_value,
            "proposed_value": a.proposed_value,
            "status": a.status,
            "contributor": u.display_name if u else None,
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
            "license": a.license,
        })
    return out


def _with_license_uri(rows: list[dict]) -> list[dict]:
    """Resolve each row's licence id to its deed URI.

    Done here rather than in either query so the two paths — federated join and
    Python fallback — cannot disagree about what a licence id means. An id with
    no mapping gets a null URI, never a guessed one."""
    for r in rows:
        r["license_uri"] = LICENSE_URIS.get(r.get("license") or "")
    return rows


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
    rows = _with_license_uri(rows)

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


# ── Identifications ────────────────────────────────────────────────────────
# One row per determination, under DwC's own term names: a provider loads this
# into an Identification History extension, so the header should need no
# mapping table. Same snapshot rule, same attribution rule as the deltas above.
IDENT_EXPORT_COLUMNS = [
    "identification_id", "tbia_id", "occurrenceID", "catalogNumber",
    "scientificName", "taxonRank", "identificationQualifier", "verbatimIdentification",
    "identifiedBy", "identifiedByID", "dateIdentified",
    "identificationReferences", "identificationRemarks",
    "scientificNameID", "nameAccordingTo",
    "status", "contributor", "reviewed_at", "license", "license_uri",
]

# Our column -> DwC term, for the identification's own fields.
_IDENT_DWC = {
    "scientific_name": "scientificName",
    "taxon_rank": "taxonRank",
    "identification_qualifier": "identificationQualifier",
    "verbatim_identification": "verbatimIdentification",
    "identified_by": "identifiedBy",
    "identified_by_id": "identifiedByID",
    "date_identified": "dateIdentified",
    "identification_references": "identificationReferences",
    "identification_remarks": "identificationRemarks",
    "scientific_name_id": "scientificNameID",
    "name_according_to": "nameAccordingTo",
}


async def _ident_rows_federated(dataset_name: str, statuses: list[str]) -> list[dict]:
    placeholders = ", ".join(["?"] * len(statuses))
    cols = ", ".join(f'i.{c} AS "{d}"' for c, d in _IDENT_DWC.items())
    sql = f"""
        SELECT i.id AS identification_id, i.occurrence_id AS tbia_id,
               o.occurrence_id AS "occurrenceID", o.catalog_number AS "catalogNumber",
               {cols},
               i.status, u.display_name AS contributor, i.reviewed_at, i.license
        FROM ann.identifications i
        JOIN occurrence o ON o.id = i.occurrence_id
        LEFT JOIN ann.users u ON u.id = i.contributor_id
        WHERE i.dataset_name = ? AND i.status IN ({placeholders})
        ORDER BY i.reviewed_at DESC NULLS LAST, i.id DESC
    """
    return await duck.query(sql, [dataset_name, *statuses])


def _ident_rows_python(db: Session, dataset_name: str, statuses: list[str]) -> list[dict]:
    idents = db.execute(
        select(Identification).where(
            Identification.dataset_name == dataset_name,
            Identification.status.in_(statuses),
        )
    ).scalars().all()
    out = []
    for i in idents:
        rec = duck._run("SELECT catalog_number, occurrence_id FROM occurrence WHERE id = ?",
                        [i.occurrence_id])
        occ = rec[0] if rec else {}
        u = db.get(User, i.contributor_id)
        row = {
            "identification_id": i.id,
            "tbia_id": i.occurrence_id,
            "occurrenceID": occ.get("occurrence_id"),
            "catalogNumber": occ.get("catalog_number"),
            "status": i.status,
            "contributor": u.display_name if u else None,
            "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
            "license": i.license,
        }
        row.update({d: getattr(i, c) for c, d in _IDENT_DWC.items()})
        out.append(row)
    return out


@router.get("/identifications")
async def export_identifications(
    dataset_name: str,
    statuses: str = "accepted,merged",
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_session),
    user: User = Depends(auth.require_role("reviewer")),
):
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    if duck.annotations_attached():
        rows = await _ident_rows_federated(dataset_name, status_list)
    else:
        rows = _ident_rows_python(db, dataset_name, status_list)
    rows = _with_license_uri(rows)

    if format == "json":
        return {"dataset_name": dataset_name, "count": len(rows), "identifications": rows}

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=IDENT_EXPORT_COLUMNS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in IDENT_EXPORT_COLUMNS})
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tbia_identifications_export.csv"'},
    )
