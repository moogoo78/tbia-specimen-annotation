"""Lightweight read helpers for annotations, usable outside request scope
(e.g. enriching an occurrence detail with its annotation history)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from .db import SessionLocal
from .models import Annotation, TranscribeRequest, User


def _serialize(a: Annotation, name: str | None) -> dict[str, Any]:
    return {
        "id": a.id,
        "occurrence_id": a.occurrence_id,
        "dataset_name": a.dataset_name,
        "field": a.field,
        "original_value": a.original_value,
        "proposed_value": a.proposed_value,
        "source": a.source,
        "ai_confidence": a.ai_confidence,
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
            select(Annotation, User.display_name)
            .join(User, Annotation.contributor_id == User.id)
            .where(Annotation.occurrence_id == occ_id)
            .order_by(Annotation.created.desc())
        ).all()
        return [_serialize(a, name) for a, name in rows]


def latest_transcribe_request(occ_id: str) -> dict[str, Any] | None:
    """The record's most recent AI transcription request, so the detail view can
    show a durable "queued / done / failed" state instead of the client's
    short-lived post-click flash."""
    with SessionLocal() as db:
        row = db.execute(
            select(TranscribeRequest, User.display_name)
            .join(User, TranscribeRequest.contributor_id == User.id)
            .where(TranscribeRequest.occurrence_id == occ_id)
            .order_by(TranscribeRequest.created.desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        req, name = row
        return {
            "id": req.id,
            "status": req.status,
            "requested_by": name,
            "created": req.created.isoformat() if req.created else None,
            "processed_at": req.processed_at.isoformat() if req.processed_at else None,
            "error": req.error,
        }
