"""Public volunteer ranking — who has closed the most metadata gaps.

The only annotation-side endpoint that does *not* require a session: the point
is to recognise contributors publicly. Names are opt-in
(``users.show_in_ranking``); everyone else is returned without a name and shown
as "Contributor #<id>", so the board can be public without publishing anyone's
identity by default.

Aggregated in one GROUP BY over SQLite — never by counting rows client-side the
way the dashboard does.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session
from fastapi import Depends

from ..db import get_session
from ..models import Annotation, User

router = APIRouter(prefix="/api", tags=["volunteers"])

ACCEPTED = ("accepted", "merged")


def _month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/volunteers")
def volunteers(
    range: str = Query(default="all", pattern="^(all|month)$"),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_session),
):
    """Contributors ranked by accepted work.

    Ranked on accepted+merged annotations, with submitted and distinct records
    reported alongside — a volunteer who fills eight fields on one specimen and
    one who improves eight specimens both show their real shape.
    """
    n_submitted = func.count().label("n_submitted")
    n_accepted = func.count().filter(Annotation.status.in_(ACCEPTED)).label("n_accepted")
    n_records = func.count(distinct(Annotation.occurrence_id)).label("n_records")

    stmt = (
        select(User.id, User.display_name, User.show_in_ranking,
               n_submitted, n_accepted, n_records)
        .join(Annotation, Annotation.contributor_id == User.id)
        # Drafts are private working state — never counted, never ranked.
        .where(Annotation.status != "draft")
        .group_by(User.id)
        # Ties fall through records then submitted, then id, so the order is
        # stable across requests rather than whatever SQLite happens to return.
        .order_by(n_accepted.desc(), n_records.desc(), n_submitted.desc(), User.id)
        .limit(limit)
    )
    if range == "month":
        stmt = stmt.where(Annotation.created >= _month_start())

    rows = db.execute(stmt).all()
    return {
        "range": range,
        "items": [
            {
                "rank": i,
                "user_id": r.id,
                # Withheld unless the volunteer opted in — the display name must
                # not leave the server for anyone who hasn't.
                "name": r.display_name if r.show_in_ranking else None,
                "anonymous": not r.show_in_ranking,
                "n_submitted": r.n_submitted,
                "n_accepted": r.n_accepted,
                "n_records": r.n_records,
            }
            for i, r in enumerate(rows, 1)
        ],
    }
