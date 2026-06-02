"""Ingest a *subset* of the TBIA occurrence CSV into a DuckDB database.

Same loader as ``ingest_tbia.py`` (identical columns + completeness flags), but
keeps only rows whose ``tbiaDatasetID`` is one of a chosen set of dataset IDs.
The set comes from either ``registry.json`` (the platform's source of truth, via
``--registry``) or a plain text file of IDs (one per line, via ``--ids``).

Usage:
    # Restrict the store to exactly the datasets listed in registry.json:
    python -m ingest.ingest_filtered --registry ../data/registry.json

    # Or from an explicit ID list:
    python -m ingest.ingest_filtered \
        --zip ../tbia_6a0e923aedaba100178348b8.zip \
        --ids ../selected-13-dataset-ids.txt \
        --db ../data/occurrences.duckdb

Exactly one of --registry / --ids is required. --db defaults to
data/occurrences.duckdb.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import duckdb

from ingest.ingest_tbia import (
    COLUMNS,
    DEFAULT_DB,
    REPO,
    SPECIES_RANKS,
    ensure_csv,
    find_zip,
)

DEFAULT_REGISTRY = os.path.join(REPO, "data", "registry.json")


def read_ids(path: str) -> list[str]:
    """Read selected tbia_dataset_id values (one per line; blanks/dupes dropped)."""
    if not os.path.exists(path):
        sys.exit(f"IDs file not found: {path}")
    seen: dict[str, None] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            v = line.strip()
            if v:
                seen[v] = None
    ids = list(seen)
    if not ids:
        sys.exit(f"No IDs found in {path}")
    return ids


def read_registry_ids(path: str) -> list[str]:
    """Collect every tbia_dataset_id listed in registry.json.

    The file is two-level: ``{institutions|aggregators: {CODE: {datasets:
    {<tbia_dataset_id>: {...}}}}}``. We union the dataset-id keys across both
    institutions and aggregators, preserving order and dropping duplicates.
    """
    if not os.path.exists(path):
        sys.exit(f"registry not found: {path}")
    with open(path, encoding="utf-8") as f:
        reg = json.load(f)
    seen: dict[str, None] = {}
    for section in ("institutions", "aggregators"):
        for src in reg.get(section, {}).values():
            for did in src.get("datasets", {}):
                seen[did] = None
    ids = list(seen)
    if not ids:
        sys.exit(f"No dataset ids found in {path}")
    return ids


def build_select(csv_path: str, ids: list[str], limit: int | None) -> str:
    read_csv = (
        f"read_csv('{csv_path}', header=true, all_varchar=true, "
        f"quote='\"', escape='\"', ignore_errors=true)"
    )
    projections = []
    for raw, target, expr in COLUMNS:
        c = f'"{raw}"'
        projections.append(f"{expr.format(c=c)} AS {target}")

    # Filter on the raw dataset-id column inside the scan (single-quotes escaped).
    id_list = ", ".join("'" + i.replace("'", "''") + "'" for i in ids)
    where = f'WHERE "tbiaDatasetID" IN ({id_list})'

    rank_list = ", ".join(f"'{r}'" for r in SPECIES_RANKS)
    flags = [
        "(std_lat IS NOT NULL AND std_lon IS NOT NULL) AS has_coordinates",
        "(std_date IS NOT NULL) AS has_date",
        f"(lower(trim(taxon_rank)) IN ({rank_list}) "
        "AND scientific_name IS NOT NULL AND trim(scientific_name) <> '') AS has_identification",
        "(associated_media IS NOT NULL AND trim(associated_media) <> '') AS has_media",
        "year(std_date) AS year",
    ]
    score = (
        "(CAST(has_coordinates AS INT) + CAST(has_date AS INT) "
        "+ CAST(has_identification AS INT) + CAST(has_media AS INT)) AS completeness_score"
    )

    base = f"SELECT {', '.join(projections)} FROM {read_csv} {where}"
    if limit:
        base += f" LIMIT {limit}"
    with_flags = f"SELECT *, {', '.join(flags)} FROM ({base})"
    return f"SELECT *, {score} FROM ({with_flags})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", help="Path to tbia_*.zip (auto-detected if omitted)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--registry", nargs="?", const=DEFAULT_REGISTRY,
                     help="registry.json to scope by (every listed dataset id; "
                          f"defaults to {DEFAULT_REGISTRY} when given with no value)")
    src.add_argument("--ids", help="Text file of tbia_dataset_id values (one per line)")
    ap.add_argument("--db", default=DEFAULT_DB, help="Output DuckDB path")
    ap.add_argument("--limit", type=int, default=None, help="Row limit for a dev sample")
    args = ap.parse_args()

    zip_path = find_zip(args.zip)
    if args.registry:
        ids = read_registry_ids(args.registry)
        source_desc = args.registry
    else:
        ids = read_ids(args.ids)
        source_desc = args.ids
    print(f"Source zip : {zip_path}")
    print(f"Target DB  : {args.db}")
    print(f"Selected   : {len(ids)} dataset id(s) from {source_desc}")
    csv_path = ensure_csv(zip_path)

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)

    con = duckdb.connect(args.db)
    con.execute("PRAGMA threads=4")

    t0 = time.time()
    print("Loading matching occurrences ...")
    con.execute(f"CREATE TABLE occurrences AS {build_select(csv_path, ids, args.limit)}")
    n = con.execute("SELECT count(*) FROM occurrences").fetchone()[0]
    print(f"  loaded {n:,} rows in {time.time() - t0:.1f}s")
    if n == 0:
        print("  WARNING: no rows matched — check that the IDs match tbiaDatasetID values.")

    print("Indexing ...")
    for col in ("bio_group", "county", "dataset_name", "taxon_rank",
                "basis_of_record", "type_status", "completeness_score", "year"):
        con.execute(f"CREATE INDEX idx_occ_{col} ON occurrences({col})")
    con.execute("CREATE INDEX idx_occ_id ON occurrences(id)")

    print("Building datasets summary ...")
    con.execute(
        """
        CREATE TABLE datasets AS
        SELECT
            dataset_name,
            any_value(tbia_dataset_id)  AS tbia_dataset_id,
            any_value(rights_holder)    AS rights_holder,
            any_value(resource_contacts) AS resource_contacts,
            count(*)                                   AS n_records,
            sum(CAST(has_identification AS INT))       AS n_identified,
            sum(CAST(has_coordinates AS INT))          AS n_georeferenced,
            sum(CAST(has_date AS INT))                 AS n_dated,
            sum(CAST(has_media AS INT))                AS n_with_media,
            round(avg(completeness_score) / 4.0, 4)    AS avg_completeness
        FROM occurrences
        WHERE dataset_name IS NOT NULL AND dataset_name <> ''
        GROUP BY dataset_name
        ORDER BY n_records DESC
        """
    )
    nds = con.execute("SELECT count(*) FROM datasets").fetchone()[0]
    print(f"  {nds:,} datasets")

    # Report which requested IDs produced no rows.
    present = {r[0] for r in con.execute(
        "SELECT DISTINCT tbia_dataset_id FROM occurrences"
    ).fetchall()}
    missing = [i for i in ids if i not in present]
    if missing:
        print(f"  {len(missing)} requested id(s) had no rows: {', '.join(missing)}")

    con.close()
    print(f"Done in {time.time() - t0:.1f}s -> {args.db}")


if __name__ == "__main__":
    main()
