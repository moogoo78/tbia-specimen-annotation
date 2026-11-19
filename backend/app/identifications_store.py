"""Read helpers for identifications, usable outside request scope — the
counterpart of `annotations_store.py`, under the same publication rules."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db import SessionLocal
from .models import Identification, User, public_name

# The determination's own columns, in DwC order. One list so the serializer,
# the create/update routes and the export cannot disagree about what an
# identification consists of.
IDENT_FIELDS = (
    "scientific_name", "taxon_rank", "identification_qualifier",
    "verbatim_identification", "identified_by", "identified_by_id",
    "date_identified", "identification_references", "identification_remarks",
)


def serialize(i: Identification, name: str | None) -> dict[str, Any]:
    """`name` is the *publishable* name (models.public_name): None means the
    contributor has not opted in, never that there is no contributor."""
    out: dict[str, Any] = {
        "id": i.id,
        "occurrence_id": i.occurrence_id,
        "dataset_name": i.dataset_name,
    }
    out.update({f: getattr(i, f) for f in IDENT_FIELDS})
    out.update({
        "status": i.status,
        "license": i.license,
        "contributor_id": i.contributor_id,
        "contributor_name": name,
        "reviewed_by": i.reviewed_by,
        "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
        "created": i.created.isoformat() if i.created else None,
        "modified": i.modified.isoformat() if i.modified else None,
    })
    return out


def list_for_occurrence(occ_id: str) -> list[dict[str, Any]]:
    """A record's published identifications, newest first — never its drafts.

    Feeds `GET /api/occurrences/{id}`, which is unauthenticated and edge-cached,
    so a draft here would be published whatever the page rendered (see
    `annotations_store.list_for_occurrence`). Rejected rows *are* shipped, as
    rejected annotations are: the history is the record of review; the page
    decides what to show as the specimen's determination."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Identification, User)
            .join(User, Identification.contributor_id == User.id)
            .where(Identification.occurrence_id == occ_id, Identification.status != "draft")
            .order_by(Identification.created.desc(), Identification.id.desc())
        ).all()
        return [serialize(i, public_name(u)) for i, u in rows]
