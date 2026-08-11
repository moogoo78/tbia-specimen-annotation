"""The taxonomic index: every distinct scientific_name in the occurrence store.

This lists *names as the store holds them*, not taxa. Nothing here reconciles
against TaiCOL, WCVP or any other checklist: synonyms are not merged, spelling
and gender variants stay separate rows, and a name used under two kingdoms is
one row covering every record carrying the string. See
`openspec/specs/species-browse/spec.md`.

The whole index is one grouped scan (~2.2s over 2.08M rows, of which the modal
descriptive columns are ~1.2s), cached with a TTL and then searched, sorted and
paged in memory — the same shape as the collector board in `collectors.py`, and
for the same reason: DuckDB cannot page a grouped aggregate without computing
the entire grouping first, so paging in SQL would pay the full scan per request.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query

from .. import duck

router = APIRouter(prefix="/api", tags=["species"])

SCOPES = ("species", "all")
SORTS = ("records", "name")

_ROLLUP: list[dict] | None = None
_ROLLUP_AT = 0.0
_ROLLUP_TTL = 600.0
_lock = asyncio.Lock()

# Descriptive columns take the name's *most-numerous* value (`mode`), not an
# arbitrary one: a name whose records are 99% 植物界 should not be labelled by
# the one row that says otherwise. `n_kingdoms` exposes that disagreement so the
# UI can mark it instead of hiding it.
_ROLLUP_SQL = """
    SELECT scientific_name                                  AS name,
           count(*)                                         AS n_records,
           count(*) FILTER (WHERE has_identification)        AS n_identified,
           mode(taxon_rank)                                 AS taxon_rank,
           mode(family)                                     AS family,
           mode(genus)                                      AS genus,
           mode(kingdom_c)                                  AS kingdom_c,
           mode(common_name_c)                              AS common_name_c,
           count(DISTINCT county)                           AS n_counties,
           count(DISTINCT kingdom_c)                        AS n_kingdoms,
           min(year)                                        AS year_min,
           max(year)                                        AS year_max,
           count(*) FILTER (WHERE has_coordinates)          AS n_geo,
           count(*) FILTER (WHERE has_media)                AS n_media,
           count(*) FILTER (WHERE type_status IS NOT NULL
                              AND type_status <> '')        AS n_type
    FROM occurrence
    WHERE scientific_name IS NOT NULL AND scientific_name <> ''
    GROUP BY scientific_name
"""


async def _rollup_rows() -> list[dict]:
    """Every named taxon in the store with its counts. Cached with a TTL."""
    global _ROLLUP, _ROLLUP_AT
    async with _lock:
        if _ROLLUP is not None and time.monotonic() - _ROLLUP_AT < _ROLLUP_TTL:
            return _ROLLUP
        rows = await duck.query(_ROLLUP_SQL)
        for r in rows:
            # Blank rather than null keeps the search predicate and the client
            # from having to special-case a missing name.
            r["common_name_c"] = r["common_name_c"] or ""
            r["taxon_rank"] = r["taxon_rank"] or ""
        _ROLLUP, _ROLLUP_AT = rows, time.monotonic()
        return rows


@router.get("/species")
async def list_species(
    q: str | None = Query(default=None, description="substring match on scientific / common name"),
    scope: str = Query(default="species", description=" | ".join(SCOPES)),
    sort: str = Query(default="records", description=" | ".join(SORTS)),
    order: str = Query(default="desc", description="asc | desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """The store's distinct scientific names, most-collected first.

    ``scope=species`` (the default) lists the names that carry at least one
    record flagged ``has_identification`` — rank species-or-below with a name;
    ``scope=all`` adds the genus- and family-level identifications, which
    are not noise but the identification gap itself — 319,916 records stop at a
    bare genus and 123,821 at a family.

    ``total`` counts the names matching the current scope and search, not the
    page. ``totals`` describes the whole index, so the page can say what
    fraction of it is in view.
    """
    if scope not in SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of {SCOPES}")
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of {SORTS}")

    rows = await _rollup_rows()
    totals = {"names": len(rows), "records": sum(r["n_records"] for r in rows)}

    # "Identified to species" is not re-defined here: `has_identification` already
    # means exactly "rank is species-or-below and a name is present"
    # (`ingest/prepare.py`, via `ingest.common.SPECIES_RANKS`). Filtering on the
    # flag rather than on a second copy of the rank list keeps the index and the
    # completeness gap from ever disagreeing about what counts as identified.
    pool = rows if scope == "all" else [r for r in rows if r["n_identified"] > 0]
    if q and q.strip():
        needle = q.strip().lower()
        pool = [
            r for r in pool
            if needle in r["name"].lower() or needle in r["common_name_c"].lower()
        ]

    desc = order.lower() != "asc"
    if sort == "name":
        pool = sorted(pool, key=lambda r: r["name"], reverse=desc)
    else:
        # Name breaks ties so paging is deterministic: 9,104 names hold exactly
        # one record, and an unstable order would repeat or skip them.
        pool = sorted(pool, key=lambda r: (-r["n_records"] if desc else r["n_records"], r["name"]))

    return {
        "total": len(pool),
        "items": pool[offset:offset + limit],
        "limit": limit,
        "offset": offset,
        "scope": scope,
        "totals": totals,
    }
