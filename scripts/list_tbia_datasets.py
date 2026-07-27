"""Inventory every dataset present in a raw TBIA export, and diff it against registry.json.

Scans the CSV inside ``tbia_*.zip`` for distinct ``tbiaDatasetID`` values —
including ones the platform has never ingested — so you can see what a fresh
export offers that ``data/registry.json`` does not yet list. This is the
discovery step that has to happen *before* ``make ingest``, since that loader is
scoped to exactly the ids already in the registry.

Writes two artifacts from a single pass over the export:

* ``data/tbia_export_summary.md`` — export-level figures (rows, datasets, rights
  holders) plus the registry diff, as a file you can read, keep, and ``diff``
  against the summary of the next export.
* ``data/tbia_datasets.csv`` — one row per dataset, for the human review that
  decides what goes into registry.json.

Reads only the handful of columns it needs, so a full 1.85 GB export scans in
well under a minute without materializing the occurrence table.

Usage:
    backend/.venv/bin/python scripts/list_tbia_datasets.py            # auto-detect zip
    backend/.venv/bin/python scripts/list_tbia_datasets.py --new-only # unregistered only
    backend/.venv/bin/python scripts/list_tbia_datasets.py --csv data/tbia_xxx.csv

Or without a host venv, using the backend image (duckdb is already in it):
    docker compose build backend
    docker run --rm -v "$PWD":/repo -w /repo tbia-specimen-annotation-backend \\
        python /repo/scripts/list_tbia_datasets.py --csv /repo/source/tbia_xxx.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime

import duckdb

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))
from ingest.ingest_tbia import ensure_csv, find_zip  # noqa: E402

DEFAULT_REGISTRY = os.path.join(REPO, "data", "registry.json")
DEFAULT_OUT = os.path.join(REPO, "data", "tbia_datasets.csv")
DEFAULT_REPORT = os.path.join(REPO, "data", "tbia_export_summary.md")

FIELDS = [
    "tbia_dataset_id", "dataset_name", "source_dataset_id", "gbif_dataset_id",
    "rights_holder", "resource_contacts", "bio_groups", "n_records",
    "in_registry", "registry_section", "registry_code",
]

# Raw export column -> the snake_case name we fold it to. Every one of these is
# a per-dataset attribute, so the fold below collapses ~2M rows to a few hundred.
SOURCE_COLUMNS = {
    "tbia_dataset_id": "tbiaDatasetID",
    "dataset_name": "datasetName",
    "source_dataset_id": "sourceDatasetID",
    "gbif_dataset_id": "gbifDatasetID",
    "rights_holder": "rightsHolder",
    "resource_contacts": "resourceContacts",
    "bio_group": "bioGroup",
}

# Fields where a dataset is represented by one value, but the export may disagree
# with itself across rows; we take the most common one (see pick_top).
TOP_FIELDS = [
    "dataset_name", "source_dataset_id", "gbif_dataset_id",
    "rights_holder", "resource_contacts",
]


def read_registry(path: str) -> dict[str, tuple[str, str]]:
    """Map every registered tbia_dataset_id -> (section, source code).

    Same two-level shape ingest_filtered.read_registry_ids walks, but we keep
    the owning source so the report can say *where* a known id is registered.
    """
    if not os.path.exists(path):
        sys.exit(f"registry not found: {path}")
    with open(path, encoding="utf-8") as f:
        reg = json.load(f)
    out: dict[str, tuple[str, str]] = {}
    for section in ("institutions", "aggregators"):
        for code, src in reg.get(section, {}).items():
            for did in src.get("datasets", {}):
                out.setdefault(did, (section, code))
    return out


def read_csv_expr(csv_path: str) -> str:
    """Reader options shared with the ingest loaders."""
    return (
        f"read_csv('{csv_path}', header=true, all_varchar=true, "
        f"quote='\"', escape='\"', ignore_errors=true)"
    )


def pick_top(field: str) -> str:
    """CTE giving each dataset its most frequent non-empty value for `field`.

    The export can carry more than one spelling of a dataset's name or holder;
    picking by frequency is deterministic where any_value() was arbitrary.
    """
    return f"""{field}_top AS (
            SELECT tbia_dataset_id, arg_max({field}, n) AS {field}
            FROM (SELECT tbia_dataset_id, {field}, sum(n) AS n
                  FROM facts
                  WHERE tbia_dataset_id IS NOT NULL AND {field} IS NOT NULL
                  GROUP BY 1, 2)
            GROUP BY 1
        )"""


def fold(con: duckdb.DuckDBPyConnection, csv_path: str) -> None:
    """Collapse the export into a temp `facts` table in ONE scan.

    Everything downstream — the per-dataset rows and every figure in the report —
    is derived from this table, so the 1.85 GB file is read exactly once. We name
    the wanted columns in the SELECT rather than via read_csv's ``columns=`` —
    that option assigns types *by position*, silently renaming the first N columns
    instead of picking the ones we asked for. Projection pushdown keeps the scan
    to these columns.

    Rows with a blank tbiaDatasetID are kept (as NULL) rather than filtered, so
    the report's row count can describe the whole export instead of quietly
    dropping records nobody would then know about.
    """
    src = read_csv_expr(csv_path)
    available = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
    missing = [raw for raw in SOURCE_COLUMNS.values() if raw not in available]
    if missing:
        # An older export can lack a column; naming it would be a binder error
        # that kills the run, so degrade to an empty column instead.
        print(f"  note: export has no {', '.join(missing)} — leaving blank")

    projections = ",\n               ".join(
        f'nullif(trim("{raw}"), \'\') AS {name}' if raw in available
        else f"CAST(NULL AS VARCHAR) AS {name}"
        for name, raw in SOURCE_COLUMNS.items()
    )
    con.execute(f"""
        CREATE TEMP TABLE facts AS
        SELECT {projections},
               count(*) AS n
        FROM {src}
        GROUP BY ALL
    """)


def per_dataset(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """A row per dataset, largest first, derived from `facts` (no re-scan)."""
    # bio_groups is ranked by frequency and capped, not a flat DISTINCT set:
    # datasets carry a long tail of stray single records (a herbarium with one
    # fish), so an unordered list hides which groups the dataset is actually
    # about — the thing you need to fill in registry.json's `groups`.
    ctes = ",\n        ".join(
        ["""totals AS (
            SELECT tbia_dataset_id, sum(n) AS n_records
            FROM facts WHERE tbia_dataset_id IS NOT NULL GROUP BY 1
        )""", """groups_top AS (
            SELECT tbia_dataset_id,
                   string_agg(bio_group || ':' || n, '|' ORDER BY n DESC) AS bio_groups
            FROM (SELECT tbia_dataset_id, bio_group, sum(n) AS n,
                         row_number() OVER (PARTITION BY tbia_dataset_id
                                            ORDER BY sum(n) DESC) AS rk
                  FROM facts
                  WHERE tbia_dataset_id IS NOT NULL AND bio_group IS NOT NULL
                  GROUP BY 1, 2)
            WHERE rk <= 5
            GROUP BY 1
        )"""] + [pick_top(f) for f in TOP_FIELDS]
    )
    joins = "\n        ".join(
        f"LEFT JOIN {f}_top USING (tbia_dataset_id)" for f in TOP_FIELDS
    )
    rows = con.execute(f"""
        WITH {ctes}
        SELECT t.tbia_dataset_id, dataset_name, source_dataset_id, gbif_dataset_id,
               rights_holder, resource_contacts, g.bio_groups, t.n_records
        FROM totals t
        LEFT JOIN groups_top g USING (tbia_dataset_id)
        {joins}
        ORDER BY t.n_records DESC
    """).fetchall()
    cols = ["tbia_dataset_id", "dataset_name", "source_dataset_id", "gbif_dataset_id",
            "rights_holder", "resource_contacts", "bio_groups", "n_records"]
    return [dict(zip(cols, r)) for r in rows]


def export_stats(con: duckdb.DuckDBPyConnection) -> dict:
    """Export-level figures, counted across `facts` rather than per-dataset rows.

    rights_holders in particular MUST be counted here: a dataset can carry more
    than one holder, so counting distinct values of the per-dataset representative
    would undercount them.
    """
    total, no_id, n_datasets, n_holders, with_source, with_gbif = con.execute("""
        SELECT sum(n),
               coalesce(sum(n) FILTER (WHERE tbia_dataset_id IS NULL), 0),
               count(DISTINCT tbia_dataset_id),
               count(DISTINCT rights_holder),
               count(DISTINCT tbia_dataset_id) FILTER (WHERE source_dataset_id IS NOT NULL),
               count(DISTINCT tbia_dataset_id) FILTER (WHERE gbif_dataset_id IS NOT NULL)
        FROM facts
    """).fetchone()
    holders = con.execute("""
        SELECT rights_holder, count(DISTINCT tbia_dataset_id) AS n_datasets, sum(n) AS n_records
        FROM facts WHERE rights_holder IS NOT NULL
        GROUP BY 1 ORDER BY n_records DESC
    """).fetchall()
    return {
        "total_rows": int(total or 0),
        "rows_without_dataset_id": int(no_id or 0),
        "n_datasets": int(n_datasets or 0),
        "n_rights_holders": int(n_holders or 0),
        "datasets_with_source_id": int(with_source or 0),
        "datasets_with_gbif_id": int(with_gbif or 0),
        "holders": holders,
    }


def md(value) -> str:
    """Escape a cell so `|` inside a value can't break the markdown table.

    bio_groups uses `|` as its own separator, so this is load-bearing.
    """
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_report(path: str, *, source_file: str, csv_path: str, stats: dict,
                 datasets: list[dict], known: dict[str, tuple[str, str]]) -> None:
    """Render the export summary.

    Always describes the WHOLE export: --new-only narrows the CSV, never this.
    Deliberately carries no "generated at" line — the report is meant to be
    diffed against the next export's, and a timestamp would change every run.
    """
    # astimezone() + %z stamps the offset: the same export summarised on the host
    # and in the (UTC) container would otherwise show two different clock times
    # with nothing to say which is which.
    created = datetime.fromtimestamp(os.path.getmtime(source_file)).astimezone()
    new = [d for d in datasets if d["tbia_dataset_id"] not in known]
    registered = len(datasets) - len(new)
    new_records = sum(d["n_records"] for d in new)
    found_ids = {d["tbia_dataset_id"] for d in datasets}
    absent = [(did, known[did]) for did in known if did not in found_ids]

    L = [
        f"# TBIA export summary — `{os.path.basename(source_file)}`",
        "",
        "| | |",
        "| --- | --- |",
        f"| Export file | `{os.path.basename(source_file)}` |",
        f"| Created | {created:%Y-%m-%d %H:%M:%S %z} (mtime of `{os.path.basename(source_file)}`) |",
        f"| Rows parsed | {stats['total_rows']:,} |",
        f"| Datasets | {stats['n_datasets']:,} |",
        f"| Rights holders | {stats['n_rights_holders']:,} |",
        "",
        f"Scanned `{csv_path}`. Row count is rows *parsed* — the reader skips "
        "malformed rows, so this is not a line count of the file.",
    ]
    if stats["rows_without_dataset_id"]:
        L += ["", f"**{stats['rows_without_dataset_id']:,} row(s) carry no `tbiaDatasetID`** "
              "and appear in no dataset below."]

    # An identifier the export never populates reads as a bug in the CSV; say so
    # here instead, so the empty column is a known fact about the export.
    n = stats["n_datasets"]
    L += ["", "### Identifier coverage", ""]
    for label, have in (("`sourceDatasetID`", stats["datasets_with_source_id"]),
                        ("`gbifDatasetID`", stats["datasets_with_gbif_id"])):
        note = " — **column is empty throughout this export**" if not have else ""
        L.append(f"- {label}: {have:,} / {n:,} datasets{note}")

    L += ["", f"## Rights holders ({stats['n_rights_holders']:,})", "",
          "| Rights holder | Datasets | Records |", "| --- | ---: | ---: |"]
    L += [f"| {md(h)} | {nd:,} | {nr:,} |" for h, nd, nr in stats["holders"]]

    L += ["", "## Registry review", "",
          f"- Datasets in this export: **{stats['n_datasets']:,}** "
          f"({stats['total_rows'] - stats['rows_without_dataset_id']:,} records)",
          f"- Already in `registry.json`: **{registered:,}**",
          f"- **Not in registry: {len(new):,}** ({new_records:,} records)"]
    if absent:
        L += ["", f"Registered but absent from this export ({len(absent):,}):", ""]
        L += [f"- `{did}` ({section}/{code})" for did, (section, code) in absent]

    L += ["", f"## Datasets not in the registry ({len(new):,})", ""]
    if new:
        L += ["| Records | tbiaDatasetID | Dataset | Rights holder | Bio groups |",
              "| ---: | --- | --- | --- | --- |"]
        L += [f"| {d['n_records']:,} | `{md(d['tbia_dataset_id'])}` | {md(d['dataset_name'])} "
              f"| {md(d['rights_holder'])} | {md(d['bio_groups'])} |" for d in new]
    else:
        L.append("None — the export adds no datasets the registry lacks.")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", help="Path to tbia_*.zip (auto-detected if omitted)")
    ap.add_argument("--csv", help="Skip the zip and scan an already-extracted CSV")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--report", default=DEFAULT_REPORT, help="Markdown summary path")
    ap.add_argument("--new-only", action="store_true",
                    help="Write only datasets missing from the registry (CSV only)")
    args = ap.parse_args()

    # The created date must come from the export itself: ensure_csv's extracted
    # CSV is stamped when it was unzipped, which says nothing about the export.
    if args.csv:
        csv_path = source_file = args.csv
        if not os.path.exists(csv_path):
            sys.exit(f"CSV not found: {csv_path}")
    else:
        source_file = find_zip(args.zip)
        if not os.path.exists(source_file):
            sys.exit(f"zip not found: {source_file}")
        csv_path = ensure_csv(source_file)
    print(f"Source     : {source_file}")
    print(f"Source CSV : {csv_path}")
    known = read_registry(args.registry)
    print(f"Registry   : {len(known)} dataset id(s) in {args.registry}")

    print("Scanning ...")
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    fold(con, csv_path)
    datasets = per_dataset(con)
    stats = export_stats(con)

    rows = [
        {k: (d[k] if k in d else "") for k in FIELDS} | {
            "in_registry": "yes" if d["tbia_dataset_id"] in known else "no",
            "registry_section": known.get(d["tbia_dataset_id"], ("", ""))[0],
            "registry_code": known.get(d["tbia_dataset_id"], ("", ""))[1],
        }
        for d in datasets
        if not (args.new_only and d["tbia_dataset_id"] in known)
    ]
    for r in rows:
        for k in FIELDS:
            if r[k] is None:
                r[k] = ""

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    write_report(args.report, source_file=source_file, csv_path=csv_path,
                 stats=stats, datasets=datasets, known=known)

    n_new = sum(1 for d in datasets if d["tbia_dataset_id"] not in known)
    new_records = sum(d["n_records"] for d in datasets if d["tbia_dataset_id"] not in known)
    found_ids = {d["tbia_dataset_id"] for d in datasets}
    missing = [d for d in known if d not in found_ids]

    print(f"rows parsed          : {stats['total_rows']:,}")
    print(f"rights holders       : {stats['n_rights_holders']:,}")
    print(f"datasets in export   : {stats['n_datasets']:,} "
          f"({stats['total_rows'] - stats['rows_without_dataset_id']:,} records)")
    print(f"  already registered : {stats['n_datasets'] - n_new:,}")
    print(f"  NOT in registry    : {n_new:,} ({new_records:,} records)")
    if stats["rows_without_dataset_id"]:
        print(f"  rows with no id    : {stats['rows_without_dataset_id']:,}")
    if missing:
        print(f"registered but absent from this export: {len(missing):,}")
        for did in missing:
            section, code = known[did]
            print(f"  {did}  ({section}/{code})")
    print(f"written: {len(rows):,} row(s) -> {args.out}")
    print(f"written: {args.report}")
    print("--- largest unregistered ---")
    shown = 0
    for d in datasets:
        if d["tbia_dataset_id"] in known:
            continue
        print(f"  {d['n_records']:>9,}  {d['tbia_dataset_id']}  "
              f"{d['dataset_name']!r} [{d['bio_groups'] or '-'}]")
        shown += 1
        if shown >= 15:
            break
    if not shown:
        print("  (none — the export adds no datasets the registry lacks)")


if __name__ == "__main__":
    main()
