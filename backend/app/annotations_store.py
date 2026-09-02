"""Lightweight read helpers for annotations, usable outside request scope
(e.g. enriching an occurrence detail with its annotation history)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from .db import SessionLocal
from .models import Annotation, TranscribeRequest, User, public_name


def _serialize(a: Annotation, name: str | None) -> dict[str, Any]:
    """`name` is the *publishable* name (models.public_name), so None here means
    the contributor has not opted in — not that the row has no contributor."""
    return {
        "id": a.id,
        "occurrence_id": a.occurrence_id,
        "dataset_name": a.dataset_name,
        "field": a.field,
        "original_value": a.original_value,
        "proposed_value": a.proposed_value,
        "source": a.source,
        # What the AI proposed for this field, beside what the contributor sent.
        # Both travel together or the pair says nothing: `ai_value` equal to
        # `proposed_value` is agreement, different is a correction, null is a
        # value no AI was involved in.
        "ai_value": a.ai_value,
        "ai_confidence": a.ai_confidence,
        "ai_model": a.ai_model,
        "note": a.note,
        "status": a.status,
        "license": a.license,
        "contributor_id": a.contributor_id,
        "contributor_name": name,
        "reviewed_by": a.reviewed_by,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "created": a.created.isoformat() if a.created else None,
        "modified": a.modified.isoformat() if a.modified else None,
    }


def list_for_occurrence(occ_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(Annotation, User)
            .join(User, Annotation.contributor_id == User.id)
            .where(Annotation.occurrence_id == occ_id)
            .order_by(Annotation.created.desc())
        ).all()
        return [_serialize(a, public_name(u)) for a, u in rows]


def _result_fields(raw: str | None) -> list[dict[str, Any]]:
    """The proposed fields out of a stored `result_json`, defensively.

    This feeds `GET /api/occurrences/{id}`, which is unauthenticated and the most
    requested route on the site — a blob written by an older version, or
    half-written by a crash, must degrade to "no proposal" rather than 500 a
    record page for everyone."""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        fields = payload.get("fields") or []
        return [
            {
                "field": str(f["field"]),
                "value": str(f.get("value", "")),
                "confidence": float(f.get("confidence") or 0.0),
            }
            for f in fields
            if isinstance(f, dict) and f.get("field")
        ]
    except Exception:  # noqa: BLE001 - a bad blob is "no proposal", not an error
        return []


def _result_meta(raw: str | None, key: str) -> str | None:
    """One scalar out of a stored `result_json` (`model` / `service`), read as
    defensively as `_result_fields` reads its list."""
    if not raw:
        return None
    try:
        value = json.loads(raw).get(key)
    except Exception:  # noqa: BLE001
        return None
    return None if value is None else str(value)


def latest_transcribe_request(occ_id: str) -> dict[str, Any] | None:
    """The record's most recent AI transcription request — its durable
    "queued / done / failed" state, and, once done, the transcription itself.

    The proposed fields ride here rather than on `annotations` because that is
    what they are: a proposal nobody has vouched for yet. The record page pours
    them into the annotation form, where a person edits and submits them."""
    with SessionLocal() as db:
        row = db.execute(
            select(TranscribeRequest, User)
            .join(User, TranscribeRequest.contributor_id == User.id)
            .where(TranscribeRequest.occurrence_id == occ_id)
            .order_by(TranscribeRequest.created.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        req, user = row
        return {
            "id": req.id,
            "status": req.status,
            # Who asked, named only if they opted in; the id goes out either way
            # so the UI can say "Unnamed contributor #<id>" like everywhere else.
            "requested_by": public_name(user),
            "requested_by_id": req.contributor_id,
            "created": req.created.isoformat() if req.created else None,
            "processed_at": req.processed_at.isoformat() if req.processed_at else None,
            "error": req.error,
            # The run's own output. Empty list while pending, on a failure, and
            # for requests processed before results were stored (those wrote `ai`
            # annotations, which are still in the record's history).
            "fields": _result_fields(req.result_json),
            "model": _result_meta(req.result_json, "model"),
            "service": _result_meta(req.result_json, "service"),
        }
