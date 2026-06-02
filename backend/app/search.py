"""Filter / facet / detail SQL over the DuckDB occurrence store.

One ``build_where`` produces the WHERE clause + params shared by the result
list, the total count, and the facet-count queries, so every view applies the
same filter consistently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import duck

# Columns returned in list/grid/table rows (kept lean for 2M-row scans).
LIST_COLUMNS = [
    "id", "catalog_number", "scientific_name", "name_author", "common_name_c",
    "family", "genus", "taxon_rank", "bio_group", "kingdom_c", "county", "locality",
    "std_lat", "std_lon", "std_date", "year", "type_status", "dataset_name",
    "recorded_by", "record_number", "has_coordinates", "has_date", "has_identification", "has_media",
    "completeness_score", "associated_media",
]

# Free-text search target columns (substring/ILIKE; CJK + Latin).
SEARCH_COLUMNS = [
    "scientific_name", "common_name_c", "alternative_name_c", "source_vernacular_name",
    "locality", "county", "dataset_name", "recorded_by", "catalog_number", "family",
    "genus",
]

# Facet dimension -> column.
FACET_COLUMNS = {
    "bio_group": "bio_group",
    "kingdom_c": "kingdom_c",
    "county": "county",
    "taxon_rank": "taxon_rank",
    "basis_of_record": "basis_of_record",
    "type_status": "type_status",
    "dataset_name": "dataset_name",
}

SORTABLE = {
    "completeness_score": "completeness_score",
    "std_date": "std_date",
    "scientific_name": "scientific_name",
    "catalog_number": "catalog_number",
    "county": "county",
    "dataset_name": "dataset_name",
}


@dataclass
class Filters:
    q: str | None = None
    bio_group: list[str] = field(default_factory=list)
    kingdom_c: list[str] = field(default_factory=list)
    county: list[str] = field(default_factory=list)
    taxon_rank: list[str] = field(default_factory=list)
    basis_of_record: list[str] = field(default_factory=list)
    type_status: list[str] = field(default_factory=list)
    dataset_name: list[str] = field(default_factory=list)
    tbia_dataset_id: list[str] = field(default_factory=list)
    collector_id: list[int] = field(default_factory=list)
    record_number_from: int | None = None
    record_number_to: int | None = None
    missing_coordinates: bool = False
    missing_date: bool = False
    missing_identification: bool = False
    has_media: bool = False
    year_from: int | None = None
    year_to: int | None = None
    bbox: str | None = None  # "minLon,minLat,maxLon,maxLat"


def _in_clause(col: str, values: list[Any], where: list[str], params: list[Any]) -> None:
    if values:
        placeholders = ", ".join(["?"] * len(values))
        where.append(f"{col} IN ({placeholders})")
        params.extend(values)


def _collector_aliases(collector_ids: list[int]) -> list[str]:
    """Raw recorded_by strings mapped to the given collectors (Python-side
    fallback for when the annotations sqlite is not ATTACHed to DuckDB)."""
    from sqlalchemy import select

    from .db import SessionLocal
    from .models import CollectorAlias

    with SessionLocal() as db:
        return list(
            db.execute(
                select(CollectorAlias.recorded_by).where(
                    CollectorAlias.collector_id.in_(collector_ids)
                )
            ).scalars()
        )


def _collector_clause(ids: list[int], where: list[str], params: list[Any]) -> None:
    """Filter occurrences to those collected by the given collector(s), matching
    on the raw recorded_by value via the collector_alias map."""
    if not ids:
        return
    if duck.annotations_attached():
        ph = ", ".join(["?"] * len(ids))
        where.append(
            "recorded_by IN "
            f"(SELECT recorded_by FROM ann.collector_alias WHERE collector_id IN ({ph}))"
        )
        params.extend(ids)
    else:
        aliases = _collector_aliases(ids)
        if aliases:
            _in_clause("recorded_by", aliases, where, params)
        else:
            where.append("FALSE")  # selected collector has no mapped values


def build_where(f: Filters) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    _in_clause("bio_group", f.bio_group, where, params)
    _in_clause("kingdom_c", f.kingdom_c, where, params)
    _in_clause("county", f.county, where, params)
    _in_clause("taxon_rank", f.taxon_rank, where, params)
    _in_clause("basis_of_record", f.basis_of_record, where, params)
    _in_clause("type_status", f.type_status, where, params)
    _in_clause("dataset_name", f.dataset_name, where, params)
    _in_clause("tbia_dataset_id", f.tbia_dataset_id, where, params)
    _collector_clause(f.collector_id, where, params)

    # Numeric record-number range. record_number is varchar, so cast (non-numeric
    # values become NULL and fall outside any range).
    if f.record_number_from is not None or f.record_number_to is not None:
        expr = "TRY_CAST(record_number AS BIGINT)"
        if f.record_number_from is not None and f.record_number_to is not None:
            where.append(f"{expr} BETWEEN ? AND ?")
            params.extend([f.record_number_from, f.record_number_to])
        elif f.record_number_from is not None:
            where.append(f"{expr} >= ?")
            params.append(f.record_number_from)
        else:
            where.append(f"{expr} <= ?")
            params.append(f.record_number_to)

    if f.missing_coordinates:
        where.append("has_coordinates = FALSE")
    if f.missing_date:
        where.append("has_date = FALSE")
    if f.missing_identification:
        where.append("has_identification = FALSE")
    if f.has_media:
        where.append("has_media = TRUE")

    if f.year_from is not None:
        where.append("year >= ?")
        params.append(f.year_from)
    if f.year_to is not None:
        where.append("year <= ?")
        params.append(f.year_to)

    if f.bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(x) for x in f.bbox.split(","))
            where.append("std_lon BETWEEN ? AND ? AND std_lat BETWEEN ? AND ?")
            params.extend([min_lon, max_lon, min_lat, max_lat])
        except (ValueError, TypeError):
            pass

    if f.q:
        like = f"%{f.q.strip()}%"
        ors = " OR ".join(f"{c} ILIKE ?" for c in SEARCH_COLUMNS)
        where.append(f"({ors})")
        params.extend([like] * len(SEARCH_COLUMNS))

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


async def search(f: Filters, *, sort: str, order: str, limit: int, offset: int) -> dict:
    where, params = build_where(f)

    sort_col = SORTABLE.get(sort, "completeness_score")
    order_sql = "DESC" if order.lower() == "desc" else "ASC"
    # NULLS LAST keeps blank dates/names out of the way regardless of direction.
    order_by = f"{sort_col} {order_sql} NULLS LAST, id ASC"

    cols = ", ".join(LIST_COLUMNS)
    total = (await duck.query_one(f"SELECT count(*) AS n FROM occurrences{where}", params))["n"]
    items = await duck.query(
        f"SELECT {cols} FROM occurrences{where} ORDER BY {order_by} LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    # Surface the first media URL as a lightweight thumbnail for the grid view;
    # drop the raw (multi-URL, ';'-packed) string to keep the payload lean.
    for row in items:
        media = parse_media(row.pop("associated_media", None))
        row["thumbnail"] = media[0] if media else None
    return {"total": total, "items": items, "limit": limit, "offset": offset}


async def facets(f: Filters, *, top: int = 20) -> dict:
    """Counts per facet value for the current filter, plus completeness gap counts."""
    where, params = build_where(f)
    out: dict[str, Any] = {}

    for name, col in FACET_COLUMNS.items():
        limit = 50 if name in ("dataset_name", "county") else top
        joiner = " AND " if where else " WHERE "
        rows = await duck.query(
            f"SELECT {col} AS value, count(*) AS count FROM occurrences{where}"
            f"{joiner}{col} IS NOT NULL AND {col} <> '' "
            f"GROUP BY {col} ORDER BY count DESC LIMIT {limit}",
            params,
        )
        out[name] = rows

    gaps = await duck.query_one(
        f"""SELECT
              sum(CASE WHEN NOT has_coordinates THEN 1 ELSE 0 END)    AS missing_coordinates,
              sum(CASE WHEN NOT has_date THEN 1 ELSE 0 END)           AS missing_date,
              sum(CASE WHEN NOT has_identification THEN 1 ELSE 0 END) AS missing_identification,
              sum(CASE WHEN has_media THEN 1 ELSE 0 END)              AS has_media,
              count(*)                                                AS total
            FROM occurrences{where}""",
        params,
    )
    out["completeness"] = gaps
    return out


async def get_detail(occ_id: str) -> dict | None:
    row = await duck.query_one("SELECT * FROM occurrences WHERE id = ?", [occ_id])
    if row is None:
        return None
    row["media"] = parse_media(row.get("associated_media"))
    return row


def parse_media(value: str | None) -> list[str]:
    if not value:
        return []
    # TBIA packs media URLs separated by ';', ',', '|' or whitespace.
    parts: list[str] = []
    for chunk in value.replace("|", " ").replace(";", " ").replace(",", " ").split():
        chunk = chunk.strip()
        if chunk.startswith("http"):
            parts.append(chunk)
    return parts
