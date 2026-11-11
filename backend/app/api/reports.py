"""Per-institution annotation report — what a data provider reads to see what
the community has done to its records, and where a reviewer works through it.

**An institution is a registry code, and annotations do not know it.** A row in
`annotations` carries `occurrence_id` + `dataset_name`; the institution is
`registry.json` code → `tbia_dataset_id`s (`occurrences.load_registry`, the same
resolution `/api/registry` serves, curated and discovered alike). So the
grouping goes through the occurrence store: one federated
`ann.annotations JOIN occurrence ON tbia_dataset_id IN (…)` when the SQLite file
is attached, else the annotation rows from SQLite and one bounded
`occurrence WHERE id IN (…)` lookup. Both paths produce the same flat rows and
everything after that — counts, the field × status matrix, the record list — is
computed once, in Python, from those rows, so the two cannot disagree.

**Public, so it publishes nothing a record page would not.** Drafts are excluded
(private working state, CLAUDE.md), and contributor names go through
`models.public_name` server-side: `contributor_name: null` is "not for
publication", never "no contributor". The per-record detail is not here — the
page reads `GET /api/occurrences/{id}`, which already carries the images and the
annotation history, so there is one definition of "a record with its
annotations". Review actions are the existing `PATCH /api/annotations/{id}`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from .. import auth, duck
from ..db import SessionLocal
from ..models import LICENSE_URIS, STATUSES, Annotation, User, public_name
from ..search import parse_media
from .occurrences import load_registry

router = APIRouter(prefix="/api/reports", tags=["reports"])

SECTIONS = ("institutions", "aggregators")
# Everything a report may show: all statuses but the private one.
REPORT_STATUSES = tuple(s for s in STATUSES if s != "draft")

_OCC_COLS = ("tbia_dataset_id", "dataset_name", "catalog_number", "scientific_name",
             "associated_media")
# The provider's own DwC occurrenceID. Aliased because `occurrence_id` on an
# annotation row is *our* record id (`occurrence.id`) — the name every view here
# groups by — and the two must not collide in a flat row.
_SOURCE_ID = "occurrence_id AS source_occurrence_id"
# Carried for the export; the public views build their payloads field by field
# and never pass these through.
_ANN_EXTRA = ("original_value", "proposed_value", "reviewed_at", "license")


# ── which datasets an institution is ────────────────────────────────────────

def _sources(reg: dict) -> list[dict[str, Any]]:
    out = []
    for kind in SECTIONS:
        for code, ent in (reg.get(kind) or {}).items():
            out.append({"kind": kind, "code": code, "name": ent.get("name") or code,
                        "datasets": ent.get("datasets") or {}})
    return out


def _resolve(reg: dict, key: str) -> dict[str, Any]:
    """`NMNS` or `institutions:NMNS`. A bare code prefers the institutions
    section, which is the curated one, over a discovered aggregator."""
    kind, _, code = key.rpartition(":")
    for src in _sources(reg):
        if src["code"] == code and (not kind or src["kind"] == kind):
            return src
    raise HTTPException(status_code=404, detail=f"Unknown institution {key!r}")


# ── the flat rows every view is computed from ───────────────────────────────

async def _rows_federated(dataset_ids: list[str] | None) -> list[dict[str, Any]]:
    placeholders = ", ".join(["?"] * len(REPORT_STATUSES))
    params: list[Any] = list(REPORT_STATUSES)
    where = f"a.status IN ({placeholders})"
    if dataset_ids is not None:
        if not dataset_ids:
            return []
        where += f" AND o.tbia_dataset_id IN ({', '.join(['?'] * len(dataset_ids))})"
        params += dataset_ids
    occ = ", ".join(f"o.{c}" for c in _OCC_COLS)
    extra = ", ".join(f"a.{c}" for c in _ANN_EXTRA)
    return await duck.query(
        f"""SELECT a.id, a.occurrence_id, a.field, a.status, a.contributor_id,
                   a.modified, {extra}, {occ}, o.{_SOURCE_ID}
            FROM ann.annotations a JOIN occurrence o ON o.id = a.occurrence_id
            WHERE {where}""",
        params,
    )


async def _rows_python(dataset_ids: list[str] | None) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        anns = db.execute(
            select(Annotation.id, Annotation.occurrence_id, Annotation.field,
                   Annotation.status, Annotation.contributor_id, Annotation.modified,
                   *(getattr(Annotation, c) for c in _ANN_EXTRA))
            .where(Annotation.status.in_(REPORT_STATUSES))
        ).all()
    rows = [dict(r._mapping) for r in anns]
    ids = sorted({r["occurrence_id"] for r in rows})
    if not ids:
        return []
    found = await duck.query(
        f"SELECT id, {', '.join(_OCC_COLS)}, {_SOURCE_ID} FROM occurrence "
        f"WHERE id IN ({', '.join(['?'] * len(ids))})",
        ids,
    )
    by_id = {o["id"]: o for o in found}
    wanted = set(dataset_ids) if dataset_ids is not None else None
    out = []
    for r in rows:
        o = by_id.get(r["occurrence_id"])
        # Same as the inner join: an annotation on a record the store no longer
        # holds belongs to no institution.
        if o is None or (wanted is not None and o["tbia_dataset_id"] not in wanted):
            continue
        out.append({**r, **{c: o[c] for c in (*_OCC_COLS, "source_occurrence_id")}})
    return out


async def _rows(dataset_ids: list[str] | None) -> list[dict[str, Any]]:
    if duck.annotations_attached():
        return await _rows_federated(dataset_ids)
    return await _rows_python(dataset_ids)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _status_counts(rows: list[dict]) -> dict[str, int]:
    c = Counter(r["status"] for r in rows)
    out = {s: c.get(s, 0) for s in REPORT_STATUSES}
    out["total"] = len(rows)
    return out


def _contributor_names(ids: set[int]) -> dict[int, str | None]:
    if not ids:
        return {}
    with SessionLocal() as db:
        users = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
        return {u.id: public_name(u) for u in users}


def _filter(rows: list[dict], status: str | None, field: str | None,
            dataset: str | None) -> list[dict]:
    return [r for r in rows
            if (not status or r["status"] == status)
            and (not field or r["field"] == field)
            and (not dataset or r["tbia_dataset_id"] == dataset)]


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/institutions")
async def report_index():
    """Every institution with at least one non-draft annotation, busiest first."""
    reg = await load_registry()
    rows = await _rows(None)
    by_ds: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ds[r["tbia_dataset_id"]].append(r)
    out = []
    for src in _sources(reg):
        mine = [r for did in src["datasets"] for r in by_ds.get(did, [])]
        if not mine:
            continue
        out.append({
            "kind": src["kind"], "code": src["code"], "name": src["name"],
            "n_annotations": len(mine),
            "n_records": len({r["occurrence_id"] for r in mine}),
            "by_status": _status_counts(mine),
        })
    out.sort(key=lambda x: (-x["n_annotations"], x["kind"], x["code"]))
    return {"items": out}


@router.get("/institutions/{code}")
async def report_summary(code: str):
    reg = await load_registry()
    src = _resolve(reg, code)
    rows = await _rows(list(src["datasets"]))

    by_record: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_record[r["occurrence_id"]].append(r)

    fields: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        fields[r["field"]].append(r)
    by_field = sorted(
        ({"field": f, **_status_counts(rs)} for f, rs in fields.items()),
        key=lambda x: (-x["total"], x["field"]),
    )

    ds_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        ds_rows[r["tbia_dataset_id"]].append(r)
    by_dataset = sorted(
        ({
            "tbia_dataset_id": did,
            "dataset_name": (src["datasets"].get(did) or {}).get("name") or rs[0]["dataset_name"],
            "n_records": len({r["occurrence_id"] for r in rs}),
            **_status_counts(rs),
        } for did, rs in ds_rows.items()),
        key=lambda x: (-x["total"], x["tbia_dataset_id"] or ""),
    )

    per_contrib = Counter(r["contributor_id"] for r in rows)
    names = _contributor_names(set(per_contrib))
    contributors = [
        {"contributor_id": cid, "contributor_name": names.get(cid), "n_annotations": n}
        for cid, n in sorted(per_contrib.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    last = max((r["modified"] for r in rows if r["modified"] is not None), default=None)
    return {
        "kind": src["kind"], "code": src["code"], "name": src["name"],
        "n_datasets": len(src["datasets"]),
        "n_records": len(by_record),
        "n_records_pending": sum(
            1 for rs in by_record.values() if any(r["status"] == "submitted" for r in rs)
        ),
        "by_status": _status_counts(rows),
        "by_field": by_field,
        "by_dataset": by_dataset,
        "contributors": contributors,
        "last_activity": _iso(last),
    }


@router.get("/institutions/{code}/records")
async def report_records(
    code: str,
    status: str | None = None,
    field: str | None = None,
    tbia_dataset_id: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """Annotated records, one row each. A record is listed when any of its
    annotations matches the filters, and its row counts only those that do —
    so the chips say why it is on the list. Records still awaiting review come
    first, then the most recently touched."""
    if status and status not in REPORT_STATUSES:
        raise HTTPException(status_code=400,
                            detail=f"status must be one of {', '.join(REPORT_STATUSES)}")
    reg = await load_registry()
    src = _resolve(reg, code)
    rows = _filter(await _rows(list(src["datasets"])), status, field, tbia_dataset_id)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["occurrence_id"]].append(r)

    items = []
    for occ_id, rs in grouped.items():
        head = rs[0]
        media = parse_media(head["associated_media"])
        last = max((r["modified"] for r in rs if r["modified"] is not None), default=None)
        counts = _status_counts(rs)
        items.append({
            "occurrence_id": occ_id,
            "catalog_number": head["catalog_number"],
            "scientific_name": head["scientific_name"],
            "dataset_name": head["dataset_name"],
            "tbia_dataset_id": head["tbia_dataset_id"],
            "thumbnail": media[0] if media else None,
            "n_media": len(media),
            "n_annotations": len(rs),
            "by_status": counts,
            "fields": sorted({r["field"] for r in rs}),
            "last_modified": _iso(last),
            "_last": last,
        })
    # Newest first, then a stable pass putting pending records on top. The id
    # pass first so ties come out the same from either query path.
    items.sort(key=lambda x: x["occurrence_id"])
    items.sort(key=lambda x: (x["_last"] is not None, x["_last"] or 0), reverse=True)
    items.sort(key=lambda x: x["by_status"]["submitted"] == 0)
    for it in items:
        del it["_last"]
    return {"total": len(items), "items": items[offset:offset + limit],
            "limit": limit, "offset": offset}


# ── the institution's edits, as a file ──────────────────────────────────────

# Three identifiers, because no one of them reaches every record: NMNS and
# NMMBA publish no occurrenceID, TBRI no catalogNumber, and catalogNumber repeats
# within a dataset (~3.7k values in the 2026 store) where occurrenceID never
# does. `tbia_id` is ours and always present — `occurrence.id`, the record URL.
EXPORT_COLUMNS = [
    "annotation_id", "tbia_id", "occurrenceID", "catalogNumber",
    "tbia_dataset_id", "dataset_name", "scientific_name",
    "field", "original_value", "proposed_value", "status",
    "contributor", "contributor_orcid", "modified", "reviewed_at",
    "license", "license_uri",
]


def _contributors_verified(ids: set[int]) -> dict[int, tuple[str | None, str | None]]:
    if not ids:
        return {}
    with SessionLocal() as db:
        users = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
        return {u.id: (u.display_name, u.orcid) for u in users}


@router.get("/institutions/{code}/export")
async def report_export(
    code: str,
    user: User = Depends(auth.require_role("reviewer")),
):
    """Every non-draft annotation on the institution's records, one row each,
    as CSV — the institution-wide counterpart of `/api/export/provider`.

    Reviewer-only for the same reason as that export, and named the same way:
    `contributor` is the ORCID `display_name` and deliberately **not**
    `public_name` — the CC-BY terms most rows carry require attribution, and the
    iD beside it is what makes the name checkable. Which is also why this route
    is not in `cache.py`'s allowlist: it stays `private, no-store`.

    UTF-8 with a BOM, because the values are Chinese and the reader is a
    curator opening it in Excel, which otherwise decodes it as the locale's
    ANSI code page."""
    reg = await load_registry()
    src = _resolve(reg, code)
    rows = await _rows(list(src["datasets"]))
    rows.sort(key=lambda r: (r["tbia_dataset_id"] or "", r["occurrence_id"], r["id"]))
    people = _contributors_verified({r["contributor_id"] for r in rows})

    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for r in rows:
        name, orcid = people.get(r["contributor_id"], (None, None))
        w.writerow({
            "annotation_id": r["id"],
            "tbia_id": r["occurrence_id"],
            "occurrenceID": r["source_occurrence_id"],
            "catalogNumber": r["catalog_number"],
            "tbia_dataset_id": r["tbia_dataset_id"],
            "dataset_name": r["dataset_name"],
            "scientific_name": r["scientific_name"],
            "field": r["field"],
            "original_value": r["original_value"],
            "proposed_value": r["proposed_value"],
            "status": r["status"],
            "contributor": name,
            "contributor_orcid": orcid,
            "modified": _iso(r["modified"]),
            "reviewed_at": _iso(r["reviewed_at"]),
            "license": r["license"],
            "license_uri": LICENSE_URIS.get(r["license"] or ""),
        })
    filename = f"island_{src['code']}_annotations_{date.today().isoformat()}.csv"
    return Response(
        buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
