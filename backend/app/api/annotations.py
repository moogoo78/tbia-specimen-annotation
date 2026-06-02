from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, duck, extract, search
from ..annotations_store import _serialize
from ..db import get_session
from ..models import Annotation, User
from ..schemas import AnnotationCreate, AnnotationUpdate, ExtractResponse

router = APIRouter(prefix="/api", tags=["annotations"])

REVIEW_STATUSES = {"accepted", "rejected", "merged"}
CONTRIB_STATUSES = {"draft", "submitted"}


def _out(db: Session, a: Annotation) -> dict:
    name = db.get(User, a.contributor_id)
    return _serialize(a, name.display_name if name else None)


@router.post("/occurrences/{occ_id}/extract", response_model=ExtractResponse)
async def ai_extract(occ_id: str, user: User = Depends(auth.current_user)):
    record = await search.get_detail(occ_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return extract.extract(record)


@router.post("/occurrences/{occ_id}/annotations")
async def create_annotation(
    occ_id: str,
    body: AnnotationCreate,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    record = await duck.query_one(
        "SELECT dataset_name FROM occurrences WHERE id = ?", [occ_id]
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    if body.status not in CONTRIB_STATUSES:
        raise HTTPException(status_code=400, detail="status must be draft or submitted")

    ann = Annotation(
        occurrence_id=occ_id,
        dataset_name=record["dataset_name"],
        field=body.field,
        original_value=body.original_value,
        proposed_value=body.proposed_value,
        source=body.source,
        ai_confidence=body.ai_confidence,
        ai_raw=body.ai_raw,
        note=body.note,
        status=body.status,
        contributor_id=user.id,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return _out(db, ann)


@router.patch("/annotations/{ann_id}")
def update_annotation(
    ann_id: int,
    body: AnnotationUpdate,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    ann = db.get(Annotation, ann_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    is_owner = ann.contributor_id == user.id
    is_reviewer = user.role in ("reviewer", "admin")

    # Content edits: owner may edit while still pending; reviewers may always edit.
    if body.proposed_value is not None or body.note is not None:
        if not (is_reviewer or (is_owner and ann.status in CONTRIB_STATUSES)):
            raise HTTPException(status_code=403, detail="Cannot edit this annotation")
        if body.proposed_value is not None:
            ann.proposed_value = body.proposed_value
        if body.note is not None:
            ann.note = body.note

    # Status transitions.
    if body.status is not None:
        if body.status in REVIEW_STATUSES:
            if not is_reviewer:
                raise HTTPException(status_code=403, detail="Reviewer role required")
            ann.reviewed_by = user.id
            ann.reviewed_at = datetime.now(timezone.utc)
        elif body.status == "submitted":
            if not (is_owner or is_reviewer):
                raise HTTPException(status_code=403, detail="Not your annotation")
        elif body.status == "draft":
            raise HTTPException(status_code=400, detail="Cannot revert to draft")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown status {body.status}")
        ann.status = body.status

    db.commit()
    db.refresh(ann)
    return _out(db, ann)


@router.get("/annotations")
def list_annotations(
    status: str | None = None,
    dataset_name: str | None = None,
    mine: bool = False,
    occurrence_id: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    conds = []
    if status:
        conds.append(Annotation.status == status)
    if dataset_name:
        conds.append(Annotation.dataset_name == dataset_name)
    if occurrence_id:
        conds.append(Annotation.occurrence_id == occurrence_id)
    if mine:
        conds.append(Annotation.contributor_id == user.id)

    total = db.scalar(select(func.count()).select_from(Annotation).where(*conds))
    rows = db.execute(
        select(Annotation).where(*conds)
        .order_by(Annotation.modified.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return {"total": total, "items": [_out(db, a) for a in rows], "limit": limit, "offset": offset}
