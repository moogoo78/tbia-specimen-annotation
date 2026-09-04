"""A contributor's own work, as a place rather than a filter.

Four routes, and the split between them is about *who is asking*:

- ``GET /api/contributions`` is the platform's public activity: what everyone
  has been contributing lately, with the same per-status breakdown. It sat
  behind a login on the dashboard for no reason -- every row of it is already
  visible on its own record page.
- ``GET /api/contributors/{user_id}`` and ``.../annotations`` are public. They
  are the recognition surface -- what a byline in a record's annotation history
  and a row on the ranking board open into. Drafts never appear, and a name
  appears only if its owner opted in (``models.public_name``), exactly as on
  every other public surface.
- ``GET /api/annotations/mine`` is the contributor's own view: drafts included,
  and real per-status totals rather than a client-side count of one page.

The private route is a *separate route template* on purpose, not
``/api/contributors/me/...``. The public pair is in ``cache.LIVE_ROUTES``, and a
response that depends on who is signed in must never be reachable under a
template a shared cache is allowed to store.

A note on the two words: the board endpoint stays ``/api/volunteers`` because
renaming it would break its callers, while the site itself says "contributors"
(the ``/volunteers`` -> ``/contributors`` redirect in the router). New routes use
the current word.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth
from ..annotations_store import _serialize
from ..contributions_store import attach_records, status_counts, summary_for
from ..db import get_session
from ..models import Annotation, User, public_name

router = APIRouter(prefix="/api", tags=["contributions"])


def _page(db: Session, conds: list, limit: int, offset: int) -> tuple[int, list[Annotation]]:
    total = db.scalar(select(func.count()).select_from(Annotation).where(*conds))
    rows = db.execute(
        select(Annotation).where(*conds)
        .order_by(Annotation.modified.desc(), Annotation.id.desc())
        .limit(limit).offset(offset)
    ).scalars().all()
    return total or 0, list(rows)


@router.get("/contributions")
async def recent_contributions(
    status: str | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: Session = Depends(get_session),
):
    """Everyone's contributions, newest first — the public activity feed.

    Drafts are excluded here as everywhere public: they are private working
    state. The summary is over every non-draft row and is deliberately *not*
    narrowed by ``status``, so choosing one leaves the breakdown standing.
    """
    if status == "draft":
        raise HTTPException(status_code=400, detail="Drafts are not public")
    base = [Annotation.status != "draft"]
    conds = base + ([Annotation.status == status] if status else [])

    total = db.scalar(select(func.count()).select_from(Annotation).where(*conds))
    # Joined rather than a lookup per row: this feed mixes contributors, so
    # `api/annotations._out`'s per-row `db.get(User, ...)` would be N+1 here.
    rows = db.execute(
        select(Annotation, User).join(User, Annotation.contributor_id == User.id)
        .where(*conds)
        .order_by(Annotation.modified.desc(), Annotation.id.desc())
        .limit(limit).offset(offset)
    ).all()
    items = [_serialize(a, public_name(u)) for a, u in rows]
    await attach_records(items)
    return {"total": total, "items": items, "limit": limit, "offset": offset,
            "summary": status_counts(db, base)}


@router.get("/contributors/{user_id}")
def contributor_profile(user_id: int, db: Session = Depends(get_session)):
    """One contributor's public standing.

    404 covers both "no such user" and "this user has contributed nothing" --
    an account that signed in once and never annotated has no page, or the user
    table would become a public directory of everyone who ever logged in.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such contributor")
    summary = summary_for(db, user_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="No such contributor")
    name = public_name(user)
    return {
        "user_id": user.id,
        "name": name,
        "anonymous": name is None,
        # The iD is an identity, so it travels with the name or not at all --
        # publishing it for someone who withheld their name would name them.
        "orcid": user.orcid if name else None,
        **summary,
    }


@router.get("/contributors/{user_id}/annotations")
async def contributor_annotations(
    user_id: int,
    status: str | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: Session = Depends(get_session),
):
    """That contributor's contributed work, newest first, with its specimens.

    Drafts are private working state and are excluded here the same way the
    ranking excludes them -- this is the published record of what someone
    contributed, not a window into what they are still typing.
    """
    conds = [Annotation.contributor_id == user_id, Annotation.status != "draft"]
    if status:
        if status == "draft":
            raise HTTPException(status_code=400, detail="Drafts are not public")
        conds.append(Annotation.status == status)

    user = db.get(User, user_id)
    total, rows = _page(db, conds, limit, offset)
    # One name lookup for the page, not one per row: every row here has the same
    # contributor (cf. `api/annotations._out`, which cannot make that assumption).
    name = public_name(user)
    items = [_serialize(a, name) for a in rows]
    await attach_records(items)
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/annotations/mine")
async def my_annotations(
    status: str | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    user: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    """Everything the signed-in contributor has written, drafts included.

    ``summary`` is a real GROUP BY over all of their rows, so the totals stay
    right past the end of the page -- the Dashboard's counts were a filter over
    whichever 500 rows it happened to fetch.
    """
    base = [Annotation.contributor_id == user.id]
    conds = base + ([Annotation.status == status] if status else [])
    total, rows = _page(db, conds, limit, offset)

    name = public_name(user)
    items = [_serialize(a, name) for a in rows]
    await attach_records(items)

    return {"total": total, "items": items, "limit": limit, "offset": offset,
            "summary": status_counts(db, base)}
