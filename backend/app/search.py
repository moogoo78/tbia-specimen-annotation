"""Filter / facet / detail SQL over the DuckDB occurrence store.

One ``build_where`` produces the WHERE clause + params shared by the result
list, the total count, and the facet-count queries, so every view applies the
same filter consistently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import duck, media

# The ETL's occurrence table. Read-only here; `ingest/prepare.py` adds the
# completeness flags this module filters and sorts on.
TABLE = "occurrence"

# standard_date arrives as a TIMESTAMP; the platform only ever deals in whole
# days, so every read narrows it to a DATE.
DATE_EXPR = "CAST(standard_date AS DATE)"
DATE_COL = f"{DATE_EXPR} AS standard_date"

# Columns returned in list/grid/table rows (kept lean for ~1.8M-row scans).
LIST_COLUMNS = [
    "id", "catalog_number", "scientific_name", "name_author", "common_name_c",
    "family", "genus", "taxon_rank", "bio_group", "kingdom_c", "county", "locality",
    "standard_latitude", "standard_longitude", DATE_COL, "year", "type_status",
    "dataset_name", "institution_code", "institution_name", "recorded_by", "record_number",
    "has_coordinates", "has_date", "has_identification", "has_media",
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

# A facet value meaning "the column is empty" (NULL or ''). It travels as an
# ordinary value — through the URL, the API and back — so the panel can offer
# it as one more checkbox. Only the facets listed here emit it; the filter
# understands it on any column.
NONE_VALUE = "__none__"
NONE_FACETS = {"basis_of_record"}

SORTABLE = {
    "completeness_score": "completeness_score",
    "standard_date": "standard_date",
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
    # Exact name match, for the species index's link into Explore. Deliberately
    # not a facet — the store holds 44,874 distinct names.
    scientific_name: list[str] = field(default_factory=list)
    basis_of_record: list[str] = field(default_factory=list)
    type_status: list[str] = field(default_factory=list)
    dataset_name: list[str] = field(default_factory=list)
    tbia_dataset_id: list[str] = field(default_factory=list)
    collector_id: list[int] = field(default_factory=list)
    # "Kingdom/rank/Name" — see app/taxa.py. ORed: picking Rosaceae and
    # Fagaceae means records in either.
    taxon: list[str] = field(default_factory=list)
    record_number_from: int | None = None
    record_number_to: int | None = None
    record_number: str | None = None  # substring match, for non-numeric numbers
    # Specimen lookup: "HAST 334", "A:0023434", a bare number, or a pasted list
    # ("BM [001015554]; isotype: A [00038750]"). See `parse_catalog_refs`.
    catalog: str | None = None
    missing_coordinates: bool = False
    missing_date: bool = False
    missing_identification: bool = False
    has_media: bool = False
    year_from: int | None = None
    year_to: int | None = None
    # Finer than year — a collecting trip is a date range. ISO "YYYY-MM-DD".
    date_from: str | None = None
    date_to: str | None = None
    bbox: str | None = None  # "minLon,minLat,maxLon,maxLat"


def _in_clause(col: str, values: list[Any], where: list[str], params: list[Any]) -> None:
    if not values:
        return
    real = [v for v in values if v != NONE_VALUE]
    terms = []
    if real:
        terms.append(f"{col} IN ({', '.join(['?'] * len(real))})")
        params.extend(real)
    if len(real) < len(values):
        terms.append(f"({col} IS NULL OR {col} = '')")
    where.append(terms[0] if len(terms) == 1 else f"({' OR '.join(terms)})")


def _collector_aliases(collector_ids: list[int]) -> list[str]:
    """Raw recorded_by strings mapped to the given collectors (Python-side
    fallback for when the annotations sqlite is not ATTACHed to DuckDB)."""
    from sqlalchemy import select

    from .db import RefSessionLocal
    from .models import CollectorAlias

    with RefSessionLocal() as db:
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
    if duck.reference_attached():
        ph = ", ".join(["?"] * len(ids))
        where.append(
            "recorded_by IN "
            f"(SELECT recorded_by FROM ref.collector_alias WHERE collector_id IN ({ph}))"
        )
        params.extend(ids)
    else:
        aliases = _collector_aliases(ids)
        if aliases:
            _in_clause("recorded_by", aliases, where, params)
        else:
            where.append("FALSE")  # selected collector has no mapped values


# "CODE<sep>NUMBER": a herbarium/museum code, then ':' / whitespace / '-', then
# the rest. The code must start with a letter so "000062-00018" stays one number.
_CATALOG_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)\s*[:\s-]\s*(\S.*?)\s*$")
# "BM [001015554]" — how JSTOR Global Plants and protologues cite a sheet.
_BRACKET_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*\[\s*([^\]]+?)\s*\]")
# A type-status label in front of a reference ("isotype:", "Holotype -"), which
# names what the sheet is, not where it is. Only words ending in "type", so a
# real code followed by a colon ("HAST: 334") is never mistaken for one.
_LABEL_RE = re.compile(r"^\s*[A-Za-z]*types?\s*[:\-]\s*", re.IGNORECASE)
# References between these. Never ':' or whitespace — those separate a code
# from its number.
_SPLIT_RE = re.compile(r"[;,\n\r]+")
# A pasted list is a lookup, not a bulk export: bound what one request scans for.
MAX_CATALOG_REFS = 50


def _norm(s: str) -> str:
    """Upper-case, punctuation and whitespace removed — the SQL `_NORM` in Python."""
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def parse_catalog(term: str) -> tuple[str | None, str]:
    """Split one specimen reference into (institution code, catalog number).

    "HAST 334" -> ("HAST", "334"); "A:0023434" -> ("A", "0023434");
    "BM [001015554]" -> ("BM", "001015554"); "0023434" -> (None, "0023434")."""
    m = _BRACKET_RE.fullmatch(term.strip()) or _CATALOG_RE.match(term)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return None, term.strip()


def parse_catalog_refs(text: str | None) -> list[tuple[str | None, str]]:
    """Every specimen reference in a pasted citation, in order, deduplicated.

    "BM [001015554]; isotype: A [00038750], K [000644915]" ->
    [("BM", "001015554"), ("A", "00038750"), ("K", "000644915")].
    Bracketed references are taken wherever they sit, so the prose around them
    ("isotype:") falls away; whatever is left is split on ; , and newlines."""
    if not text:
        return []
    refs = [(m.group(1).upper(), m.group(2).strip()) for m in _BRACKET_RE.finditer(text)]
    for seg in _SPLIT_RE.split(_BRACKET_RE.sub(";", text)):
        seg = _LABEL_RE.sub("", seg).strip()
        if _norm(seg):
            refs.append(parse_catalog(seg))
    seen: set[tuple[str | None, str]] = set()
    out = []
    for code, num in refs:
        key = (code, _norm(num).lstrip("0") or _norm(num))
        if key not in seen and _norm(num):
            seen.add(key)
            out.append((code, num))
    return out[:MAX_CATALOG_REFS]


def format_ref(code: str | None, num: str) -> str:
    return f"{code} {num}" if code else num


# catalog_number with everything but letters/digits dropped, upper-cased, so
# "A:0023434", "A 0023434" and "a-0023434" are one key.
_NORM = "upper(regexp_replace(coalesce(catalog_number, ''), '[^A-Za-z0-9]', '', 'g'))"


def _ref_condition(code: str | None, num: str) -> tuple[str, list[Any]]:
    """SQL matching one reference.

    The code people cite lives in three places in this export, so all three are
    tried: TBIA's partner code (`institution_code`: TAIF, NMNS), the collection
    code (`dataset_code`: HAST, TAI, TNM — the herbarium acronym), or embedded
    in the catalog number itself (GBIF rows: "BM001015554", "A:TAI-4114").
    Numbers compare with leading zeros stripped, so "HAST 0000334" finds 334.
    Exact rather than substring: this is a lookup, and free-text `q` already
    does substring over catalog_number."""
    num_key = _norm(num).lstrip("0")
    # Code and number as one stored value ("A:0023434" stored literally).
    terms = [f"{_NORM} = ?"]
    params: list[Any] = [_norm((code or "") + num)]
    if code:
        terms.append(
            "((upper(institution_code) = ? OR upper(dataset_code) = ?)"
            f" AND ltrim({_NORM}, '0') = ?)"
        )
        params.extend([code, code, num_key])
        # Code embedded in the number, leading zeros after it ignored:
        # "A:23434" finds a stored "A:0023434".
        terms.append(f"(starts_with({_NORM}, ?) AND ltrim(substr({_NORM}, ?), '0') = ?)")
        params.extend([code, len(code) + 1, num_key])
    else:
        terms.append(f"ltrim({_NORM}, '0') = ?")
        params.append(num_key)
    return f"({' OR '.join(terms)})", params


def _catalog_clause(text: str | None, where: list[str], params: list[Any]) -> None:
    """Records matching any reference in `text` (see `parse_catalog_refs`)."""
    refs = parse_catalog_refs(text)
    if not refs:
        return
    conds = []
    for code, num in refs:
        sql, p = _ref_condition(code, num)
        conds.append(sql)
        params.extend(p)
    where.append(conds[0] if len(conds) == 1 else f"({' OR '.join(conds)})")


async def catalog_matches(text: str | None) -> list[dict]:
    """Per-reference hit counts for a pasted list, in one scan — so the page can
    say which references found nothing, rather than leave someone who pasted
    four and got two working out which two."""
    refs = parse_catalog_refs(text)
    if not refs:
        return []
    cols, params = [], []
    for i, (code, num) in enumerate(refs):
        sql, p = _ref_condition(code, num)
        cols.append(f"count(*) FILTER (WHERE {sql}) AS n{i}")
        params.extend(p)
    row = await duck.query_one(f"SELECT {', '.join(cols)} FROM {TABLE}", params)
    return [
        {"ref": format_ref(code, num), "n": row[f"n{i}"]}
        for i, (code, num) in enumerate(refs)
    ]


def _taxon_clause(values: list[str], where: list[str], params: list[Any]) -> None:
    from .taxa import MAX_TAXA, taxon_condition

    if not values:
        return
    conds = []
    for v in values[:MAX_TAXA]:
        c = taxon_condition(v)
        if c:
            conds.append(c[0])
            params.extend(c[1])
    # Asked for taxa and none parsed: match nothing rather than everything.
    where.append(f"({' OR '.join(conds)})" if conds else "FALSE")


def build_where(f: Filters) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    _in_clause("bio_group", f.bio_group, where, params)
    _in_clause("kingdom_c", f.kingdom_c, where, params)
    _in_clause("county", f.county, where, params)
    _in_clause("taxon_rank", f.taxon_rank, where, params)
    _in_clause("scientific_name", f.scientific_name, where, params)
    _in_clause("basis_of_record", f.basis_of_record, where, params)
    _in_clause("type_status", f.type_status, where, params)
    _in_clause("dataset_name", f.dataset_name, where, params)
    _in_clause("tbia_dataset_id", f.tbia_dataset_id, where, params)
    _collector_clause(f.collector_id, where, params)
    _taxon_clause(f.taxon, where, params)

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

    # Text record number, for the many that aren't numbers at all ("TAI-9",
    # "陳-123") and so can never match the range above. Substring/ILIKE, like
    # the rest of the free-text search.
    if f.record_number and f.record_number.strip():
        where.append("record_number ILIKE ?")
        params.append(f"%{f.record_number.strip()}%")

    _catalog_clause(f.catalog, where, params)

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

    # Inclusive on both ends, compared as DATE so a TIMESTAMP time-of-day can't
    # push a record out of its own trip.
    if f.date_from:
        where.append(f"{DATE_EXPR} >= CAST(? AS DATE)")
        params.append(f.date_from)
    if f.date_to:
        where.append(f"{DATE_EXPR} <= CAST(? AS DATE)")
        params.append(f.date_to)

    if f.bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = (float(x) for x in f.bbox.split(","))
            where.append(
                "standard_longitude BETWEEN ? AND ? AND standard_latitude BETWEEN ? AND ?"
            )
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
    total = (await duck.query_one(f"SELECT count(*) AS n FROM {TABLE}{where}", params))["n"]
    items = await duck.query(
        f"SELECT {cols} FROM {TABLE}{where} ORDER BY {order_by} LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    # Surface the first media URL as a lightweight thumbnail for the grid view;
    # drop the raw (multi-URL, ';'-packed) string to keep the payload lean.
    for row in items:
        media = parse_media(row.pop("associated_media", None))
        row["thumbnail"] = media[0] if media else None
    return {"total": total, "items": items, "limit": limit, "offset": offset}


async def queue(f: Filters, *, limit: int) -> dict:
    """A random draw from the rows matching ``f`` — the landing page's queue.

    ``ORDER BY random()`` rather than a random OFFSET: DuckDB answers it in
    ~80ms over the whole gap pool, where paging that far into a sorted 2M-row
    scan costs half a second. A random draw has no stable order, so there is no
    ``offset`` — every call is a fresh sample, which is the point.

    ``total`` is the size of the pool drawn from, not of the draw, so the page
    can say how much is waiting behind the few records it is showing.
    """
    where, params = build_where(f)
    cols = ", ".join(LIST_COLUMNS)
    total = (await duck.query_one(f"SELECT count(*) AS n FROM {TABLE}{where}", params))["n"]
    items = await duck.query(
        f"SELECT {cols} FROM {TABLE}{where} ORDER BY random() LIMIT ?",
        params + [limit],
    )
    for row in items:
        media = parse_media(row.pop("associated_media", None))
        row["thumbnail"] = media[0] if media else None
    return {"total": total, "items": items, "limit": limit}


async def facets(f: Filters, *, top: int = 20) -> dict:
    """Counts per facet value for the current filter, plus completeness gap counts."""
    where, params = build_where(f)
    out: dict[str, Any] = {}

    for name, col in FACET_COLUMNS.items():
        limit = 50 if name in ("dataset_name", "county") else top
        joiner = " AND " if where else " WHERE "
        if name in NONE_FACETS:
            # Empties fold into one NONE_VALUE row instead of being dropped.
            rows = await duck.query(
                f"SELECT coalesce(nullif({col}, ''), '{NONE_VALUE}') AS value,"
                f" count(*) AS count FROM {TABLE}{where}"
                f" GROUP BY 1 ORDER BY count DESC LIMIT {limit}",
                params,
            )
        else:
            rows = await duck.query(
                f"SELECT {col} AS value, count(*) AS count FROM {TABLE}{where}"
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
            FROM {TABLE}{where}""",
        params,
    )
    out["completeness"] = gaps
    return out


async def get_detail(occ_id: str) -> dict | None:
    row = await duck.query_one(
        f"SELECT * REPLACE ({DATE_EXPR} AS standard_date) FROM {TABLE} WHERE id = ?",
        [occ_id],
    )
    if row is None:
        return None
    row["media"] = parse_media(row.get("associated_media"))
    # Other renditions of those same images, when the source publishes them
    # (app/media.py). Sent from here rather than derived in the browser so one
    # file decides what a size name means; `[]` for every source without a rule,
    # which is what makes the picker absent rather than broken.
    row["media_sizes"] = media.sizes_for(row["media"])
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
