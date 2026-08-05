"""Load a TBIA export into a new DuckDB store, scoped to data/registry.json.

Step 3 of the refresh (see ``ingest/common.py``). A row is kept when its
``tbiaDatasetID`` is listed in the registry, or when its ``rightsHolder`` is
``GBIF``; everything else is dropped. Two tables come out:

    occurrence  one row per record, every CSV column snake_cased, plus the
                registry's institution_code / institution_name / dataset_code /
                groups
    dataset     one row per tbia_dataset_id, with num_of_rows,
                n_source_dataset_ids and in_registry

The store is **not servable yet** — ``ingest.prepare`` derives the completeness
flags and indexes the API queries. Build to a side path and swap after
preparing, so a live store is never served without its flags:

    python -m ingest.build --zip ../tmp/tbia_xxx.zip --db ../data/tbia.new.duckdb
    python -m ingest.prepare --db ../data/tbia.new.duckdb
    mv ../data/tbia.new.duckdb ../data/tbia.duckdb

Before loading a row, the export's columns are compared against the baseline
(``ingest/columns.json``, else the target store's schema). Any difference aborts
the build: the app reads columns like ``standard_date`` and ``class`` by name, so
an upstream rename would load cleanly and then fail every query. Accept a change
by editing the manifest — there is deliberately no override flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

import duckdb

from ingest.common import (
    BOOLEAN_COLS,
    COLUMNS_MANIFEST,
    DEFAULT_DB,
    DEFAULT_REGISTRY,
    DOUBLE_COLS,
    GBIF,
    REPO,
    TIMESTAMP_COLS,
    camel_to_snake,
    column_baseline,
    compare_columns,
    ensure_csv,
    find_zip,
    flatten_registry,
    load_registry,
    read_header,
    write_manifest,
)


def sql_str(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def check_columns(header: list[str], db_path: str, manifest_path: str) -> None:
    """Abort unless the export's columns match the baseline. Record one if there is none."""
    baseline, source = column_baseline(db_path, manifest_path)
    if baseline is None:
        write_manifest(header, manifest_path)
        print(f"  no baseline found — recorded {len(header)} columns in "
              f"{os.path.relpath(manifest_path, REPO)}")
        return

    added, removed = compare_columns(baseline, header)
    if not added and not removed:
        print(f"  columns match the baseline ({source}, {len(baseline)} columns)")
        return

    print(f"\nEXPORT COLUMNS CHANGED vs {source}", file=sys.stderr)
    for c in added:
        print(f"  + {c}  (new in this export)", file=sys.stderr)
    for c in removed:
        print(f"  - {c}  (gone from this export)", file=sys.stderr)
    sys.exit(
        f"\nRefusing to build: the app reads columns by name, so a changed export can "
        f"produce a store that loads and then fails every query.\n"
        f"Review the diff above (a rename is one + and one -), edit "
        f"{os.path.relpath(manifest_path, REPO)} to match, and re-run.\n"
        f"Nothing was written; any existing store is untouched."
    )


def build_select(header: list[str]) -> str:
    """One projection per CSV column, snake_cased, cast only where the fields doc types it."""
    parts = []
    for col in header:
        ref = f's."{col}"'
        if col in DOUBLE_COLS:
            expr = f"TRY_CAST({ref} AS DOUBLE)"
        elif col in BOOLEAN_COLS:
            expr = f"TRY_CAST({ref} AS BOOLEAN)"
        elif col in TIMESTAMP_COLS:
            expr = f"TRY_CAST({ref} AS TIMESTAMP)"
        else:
            expr = ref
        parts.append(f'  {expr} AS "{camel_to_snake(col)}"')
    return ",\n".join(parts)


def load_occurrence(con, csv_path: str, table: str, select_list: str) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE "{table}" AS
        SELECT
        {select_list},
          COALESCE(r.institution_code, {sql_str(GBIF)}) AS "institution_code",
          COALESCE(r.institution_name, {sql_str(GBIF)}) AS "institution_name",
          r.dataset_code AS "dataset_code",
          r.groups AS "groups"
        FROM read_csv({sql_str(csv_path)}, header=true, all_varchar=true) AS s
        LEFT JOIN registry_map AS r
          ON s."tbiaDatasetID" = r.tbia_dataset_id
        WHERE r.tbia_dataset_id IS NOT NULL
           OR s."rightsHolder" = {sql_str(GBIF)}
    """)


def build_dataset(con, table: str) -> None:
    """Rolled up from the rows actually loaded, so the counts can never disagree."""
    con.execute(f"""
        CREATE OR REPLACE TABLE dataset AS
        SELECT d.tbia_dataset_id,
               d.dataset_name,
               d.source_dataset_id,
               d.gbif_dataset_id,
               d.rights_holder,
               d.institution_code,
               d.institution_name,
               d.dataset_code,
               d.groups,
               (r.tbia_dataset_id IS NOT NULL) AS in_registry,
               d.num_of_rows,
               d.n_source_dataset_ids
        FROM (
            SELECT tbia_dataset_id,
                   max(dataset_name)                 AS dataset_name,
                   max(source_dataset_id)            AS source_dataset_id,
                   max(gbif_dataset_id)              AS gbif_dataset_id,
                   max(rights_holder)                AS rights_holder,
                   any_value(institution_code)       AS institution_code,
                   any_value(institution_name)       AS institution_name,
                   any_value(dataset_code)           AS dataset_code,
                   any_value(groups)                 AS groups,
                   count(*)                          AS num_of_rows,
                   count(DISTINCT source_dataset_id) AS n_source_dataset_ids
            FROM "{table}"
            GROUP BY tbia_dataset_id
        ) d
        LEFT JOIN registry_map r ON r.tbia_dataset_id = d.tbia_dataset_id
    """)


def report(con, table: str) -> None:
    unmatched = con.execute("""
        SELECT m.institution_code, m.tbia_dataset_id
        FROM registry_map m
        LEFT JOIN dataset d ON d.tbia_dataset_id = m.tbia_dataset_id
        WHERE d.tbia_dataset_id IS NULL
        ORDER BY 1, 2
    """).fetchall()
    if unmatched:
        print(f"\n  {len(unmatched)} registry dataset(s) matched nothing in this export:")
        for code, ds_id in unmatched:
            print(f"    {code:<8} {ds_id}")

    print("\n  rows by source:")
    for code, rows, ds in con.execute(f"""
        SELECT institution_code, count(*) AS rows, count(DISTINCT tbia_dataset_id) AS datasets
        FROM "{table}" GROUP BY 1 ORDER BY rows DESC
    """).fetchall():
        print(f"    {code:<8} {rows:>10,} rows  {ds:>5} dataset(s)")

    total = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    rolled = con.execute("SELECT coalesce(sum(num_of_rows), 0) FROM dataset").fetchone()[0]
    if total != rolled:
        sys.exit(f"dataset roll-up ({rolled:,}) disagrees with {table} ({total:,})")
    n_ds, n_reg = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE in_registry) FROM dataset"
    ).fetchone()
    print(f"\n  {total:,} rows | {n_ds:,} datasets ({n_reg} curated, {n_ds - n_reg} via GBIF)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--zip", help="TBIA export .zip (auto-detected if omitted)")
    src.add_argument("--csv", help="already-extracted TBIA export .csv")
    ap.add_argument("--db", default=DEFAULT_DB, help="output DuckDB path")
    ap.add_argument("--table", default="occurrence", help="occurrence table name")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY, help="registry JSON")
    ap.add_argument("--manifest", default=COLUMNS_MANIFEST, help="expected column manifest")
    args = ap.parse_args()

    csv_path = args.csv
    if not csv_path:
        zip_path = find_zip(args.zip)
        print(f"Source zip : {zip_path}")
        csv_path = ensure_csv(zip_path)
    csv_path = os.path.abspath(csv_path)
    if not os.path.exists(csv_path):
        sys.exit(f"no such file: {csv_path}")
    print(f"Source csv : {csv_path}")
    print(f"Target DB  : {args.db}")

    mapping = flatten_registry(load_registry(args.registry))
    print(f"Registry   : {len(mapping)} dataset(s) across "
          f"{len({m['institution_code'] for m in mapping})} source(s)")

    header = read_header(csv_path)
    check_columns(header, args.db, args.manifest)

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    if os.path.exists(args.db):
        print(f"  replacing existing {args.db}")
        os.remove(args.db)

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as tf:
        json.dump(mapping, tf, ensure_ascii=False)
        reg_tmp = tf.name

    t0 = time.time()
    con = duckdb.connect(args.db)
    try:
        con.execute("PRAGMA threads=4")
        con.execute(f"CREATE OR REPLACE TEMP TABLE registry_map AS "
                    f"SELECT * FROM read_json({sql_str(reg_tmp)})")
        print("\nLoading occurrences ...")
        load_occurrence(con, csv_path, args.table, build_select(header))
        print(f"  loaded in {time.time() - t0:.1f}s")
        print("Building dataset roll-up ...")
        build_dataset(con, args.table)
        report(con, args.table)
    finally:
        con.close()
        os.unlink(reg_tmp)

    rel_db = os.path.relpath(args.db, REPO)
    print(f"\nDone in {time.time() - t0:.1f}s -> {args.db}")
    print("The store has no completeness flags yet — the API cannot serve it. Next:")
    print(f"  cd backend && .venv/bin/python -m ingest.prepare --db ../{rel_db}")


if __name__ == "__main__":
    main()
