"""AI transcription pipeline — the batch worker's core.

A contributor schedules a record (``TranscribeRequest``, status ``pending``);
this module drains the queue: for each request it fetches the occurrence, sends
the specimen image + the label-transcription prompt to Claude vision, and turns
the response into ``ai`` annotation drafts (status ``submitted``) attributed to
the scheduling contributor. Runs from ``app.worker`` (cron / ``make transcribe``).

The transcription itself reuses ``extract.build_prompt`` (the field list the
copy-paste flow already uses) and ``extract.parse_pasted`` (the defensive JSON
parser), so the pipeline and the manual flow stay in lockstep.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import extract, search
from .config import settings
from .models import Annotation, TranscribeRequest
from .schemas import ExtractResponse

log = logging.getLogger("pipeline")

# tbia annotation field -> occurrence column, for the annotation's original_value
# (reference/diff). `annotation*`/`verbatim*` fields have no occurrence value.
_ORIGINAL_COLUMN = {
    "catalogNumber": "catalog_number", "typeStatus": "type_status",
    "recordedBy": "recorded_by", "recordNumber": "record_number",
    "taxonRank": "taxon_rank", "eventDate": "std_date", "locality": "locality",
}


def transcribe_record(record: dict) -> ExtractResponse:
    """One Claude vision call: read the specimen label into proposed fields.

    Sends the first media image plus the transcription prompt, then parses the
    model's JSON reply with the same defensive parser the copy-paste flow uses.
    Raises ValueError when the record has no image."""
    occ_id = record.get("id", "")
    media = record.get("media") or []
    image_url = media[0] if media else None
    if not image_url:
        raise ValueError("record has no image to transcribe")

    prompt = extract.build_prompt(record).prompt
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "url", "url": image_url}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    out = extract.parse_pasted(occ_id, text)  # validates + clamps confidence
    out.image_url = image_url
    out.model = resp.model
    out.service = "anthropic"
    return out


async def process_one(db: Session, req: TranscribeRequest) -> int:
    """Transcribe one pending request into annotation rows; returns the count.

    Marks the request done/failed and commits. Never raises — a bad record fails
    just that request, not the batch."""
    try:
        record = await search.get_detail(req.occurrence_id)
        if record is None:
            raise ValueError("occurrence not found")
        result = transcribe_record(record)

        n = 0
        for field in result.fields:
            db.add(Annotation(
                occurrence_id=req.occurrence_id,
                dataset_name=record.get("dataset_name"),
                field=field.field,
                original_value=_original(record, field.field),
                proposed_value=field.value,
                source="ai",
                ai_confidence=field.confidence,
                note=f"AI transcription ({result.service or 'anthropic'} · {result.model})",
                status="submitted",
                contributor_id=req.contributor_id,
            ))
            n += 1

        req.status = "done"
        req.processed_at = datetime.now(timezone.utc)
        db.commit()
        return n
    except Exception as exc:  # noqa: BLE001 - isolate one request's failure
        db.rollback()
        req.status = "failed"
        req.processed_at = datetime.now(timezone.utc)
        req.error = str(exc)[:500]
        db.commit()
        log.warning("transcribe request %s failed: %s", req.id, exc)
        return 0


async def process_pending(db: Session, limit: int | None = None) -> dict:
    """Drain up to `limit` pending requests (default settings.transcribe_batch)."""
    limit = limit or settings.transcribe_batch
    pending = db.execute(
        select(TranscribeRequest)
        .where(TranscribeRequest.status == "pending")
        .order_by(TranscribeRequest.created)
        .limit(limit)
    ).scalars().all()

    annotations = 0
    done = 0
    for req in pending:
        n = await process_one(db, req)
        annotations += n
        if req.status == "done":
            done += 1
    return {
        "requests": len(pending),
        "done": done,
        "failed": len(pending) - done,
        "annotations": annotations,
    }


def _original(record: dict, field: str) -> str | None:
    col = _ORIGINAL_COLUMN.get(field)
    if not col:
        return None
    val = record.get(col)
    return None if val is None else str(val)
