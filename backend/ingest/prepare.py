"""Derive the app-facing columns on a freshly exported ``data/tbia.duckdb``.

The CSV → DuckDB extraction now happens in the TBIA ETL (see
``task-tbia-data-etl.md``), which produces two tables:

    occurrence  — one row per specimen record, raw TBIA column names
    dataset     — one row per tbia_dataset_id (name, institution, num_of_rows)

Neither carries the *completeness* flags the platform is built around, so this
step adds them in place:

  * ``occurrence`` gains ``has_coordinates / has_date / has_identification /
    has_media``, ``completeness_score`` (0–4) and ``year``, plus the indexes the
    facet and default-sort queries lean on.
  * ``dataset`` gains the matching per-dataset roll-ups
    (``n_identified / n_georeferenced / n_dated / n_with_media /
    avg_completeness``) that feed ``GET /api/datasets``.

It is idempotent — derived columns and indexes are dropped and rebuilt — so run
it after every ETL refresh:

    python -m ingest.prepare                     # data/tbia.duckdb
    python -m ingest.prepare --db ../data/x.duckdb
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import duckdb

from ingest.ingest_tbia import REPO, SPECIES_RANKS

DEFAULT_DB = os.path.join(REPO, "data", "tbia.duckdb")

# Derived occurrence columns: (name, type, SQL expression over the raw columns).
# Order matters — completeness_score reads the four flags written before it.
OCCURRENCE_DERIVED: list[tuple[str, str, str]] = [
    (
        "has_coordinates",
        "BOOLEAN",
        "standard_latitude IS NOT NULL AND standard_longitude IS NOT NULL",
    ),
    ("has_date", "BOOLEAN", "standard_date IS NOT NULL"),
    (
        "has_identification",
        "BOOLEAN",
        "lower(trim(taxon_rank)) IN ({ranks}) AND scientific_name IS NOT NULL "
        "AND trim(scientific_name) <> ''",
    ),
    (
        "has_media",
        "BOOLEAN",
        "associated_media IS NOT NULL AND trim(associated_media) <> ''",
    ),
    ("year", "INTEGER", "year(standard_date)"),
    (
        "completeness_score",
        "INTEGER",
        "CAST(has_coordinates AS INT) + CAST(has_date AS INT) "
        "+ CAST(has_identification AS INT) + CAST(has_media AS INT)",
    ),
]

# Derived dataset roll-ups: (name, type, aggregate over the occurrence rows).
DATASET_DERIVED: list[tuple[str, str, str]] = [
    ("n_identified", "BIGINT", "sum(CAST(has_identification AS INT))"),
    ("n_georeferenced", "BIGINT", "sum(CAST(has_coordinates AS INT))"),
    ("n_dated", "BIGINT", "sum(CAST(has_date AS INT))"),
    ("n_with_media", "BIGINT", "sum(CAST(has_media AS INT))"),
    ("avg_completeness", "DOUBLE", "round(avg(completeness_score) / 4.0, 4)"),
]

# Columns filtered/sorted/faceted on often enough to be worth an index.
INDEXED = (
    "bio_group", "county", "dataset_name", "taxon_rank", "basis_of_record",
    "type_status", "completeness_score", "year", "tbia_dataset_id", "id",
)


def _rebuild_columns(
    con: duckdb.DuckDBPyConnection, table: str, derived: list[tuple[str, str, str]]
) -> None:
    """Drop and re-add the derived columns so a re-run always recomputes them."""
    for name, sql_type, _ in derived:
        con.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS "{name}"')
        con.execute(f'ALTER TABLE {table} ADD COLUMN "{name}" {sql_type}')


def _require_tables(con: duckdb.DuckDBPyConnection) -> None:
    have = {r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables()"
    ).fetchall()}
    missing = {"occurrence", "dataset"} - have
    if missing:
        sys.exit(
            f"expected table(s) {', '.join(sorted(missing))} not found — "
            "is this a TBIA ETL export?"
        )


def prepare(db_path: str) -> None:
    if not os.path.exists(db_path):
        sys.exit(f"DuckDB not found: {db_path}")

    con = duckdb.connect(db_path)
    con.execute("PRAGMA threads=4")
    _require_tables(con)

    t0 = time.time()
    n = con.execute("SELECT count(*) FROM occurrence").fetchone()[0]
    print(f"Target DB  : {db_path}")
    print(f"Occurrence : {n:,} rows")

    # Indexes first: a column cannot be dropped while an index references it.
    print("Dropping stale indexes ...")
    for col in INDEXED:
        con.execute(f"DROP INDEX IF EXISTS idx_occ_{col}")

    print("Deriving completeness flags ...")
    ranks = ", ".join(f"'{r}'" for r in SPECIES_RANKS)
    _rebuild_columns(con, "occurrence", OCCURRENCE_DERIVED)
    for name, _, expr in OCCURRENCE_DERIVED:
        con.execute(f'UPDATE occurrence SET "{name}" = {expr.format(ranks=ranks)}')

    print("Indexing ...")
    for col in INDEXED:
        con.execute(f"CREATE INDEX idx_occ_{col} ON occurrence({col})")

    print("Rolling up per-dataset completeness ...")
    _rebuild_columns(con, "dataset", DATASET_DERIVED)
    aggs = ", ".join(f"{expr} AS {name}" for name, _, expr in DATASET_DERIVED)
    sets = ", ".join(f'"{name}" = s.{name}' for name, _, _ in DATASET_DERIVED)
    con.execute(
        f"""
        UPDATE dataset d SET {sets}
        FROM (
            SELECT tbia_dataset_id, {aggs}
            FROM occurrence GROUP BY tbia_dataset_id
        ) s
        WHERE s.tbia_dataset_id = d.tbia_dataset_id
        """
    )

    summ = con.execute(
        """
        SELECT round(100.0 * avg(CAST(has_identification AS INT)), 1),
               round(100.0 * avg(CAST(has_coordinates AS INT)), 1),
               round(100.0 * avg(CAST(has_date AS INT)), 1),
               round(100.0 * avg(CAST(has_media AS INT)), 1)
        FROM occurrence
        """
    ).fetchone()
    print(f"  completeness%: ident={summ[0]} coord={summ[1]} "
          f"date={summ[2]} media={summ[3]}")

    in_reg, total = con.execute(
        "SELECT count(*) FILTER (WHERE in_registry), count(*) FROM dataset"
    ).fetchone()
    print(f"  {total:,} datasets ({in_reg} in registry.json, "
          f"{total - in_reg} referenced from the DB only)")

    con.close()
    print(f"Done in {time.time() - t0:.1f}s -> {db_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help="ETL-produced DuckDB path")
    prepare(ap.parse_args().db)


if __name__ == "__main__":
    main()
