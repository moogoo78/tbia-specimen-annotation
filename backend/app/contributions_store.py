"""What one contributor has done — counted, and put back beside its specimens.

Two things live here rather than in a router, for the same reason
``annotations_store`` does: more than one endpoint needs them, and if each built
its own the numbers would drift.

- ``count_columns`` is the single definition of what a contribution *count*
  means. The ranking board (``api/volunteers``) and a contributor's own profile
  (``api/contributions``) both select it, so the figure on a board row and the
  figure on the page that row opens cannot disagree.
- ``attach_records`` is how an annotation gets its specimen back. The rows live
  in SQLite and the specimens live in DuckDB, and the join between them is
  deliberately *not* the federated one in ``api/export`` -- see below.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from . import duck
from .models import Annotation

#: Reviewed into the provider export. "Accepted" on screen means both.
ACCEPTED = ("accepted", "merged")


def count_columns() -> tuple[Any, Any, Any]:
    """``(n_submitted, n_accepted, n_records)`` as labelled aggregate columns.

    A volunteer who fills eight fields on one specimen and one who improves eight
    specimens both show their real shape, which is why records is counted
    separately from rows. Drafts are private working state and are excluded by
    every caller's WHERE clause, not here.
    """
    return (
        func.count().label("n_submitted"),
        func.count().filter(Annotation.status.in_(ACCEPTED)).label("n_accepted"),
        func.count(distinct(Annotation.occurrence_id)).label("n_records"),
    )


def summary_for(db: Session, user_id: int) -> dict[str, Any] | None:
    """One contributor's public standing, or None if they have contributed nothing.

    None is what makes a profile 404: an account that has signed in but never
    annotated has nothing to show, and inventing a page of zeroes for it would
    turn the user table into a directory of people.
    """
    n_submitted, n_accepted, n_records = count_columns()
    row = db.execute(
        select(n_submitted, n_accepted, n_records,
               func.min(Annotation.created).label("first"),
               func.max(Annotation.created).label("last"))
        .where(Annotation.contributor_id == user_id, Annotation.status != "draft")
    ).one()
    if not row.n_submitted:
        return None
    return {
        "n_submitted": row.n_submitted,
        "n_accepted": row.n_accepted,
        "n_records": row.n_records,
        "first": row.first.isoformat() if row.first else None,
        "last": row.last.isoformat() if row.last else None,
    }


def status_counts(db: Session, conds: list) -> dict[str, int]:
    """Per-status totals over *every* matching row, plus ``total``.

    A dashboard tile is a claim about all of someone's work, so it cannot be a
    count of whichever page happened to be fetched -- which is what it was: the
    UI pulled 500 rows and filtered them in the browser, so every number was
    silently wrong from row 501 on and there was nothing on screen to say so.

    Callers pass the conditions *without* their status filter, so the breakdown
    stays whole while the list beneath it is narrowed to one status.
    """
    rows = db.execute(
        select(Annotation.status, func.count()).where(*conds).group_by(Annotation.status)
    ).all()
    counts = {status: n for status, n in rows}
    counts["total"] = sum(counts.values())
    return counts


async def attach_records(rows: list[dict[str, Any]]) -> None:
    """Fill ``scientific_name`` / ``catalog_number`` onto serialized annotations.

    A contribution list that names only a field and a dataset does not tell you
    *which specimen* you improved, so the specimen has to come back with it.

    This is one bounded lookup for the page's own occurrence ids, not the
    federated ``JOIN occurrence`` in ``api/export``. Paging and ordering stay in
    SQLite, where the rows live and ``contributor_id`` is indexed -- a join
    across the two stores would have to compute the whole grouping to page it.
    It also reads only ``occurrence``, so it needs no ``annotations_attached()``
    guard and no Python fallback branch, and an id that a re-ingested store no
    longer holds comes back null instead of silently dropping the row the way an
    inner join would.

    Mutates in place; the keys are always present afterwards, even on a miss.
    """
    for r in rows:
        r["scientific_name"] = None
        r["catalog_number"] = None
    ids = sorted({r["occurrence_id"] for r in rows if r.get("occurrence_id")})
    if not ids:
        return
    placeholders = ", ".join(["?"] * len(ids))
    found = await duck.query(
        f"SELECT id, scientific_name, catalog_number FROM occurrence WHERE id IN ({placeholders})",
        list(ids),
    )
    by_id = {o["id"]: o for o in found}
    for r in rows:
        o = by_id.get(r["occurrence_id"])
        if o:
            r["scientific_name"] = o["scientific_name"]
            r["catalog_number"] = o["catalog_number"]
