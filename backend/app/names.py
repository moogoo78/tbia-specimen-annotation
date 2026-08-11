"""Matching a written-down name to a collector.

Shared by the sampling-event seeder and the story endpoints, which face the same
problem from two directions: a name printed in a published source has to be tied
to a ``Collector`` row, or left alone.

Deliberately conservative. Folding closes 'R. Fortune' vs 'R.Fortune' and no
more — anything fuzzier risks tying a historical figure to an unrelated modern
collector, which is worse than leaving the name unresolved.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select

from .models import Collector, CollectorAlias


def fold(name: str) -> str:
    """Fold a name for comparison: NFKC, case, and all spacing/punctuation."""
    s = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"[\s.,;:'\-()\[\]]+", "", s)


def collector_index(db) -> dict[str, int]:
    """Folded name -> collector id, from aliases and canonical names.

    Canonical names are indexed last so they win a collision with a raw alias
    string, which may carry a whole party ('A, B') rather than one person.
    """
    idx: dict[str, int] = {}
    for raw, cid in db.execute(
        select(CollectorAlias.recorded_by, CollectorAlias.collector_id)
    ).all():
        idx.setdefault(fold(raw), cid)
    for c in db.execute(select(Collector)).scalars():
        for n in (c.name, c.name_en):
            if n:
                idx[fold(n)] = c.id
    idx.pop("", None)
    return idx
