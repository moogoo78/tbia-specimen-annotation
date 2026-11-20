"""Admin: the user list, and the identifier flag on each user.

The flag is the only thing set here. `role` stays out on purpose — it has
never had an editing surface, and widening one admin action into "edit any
user" is a bigger decision than this one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


class AdminUser(BaseModel):
    id: int
    orcid: str | None = None
    email: str | None = None
    display_name: str
    role: str
    is_identifier: bool = False


class AdminUserPatch(BaseModel):
    is_identifier: bool


def _out(u: User) -> AdminUser:
    return AdminUser(id=u.id, orcid=u.orcid, email=u.email, display_name=u.display_name,
                     role=u.role, is_identifier=bool(u.is_identifier))


@router.get("")
def list_users(
    q: str | None = None,
    identifiers: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    _: User = Depends(auth.require_role("admin")),
    db: Session = Depends(get_session),
):
    conds = []
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(User.display_name.ilike(like), User.public_display_name.ilike(like),
                         User.orcid.ilike(like), User.email.ilike(like)))
    if identifiers:
        conds.append(User.is_identifier.is_(True))
    total = db.scalar(select(func.count()).select_from(User).where(*conds))
    rows = db.execute(
        select(User).where(*conds).order_by(User.display_name, User.id).limit(limit).offset(offset)
    ).scalars().all()
    return {"total": total, "items": [_out(u) for u in rows], "limit": limit, "offset": offset}


@router.patch("/{user_id}", response_model=AdminUser)
def update_user(
    user_id: int,
    body: AdminUserPatch,
    _: User = Depends(auth.require_role("admin")),
    db: Session = Depends(get_session),
):
    """Grant or withdraw the identifier flag. Withdrawing it stops new
    determinations only; what the person already identified stays theirs and
    keeps its status — the flag gates the act, it does not retract the work."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    u.is_identifier = body.is_identifier
    db.commit()
    db.refresh(u)
    return _out(u)
