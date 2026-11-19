"""The contribution workflow rules, shared by every kind of contribution.

An annotation (one field) and an identification (one determination) are
different shapes of work under the *same* rules: who may create in which
status, who may edit, who may relicense, who may review. They lived inline in
`PATCH /annotations/{id}`; with two routers enforcing them, a copy per router is
how the two would come to disagree, so each rule is defined once here.

Each helper raises `HTTPException` with the message the annotation endpoints
have always returned, so moving them here changed no response.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from .models import DEFAULT_LICENSE, LICENSES, User

REVIEW_STATUSES = {"accepted", "rejected", "merged"}
CONTRIB_STATUSES = {"draft", "submitted"}


def _check_license(license: str) -> str:
    if license not in LICENSES:
        raise HTTPException(
            status_code=400, detail=f"license must be one of {', '.join(LICENSES)}"
        )
    return license


def check_create_status(status: str) -> None:
    """A new contribution starts as a draft or as submitted — never reviewed."""
    if status not in CONTRIB_STATUSES:
        raise HTTPException(status_code=400, detail="status must be draft or submitted")


def resolve_license(requested: str | None, user: User) -> str:
    """An unstated licence is the contributor's own default, not a platform guess."""
    return _check_license(requested or user.default_license or DEFAULT_LICENSE)


def is_reviewer(user: User) -> bool:
    return user.role in ("reviewer", "admin")


def check_content_edit(row: Any, user: User) -> None:
    """Owner may edit while still pending; reviewers may always edit."""
    owner = row.contributor_id == user.id
    if not (is_reviewer(user) or (owner and row.status in CONTRIB_STATUSES)):
        raise HTTPException(status_code=403, detail="Cannot edit this annotation")


def apply_license(row: Any, license: str, user: User) -> None:
    """Relicensing is the contributor's alone — at any time, in any status.

    A reviewer may edit a *value*; that is the job. Restating the terms someone
    else released their work under is not, so this is the one edit the reviewer
    role does not inherit — not even for an admin.

    There is no status past which it freezes, which is iNaturalist's rule and
    the right one: what cannot be revoked is the copy a provider already took,
    not the record. An export states the terms in force when it ran, that
    delivered file keeps them, and a later change applies to exports from here
    on. Freezing the row instead would confuse "you cannot take back what you
    gave" with "you may never change your mind", and only the first is true."""
    if row.contributor_id != user.id:
        raise HTTPException(status_code=403, detail="Only the contributor may set the licence")
    row.license = _check_license(license)


def apply_status(row: Any, status: str, user: User) -> None:
    """Status transitions, one way: there is no path back to draft."""
    owner = row.contributor_id == user.id
    if status in REVIEW_STATUSES:
        if not is_reviewer(user):
            raise HTTPException(status_code=403, detail="Reviewer role required")
        row.reviewed_by = user.id
        row.reviewed_at = datetime.now(timezone.utc)
    elif status == "submitted":
        if not (owner or is_reviewer(user)):
            raise HTTPException(status_code=403, detail="Not your annotation")
    elif status == "draft":
        raise HTTPException(status_code=400, detail="Cannot revert to draft")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown status {status}")
    row.status = status
