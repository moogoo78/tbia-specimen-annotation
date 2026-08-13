from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, duck, extract, notify, pipeline, policy, search
from ..annotations_store import _serialize
from ..config import settings
from ..db import get_session
from ..models import Annotation, TranscribeRequest, User
from ..schemas import (
    AnnotationCreate,
    AnnotationUpdate,
    ExtractPaste,
    ExtractPromptResponse,
    ExtractResponse,
    TranscribeConfig,
    TranscribeConfigUpdate,
    TranscribeOptions,
    TranscribeRequestOut,
)

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


@router.get("/occurrences/{occ_id}/extract-prompt", response_model=ExtractPromptResponse)
async def ai_extract_prompt(occ_id: str, user: User = Depends(auth.current_user)):
    """Build a ready-to-paste prompt (+ image URL) for the user's own AI chat."""
    record = await search.get_detail(occ_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    return extract.build_prompt(record)


@router.post("/occurrences/{occ_id}/extract-paste", response_model=ExtractResponse)
async def ai_extract_paste(
    occ_id: str, body: ExtractPaste, user: User = Depends(auth.current_user)
):
    """Parse the JSON the user pastes back into AI-draft fields."""
    try:
        return extract.parse_pasted(occ_id, body.raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/transcribe/config", response_model=TranscribeConfig)
async def transcribe_config(db: Session = Depends(get_session)):
    """The models the "auto" preset resolves to, plus the route in force. Mirrors
    the fallback logic in pipeline.transcribe_record: single mode uses
    anthropic_model and no OCR pass; two_stage uses ocr_model -> field_model.

    The route comes from the admin-set policy, not from who is asking — every
    caller is told the same thing, because it is what *their* click will do."""
    route = policy.transcribe_route(db)
    if settings.transcribe_mode == "single":
        return TranscribeConfig(
            mode="single", ocr_model=None, field_model=settings.anthropic_model, route=route,
        )
    return TranscribeConfig(
        mode="two_stage", ocr_model=settings.ocr_model, field_model=settings.field_model,
        route=route,
    )


@router.put("/transcribe/config", response_model=TranscribeConfig)
async def set_transcribe_config(
    body: TranscribeConfigUpdate,
    user: User = Depends(auth.require_role("admin")),
    db: Session = Depends(get_session),
):
    """Set the system-wide transcribe route. Admin-only, and it moves what every
    contributor's click does — under "now" their request pays for the vision call
    and holds the connection while it runs — so it is one deliberate act by one
    role, rather than a per-record choice each caller makes for themselves."""
    try:
        policy.set_transcribe_route(db, body.route, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await transcribe_config(db)


@router.post("/occurrences/{occ_id}/transcribe-request", response_model=TranscribeRequestOut)
async def schedule_transcribe(
    occ_id: str,
    opts: TranscribeOptions | None = Body(default=None),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    """Schedule a record for transcription: persist the request (occurrence id +
    who scheduled it + optional pipeline overrides) and ping Discord. The Discord
    ping is best-effort and never blocks the request."""
    record = await duck.query_one("SELECT id FROM occurrence WHERE id = ?", [occ_id])
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    opts = opts or TranscribeOptions()
    if opts.mode is not None and opts.mode not in ("single", "two_stage"):
        raise HTTPException(status_code=400, detail="mode must be 'single' or 'two_stage'")

    req = TranscribeRequest(
        occurrence_id=occ_id, contributor_id=user.id,
        mode=opts.mode, ocr_model=opts.ocr_model, field_model=opts.field_model,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    notified = notify.transcribe_scheduled(occ_id, user.id)
    out = TranscribeRequestOut.model_validate(req)
    out.notified = notified
    return out


@router.post("/occurrences/{occ_id}/transcribe-now", response_model=TranscribeRequestOut)
async def transcribe_now(
    occ_id: str,
    opts: TranscribeOptions | None = Body(default=None),
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    """Transcribe a record **now**, in this request, instead of queueing it.

    Same destination as the queue: one `transcribe_requests` row and `ai`
    annotation drafts written by `pipeline.process_one`, so a record looks the
    same afterwards whichever route produced it. What differs is who waits and
    who pays — the caller holds the connection for the tens of seconds a vision
    call takes, and the call is billed the moment they click.

    **Who may call it is policy, not role alone.** An admin always may. Everyone
    else may exactly when an admin has switched the system-wide route to "now"
    (`policy.transcribe_route`) — the same value the UI reads to decide which
    button to show. The check is here rather than only in the UI because the
    endpoint is reachable without it, and "the switch is set to queue" has to
    mean nobody is spending vision calls inline, not just that nobody is being
    offered the option.

    No Discord ping either: that notification exists to tell a human the worker
    has something to drain, and here it has already been drained.

    A failure (no API key, unreadable image, model error) is *not* a 500 —
    `process_one` records it on the row, and the response carries
    `status="failed"` with the reason in `error`, exactly as the worker would.
    """
    if user.role != "admin" and policy.transcribe_route(db) != "now":
        raise HTTPException(status_code=403, detail="Run-now is disabled; use the queue")

    record = await duck.query_one("SELECT id FROM occurrence WHERE id = ?", [occ_id])
    if record is None:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    opts = opts or TranscribeOptions()
    if opts.mode is not None and opts.mode not in ("single", "two_stage"):
        raise HTTPException(status_code=400, detail="mode must be 'single' or 'two_stage'")

    # A record already waiting in the queue is *run*, not queued a second time:
    # the worker drains by status, so a fresh row would leave the pending one to
    # be transcribed again later and write a duplicate set of drafts. Running the
    # existing row also keeps the drafts credited to whoever asked for them — the
    # admin supplied the impatience, not the request.
    req = db.execute(
        select(TranscribeRequest)
        .where(TranscribeRequest.occurrence_id == occ_id)
        .where(TranscribeRequest.status == "pending")
        .order_by(TranscribeRequest.created.desc())
    ).scalars().first()

    if req is None:
        req = TranscribeRequest(
            occurrence_id=occ_id, contributor_id=user.id,
            mode=opts.mode, ocr_model=opts.ocr_model, field_model=opts.field_model,
        )
        db.add(req)
        db.commit()
        db.refresh(req)

    n = await pipeline.process_one(db, req)
    db.refresh(req)

    out = TranscribeRequestOut.model_validate(req)
    out.n_annotations = n
    return out


@router.post("/occurrences/{occ_id}/annotations")
async def create_annotation(
    occ_id: str,
    body: AnnotationCreate,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    record = await duck.query_one(
        "SELECT dataset_name FROM occurrence WHERE id = ?", [occ_id]
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
