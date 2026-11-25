"""Admin: every user, what they have contributed, and the identifier flag.

Backs the /admin/users page. Two things are set nowhere else and are still
not set here: `role` (no editing surface, by decision) and anything a user
controls about themselves (/me). The one write is the identifier flag.

Drafts stay private even from an admin: they are counted, never listed. A
draft is working state its author has not offered to anyone, and "an admin can
read it" would make the /me promise conditional.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_session
from ..identifications_store import serialize as serialize_ident
from ..models import Annotation, Identification, User, public_name

router = APIRouter(prefix="/api/admin/users", tags=["admin"])

ACCEPTED = ("accepted", "merged")
SORTS = ("name", "created", "last_login", "annotations", "identifications")


class AdminUser(BaseModel):
    id: int
    orcid: str | None = None
    email: str | None = None
    display_name: str
    public_display_name: str | None = None
    show_in_ranking: bool = False
    role: str
    is_identifier: bool = False
    created: datetime | None = None
    last_login_at: datetime | None = None
    # Non-draft rows; "accepted" counts accepted + merged.
    n_annotations: int = 0
    n_annotations_accepted: int = 0
    n_identifications: int = 0
    n_identifications_accepted: int = 0


class AdminUserPatch(BaseModel):
    is_identifier: bool


def _counts(model):
    """Per-contributor (all non-draft, accepted) counts as a subquery."""
    return (
        select(
            model.contributor_id.label("uid"),
            func.count().label("n"),
            func.sum(case((model.status.in_(ACCEPTED), 1), else_=0)).label("ok"),
        )
        .where(model.status != "draft")
        .group_by(model.contributor_id)
        .subquery()
    )


def _row(u: User, na=0, naok=0, ni=0, niok=0) -> AdminUser:
    return AdminUser(
        id=u.id, orcid=u.orcid, email=u.email, display_name=u.display_name,
        public_display_name=u.public_display_name, show_in_ranking=bool(u.show_in_ranking),
        role=u.role, is_identifier=bool(u.is_identifier), created=u.created,
        last_login_at=u.last_login_at, n_annotations=na or 0, n_annotations_accepted=naok or 0,
        n_identifications=ni or 0, n_identifications_accepted=niok or 0,
    )


@router.get("")
def list_users(
    q: str | None = None,
    identifiers: bool = False,
    role: str | None = None,
    sort: str = Query(default="name", pattern=f"^-?({'|'.join(SORTS)})$"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    _: User = Depends(auth.require_role("admin")),
    db: Session = Depends(get_session),
):
    """`sort` is one of SORTS; a leading `-` reverses it. Counts default to
    descending order and names/dates to the natural one, so `annotations`
    lists the most active first."""
    a, i = _counts(Annotation), _counts(Identification)
    conds = []
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(User.display_name.ilike(like), User.public_display_name.ilike(like),
                         User.orcid.ilike(like), User.email.ilike(like)))
    if identifiers:
        conds.append(User.is_identifier.is_(True))
    if role:
        conds.append(User.role == role)

    desc = sort.startswith("-")
    key = sort.lstrip("-")
    col, natural_desc = {
        "name": (func.lower(User.display_name), False),
        "created": (User.created, True),
        "last_login": (User.last_login_at, True),
        "annotations": (func.coalesce(a.c.n, 0), True),
        "identifications": (func.coalesce(i.c.n, 0), True),
    }[key]
    order = col.desc() if natural_desc != desc else col.asc()
    if key == "last_login":
        order = order.nulls_last()

    base = (select(User, a.c.n, a.c.ok, i.c.n, i.c.ok)
            .outerjoin(a, a.c.uid == User.id).outerjoin(i, i.c.uid == User.id)
            .where(*conds))
    total = db.scalar(select(func.count()).select_from(User).where(*conds))
    rows = db.execute(base.order_by(order, User.id).limit(limit).offset(offset)).all()
    return {"total": total, "items": [_row(*r) for r in rows], "limit": limit, "offset": offset}


def _by_status(db: Session, model, uid: int) -> dict[str, int]:
    rows = db.execute(
        select(model.status, func.count()).where(model.contributor_id == uid).group_by(model.status)
    ).all()
    return {s: n for s, n in rows}


@router.get("/{user_id}")
def get_user(
    user_id: int,
    _: User = Depends(auth.require_role("admin")),
    db: Session = Depends(get_session),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    ann, ident = _by_status(db, Annotation, u.id), _by_status(db, Identification, u.id)
    ok = lambda d: sum(d.get(s, 0) for s in ACCEPTED)  # noqa: E731
    nd = lambda d: sum(n for s, n in d.items() if s != "draft")  # noqa: E731
    recent = db.execute(
        select(Identification)
        .where(Identification.contributor_id == u.id, Identification.status != "draft")
        .order_by(Identification.modified.desc(), Identification.id.desc()).limit(20)
    ).scalars().all()
    name = public_name(u)
    return {
        "user": _row(u, nd(ann), ok(ann), nd(ident), ok(ident)),
        "annotations_by_status": ann,
        "identifications_by_status": ident,
        "recent_identifications": [serialize_ident(r, name) for r in recent],
    }


@router.patch("/{user_id}")
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
    return _row(u)
