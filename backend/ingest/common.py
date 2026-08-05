"""Shared pieces of the TBIA refresh: export access, the registry, the column baseline.

The refresh is four steps, in order:

    1. inspect.py  survey a downloaded export (read-only)
    2. (human)     edit data/registry.json to match what inspect reported
    3. build.py    load the export into a new DuckDB, scoped to the registry
    4. prepare.py  derive the completeness flags the API queries

Everything both scripts need lives here so neither imports the other.
"""

from __future__ import annotations

import csv
import glob
import io
import json
import os
import re
import sys
import zipfile
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data")

DEFAULT_REGISTRY = os.path.join(DATA, "registry.json")
DEFAULT_DB = os.path.join(DATA, "tbia.duckdb")
COLUMNS_MANIFEST = os.path.join(HERE, "columns.json")

GBIF = "GBIF"

# Ranks that count as "identified to a usable taxon" for the identification gap.
SPECIES_RANKS = ("species", "subspecies", "variety", "form", "forma", "subvariety")

# Everything not listed here stays VARCHAR (the TBIA fields doc types them as string).
DOUBLE_COLS = {"standardLatitude", "standardLongitude", "standardOrganismQuantity",
               "standardRawLatitude", "standardRawLongitude"}
BOOLEAN_COLS = {"dataGeneralizations", "match_higher_taxon"}
TIMESTAMP_COLS = {"created", "modified", "standardDate", "sourceCreated", "sourceModified"}

# Columns the pipeline adds itself — excluded when an existing store is used as
# the column baseline, since the export never carries them.
BUILD_ADDED = ("institution_code", "institution_name", "dataset_code", "groups")
PREPARE_ADDED = ("has_coordinates", "has_date", "has_identification", "has_media",
                 "year", "completeness_score")

# The columns inspect.py reads out of every row.
INSPECT_COLUMNS = ["tbiaDatasetID", "datasetName", "sourceDatasetID", "gbifDatasetID",
                   "rightsHolder"]


def camel_to_snake(name: str) -> str:
    """tbiaDatasetID -> tbia_dataset_id; verbatimSRS -> verbatim_srs; id -> id."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def raise_field_limit() -> None:
    """TBIA `synonyms` / `associatedMedia` values exceed csv's 128 KB default."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 2


# --------------------------------------------------------------------------- export


def find_zip(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    hits = sorted(glob.glob(os.path.join(REPO, "tmp", "tbia_*.zip"))
                  + glob.glob(os.path.join(REPO, "tbia_*.zip")))
    if not hits:
        sys.exit(f"No tbia_*.zip found in {REPO}/tmp or {REPO}; pass --zip explicitly.")
    return hits[0]


@contextmanager
def open_export(path: str):
    """Yield (text_stream, member_name) for a .zip holding one CSV, or a plain .csv.

    Streams the member straight out of the archive — nothing is extracted, so a
    multi-GB export is read in constant memory.
    """
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist()
                       if n.lower().endswith(".csv") and not n.startswith("__MACOSX/")]
            if not members:
                sys.exit(f"no .csv found inside {path}")
            if len(members) > 1:
                print(f"note: {len(members)} csv files in zip, using {members[0]!r}",
                      file=sys.stderr)
            with zf.open(members[0]) as raw:
                yield io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), members[0]
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            yield fh, os.path.basename(path)


def ensure_csv(zip_path: str, outdir: str | None = None) -> str:
    """Extract the single CSV from the zip, skipping if it is already there.

    build.py hands the file to DuckDB's read_csv, which scans it in parallel —
    worth the ~2 GB on disk that streaming from the archive would save.
    """
    outdir = outdir or os.path.dirname(os.path.abspath(zip_path))
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith(".csv") and not n.startswith("__MACOSX/")]
        if not names:
            sys.exit(f"No CSV inside {zip_path}")
        member = names[0]
        out_path = os.path.join(outdir, os.path.basename(member))
        want = zf.getinfo(member).file_size
        if os.path.exists(out_path) and os.path.getsize(out_path) == want:
            print(f"  CSV already extracted: {out_path}")
            return out_path
        os.makedirs(outdir, exist_ok=True)
        print(f"  Extracting {member} ({want / 1e9:.2f} GB) -> {out_path} ...")
        with zf.open(member) as src, open(out_path, "wb") as dst:
            while chunk := src.read(8 << 20):
                dst.write(chunk)
        return out_path


def read_header(csv_path: str) -> list[str]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    missing = [c for c in ("tbiaDatasetID", "rightsHolder") if c not in header]
    if missing:
        sys.exit(f"csv is missing {', '.join(missing)} — is this a TBIA export?")
    return header


# ------------------------------------------------------------------------- registry


def load_registry(path: str = DEFAULT_REGISTRY) -> dict:
    """Read data/registry.json, which decides what gets ingested."""
    if not os.path.exists(path):
        sys.exit(f"registry not found: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            reg = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.exit(f"registry is not valid JSON ({path}): {exc}")
    reg.setdefault("institutions", {})
    reg.setdefault("aggregators", {})
    return reg


def flatten_registry(reg: dict) -> list[dict]:
    """Both registry sections -> one row per dataset, ready for the SQL join."""
    rows: list[dict] = []
    seen: dict[str, str] = {}
    for section in ("institutions", "aggregators"):
        for code, src in reg.get(section, {}).items():
            datasets = src.get("datasets")
            if not isinstance(datasets, dict):
                print(f"warning: {section}/{code} has no 'datasets' object — skipped",
                      file=sys.stderr)
                continue
            for ds_id, ds in datasets.items():
                if ds_id in seen:
                    sys.exit(f"registry maps {ds_id} to both {seen[ds_id]} and {code} — "
                             "a dataset belongs to exactly one source")
                seen[ds_id] = code
                rows.append({
                    "tbia_dataset_id": ds_id,
                    "institution_code": code,
                    "institution_name": src.get("name") or code,
                    "dataset_code": ds.get("code"),
                    "groups": ds.get("groups") or None,
                    "dataset_name": ds.get("name"),
                })
    if not rows:
        sys.exit("registry lists no datasets — nothing would be ingested")
    return rows


# ------------------------------------------------------------------ column baseline


def load_manifest(path: str = COLUMNS_MANIFEST) -> list[str] | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_manifest(columns: list[str], path: str = COLUMNS_MANIFEST) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(columns), fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def store_columns(db_path: str) -> list[str] | None:
    """The export columns an existing store implies, or None if there is no store.

    Strips what build.py and prepare.py add, so what is left is the export's own
    column set as it stood when that store was built.
    """
    if not os.path.exists(db_path):
        return None
    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
        try:
            cols = [r[0] for r in con.execute(
                "SELECT column_name FROM duckdb_columns() WHERE table_name = 'occurrence'"
            ).fetchall()]
        finally:
            con.close()
    except Exception as exc:
        print(f"note: could not read columns from {db_path}: {exc}", file=sys.stderr)
        return None
    drop = set(BUILD_ADDED) | set(PREPARE_ADDED)
    cols = [c for c in cols if c not in drop]
    return cols or None


def column_baseline(db_path: str = DEFAULT_DB,
                    manifest_path: str = COLUMNS_MANIFEST) -> tuple[list[str] | None, str]:
    """(baseline columns, where it came from). Manifest wins; the store is the fallback."""
    manifest = load_manifest(manifest_path)
    if manifest:
        return manifest, os.path.relpath(manifest_path, REPO)
    cols = store_columns(db_path)
    if cols:
        return cols, f"{os.path.relpath(db_path, REPO)} (occurrence)"
    return None, "none"


def compare_columns(baseline: list[str], header: list[str]) -> tuple[list[str], list[str]]:
    """(added, removed), matched on snake_case so either namespace can be passed in.

    Order is not compared — the load projects by name.
    """
    base = {camel_to_snake(c): c for c in baseline}
    have = {camel_to_snake(c): c for c in header}
    added = [have[k] for k in have.keys() - base.keys()]
    removed = [base[k] for k in base.keys() - have.keys()]
    return sorted(added), sorted(removed)
