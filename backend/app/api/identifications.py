"""Identifications: a person's determination of a specimen (DwC Identification).

Not transcription — nothing here reads a label or calls a model. Same workflow
as an annotation (`app/workflow.py`): created as draft/submitted, reviewed to
accepted/rejected/merged, licensed per row by its contributor alone.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth, duck, taicol, workflow
from ..db import get_session
from ..identifications_store import IDENT_FIELDS, serialize
from ..models import Identification, User, public_name
from ..schemas import IdentificationCreate, IdentificationUpdate

router = APIRouter(prefix="/api", tags=["identifications"])

# DwC dateIdentified is ISO 8601; a determination slip often gives only a year
# or a month, and DwC permits an interval. Anything else is refused rather than
# stored, because this value goes to providers as a date.
_DATE = r"\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?"
DATE_RE = re.compile(rf"^{_DATE}(/{_DATE})?$")

MAX_LEN = 2000


def _clean(name: str, value: str | None) -> str | None:
    """Trim; blank means "no value". Raises on what must not be stored."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_LEN:
        raise HTTPException(status_code=400, detail=f"{name} is too long")
    if not value:
        return None
    if name == "scientific_name_id" and not value.startswith(taicol.NAME_URI_PREFIX):
        # The only source of one is the TaiCOL picker; anything else is not an
        # identifier we can stand behind in a provider export.
        raise HTTPException(status_code=400, detail="scientific_name_id must be a TaiCOL name URI")
    if name == "date_identified" and not DATE_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail="date_identified must be ISO 8601: YYYY, YYYY-MM or YYYY-MM-DD",
        )
    return value


def _out(db: Session, i: Identification) -> dict:
    return serialize(i, public_name(db.get(User, i.contributor_id)))


@router.post("/occurrences/{occ_id}/identifications")
async def create_identification(
    occ_id: str,
    body: IdentificationCreate,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    record = await duck.query_one("SELECT dataset_name FROM occurrence WHERE id = ?", [occ_id])
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    workflow.check_create_status(body.status)
    license = workflow.resolve_license(body.license, user)

    values = {f: _clean(f, getattr(body, f)) for f in IDENT_FIELDS}
    if not values["scientific_name"]:
        raise HTTPException(status_code=400, detail="scientific_name is required")
    if not values["scientific_name_id"]:
        values["name_according_to"] = None  # provenance only travels with an id

    ident = Identification(
        occurrence_id=occ_id,
        dataset_name=record["dataset_name"],
        status=body.status,
        license=license,
        contributor_id=user.id,
        **values,
    )
    db.add(ident)
    db.commit()
    db.refresh(ident)
    return _out(db, ident)


@router.patch("/identifications/{ident_id}")
def update_identification(
    ident_id: int,
    body: IdentificationUpdate,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    ident = db.get(Identification, ident_id)
    if ident is None:
        raise HTTPException(status_code=404, detail="Identification not found")

    # Absent = untouched; "" = clear (except the name, which a determination needs).
    sent = {f: getattr(body, f) for f in IDENT_FIELDS if getattr(body, f) is not None}
    # A new name without a new id is a hand-typed name: the old TaiCOL id and
    # its provenance described the previous name, so they go with it.
    if ("scientific_name" in sent and "scientific_name_id" not in sent
            and (sent["scientific_name"] or "").strip() != (ident.scientific_name or "")):
        sent["scientific_name_id"] = ""
        sent["name_according_to"] = ""
    if sent:
        workflow.check_content_edit(ident, user)
        for f, v in sent.items():
            v = _clean(f, v)
            if f == "scientific_name" and not v:
                raise HTTPException(status_code=400, detail="scientific_name is required")
            setattr(ident, f, v)
    if body.license is not None:
        workflow.apply_license(ident, body.license, user)
    if body.status is not None:
        workflow.apply_status(ident, body.status, user)

    db.commit()
    db.refresh(ident)
    return _out(db, ident)


@router.get("/identifications")
def list_identifications(
    status: str | None = None,
    mine: bool = False,
    occurrence_id: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    conds = []
    if occurrence_id:
        conds.append(Identification.occurrence_id == occurrence_id)
    if mine:
        conds.append(Identification.contributor_id == user.id)
    else:
        # Drafts are private: only their author ever lists them.
        conds.append(or_(Identification.status != "draft",
                         Identification.contributor_id == user.id))
    if status:
        conds.append(Identification.status == status)

    total = db.scalar(select(func.count()).select_from(Identification).where(*conds))
    rows = db.execute(
        select(Identification).where(*conds)
        .order_by(Identification.modified.desc(), Identification.id.desc())
        .limit(limit).offset(offset)
    ).scalars().all()
    return {"total": total, "items": [_out(db, i) for i in rows],
            "limit": limit, "offset": offset}
