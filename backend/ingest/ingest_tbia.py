"""Ingest the TBIA occurrence CSV into a read-only DuckDB database.

The source is a ~1.85 GB CSV inside ``tbia_<hash>.zip`` (≈1,992,619 data rows).
We load it into ``data/occurrences.duckdb`` with snake_case columns, parsed
coordinate/date types, and the four *completeness* flags that drive the whole
platform (missing identification / coordinates / date / media).

Usage:
    python -m ingest.ingest_tbia                # full load
    python -m ingest.ingest_tbia --limit 50000  # quick dev sample
    python -m ingest.ingest_tbia --zip ../tbia_xxx.zip --db ../data/occurrences.duckdb
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time
import zipfile

import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DEFAULT_DB = os.path.join(REPO, "data", "occurrences.duckdb")

# (raw CSV column, target snake_case column, SQL expression producing the value).
# {c} is the raw column reference (double-quoted to survive reserved words).
COLUMNS: list[tuple[str, str, str]] = [
    ("id", "id", "{c}"),
    ("created", "created", "{c}"),
    ("modified", "modified", "{c}"),
    ("standardDate", "std_date", "TRY_CAST(left({c}, 10) AS DATE)"),
    ("standardLatitude", "std_lat", "TRY_CAST({c} AS DOUBLE)"),
    ("standardLongitude", "std_lon", "TRY_CAST({c} AS DOUBLE)"),
    ("standardOrganismQuantity", "std_organism_quantity", "{c}"),
    ("associatedMedia", "associated_media", "{c}"),
    ("basisOfRecord", "basis_of_record", "{c}"),
    ("catalogNumber", "catalog_number", "{c}"),
    ("coordinateUncertaintyInMeters", "coordinate_uncertainty", "TRY_CAST({c} AS DOUBLE)"),
    ("dataGeneralizations", "data_generalizations", "{c}"),
    ("datasetName", "dataset_name", "{c}"),
    ("tbiaDatasetID", "tbia_dataset_id", "{c}"),
    ("sourceDatasetID", "source_dataset_id", "{c}"),
    ("gbifDatasetID", "gbif_dataset_id", "{c}"),
    ("eventDate", "event_date", "{c}"),
    ("county", "county", "{c}"),
    ("municipality", "municipality", "{c}"),
    ("license", "license", "{c}"),
    ("locality", "locality", "{c}"),
    ("occurrenceID", "occurrence_id", "{c}"),
    ("organismQuantity", "organism_quantity", "{c}"),
    ("organismQuantityType", "organism_quantity_type", "{c}"),
    ("originalScientificName", "original_scientific_name", "{c}"),
    ("preservation", "preservation", "{c}"),
    ("recordedBy", "recorded_by", "{c}"),
    ("recordNumber", "record_number", "{c}"),
    ("references", "references_url", "{c}"),
    ("resourceContacts", "resource_contacts", "{c}"),
    ("rightsHolder", "rights_holder", "{c}"),
    ("sensitiveCategory", "sensitive_category", "{c}"),
    ("sourceCreated", "source_created", "{c}"),
    ("sourceModified", "source_modified", "{c}"),
    ("sourceScientificName", "source_scientific_name", "{c}"),
    ("sourceVernacularName", "source_vernacular_name", "{c}"),
    ("typeStatus", "type_status", "{c}"),
    ("verbatimCoordinateSystem", "verbatim_coordinate_system", "{c}"),
    ("verbatimLatitude", "verbatim_latitude", "{c}"),
    ("verbatimLongitude", "verbatim_longitude", "{c}"),
    ("verbatimSRS", "verbatim_srs", "{c}"),
    ("scientificName", "scientific_name", "{c}"),
    ("name_author", "name_author", "{c}"),
    ("bioGroup", "bio_group", "{c}"),
    ("taxonRank", "taxon_rank", "{c}"),
    ("common_name_c", "common_name_c", "{c}"),
    ("alternative_name_c", "alternative_name_c", "{c}"),
    ("synonyms", "synonyms", "{c}"),
    ("kingdom", "kingdom", "{c}"),
    ("kingdom_c", "kingdom_c", "{c}"),
    ("phylum", "phylum", "{c}"),
    ("phylum_c", "phylum_c", "{c}"),
    ("class", "class_name", "{c}"),
    ("class_c", "class_c", "{c}"),
    ("order", "order_name", "{c}"),
    ("order_c", "order_c", "{c}"),
    ("family", "family", "{c}"),
    ("family_c", "family_c", "{c}"),
    ("genus", "genus", "{c}"),
    ("genus_c", "genus_c", "{c}"),
]

# Ranks that count as "identified to a usable taxon" for the identification gap.
SPECIES_RANKS = ("species", "subspecies", "variety", "form", "forma", "subvariety")


def find_zip(explicit: str | None) -> str:
    if explicit:
        return explicit
    hits = glob.glob(os.path.join(REPO, "tbia_*.zip"))
    if not hits:
        sys.exit(f"No tbia_*.zip found in {REPO}; pass --zip explicitly.")
    return hits[0]


def ensure_csv(zip_path: str) -> str:
    """Extract the single CSV from the zip into data/ if not already present."""
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            sys.exit(f"No CSV inside {zip_path}")
        csv_name = names[0]
        out_path = os.path.join(REPO, "data", os.path.basename(csv_name))
        if os.path.exists(out_path) and os.path.getsize(out_path) == zf.getinfo(csv_name).file_size:
            print(f"  CSV already extracted: {out_path}")
            return out_path
        print(f"  Extracting {csv_name} -> {out_path} ...")
        with zf.open(csv_name) as src, open(out_path, "wb") as dst:
            while chunk := src.read(8 << 20):
                dst.write(chunk)
        return out_path


def build_select(csv_path: str, limit: int | None, exclude_gbif: bool = True) -> str:
    read_csv = (
        f"read_csv('{csv_path}', header=true, all_varchar=true, "
        f"quote='\"', escape='\"', ignore_errors=true)"
    )
    projections = []
    for raw, target, expr in COLUMNS:
        c = f'"{raw}"'
        projections.append(f"{expr.format(c=c)} AS {target}")

    # Completeness flags + score, derived from the projected values.
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

    base = f"SELECT {', '.join(projections)} FROM {read_csv}"
    # GBIF datasets are external aggregated mirrors, not TBIA-native specimens;
    # skip them so the occurrence store only holds TBIA institution data.
    if exclude_gbif:
        base += " WHERE \"rightsHolder\" IS DISTINCT FROM 'GBIF'"
    if limit:
        base += f" LIMIT {limit}"
    # Wrap once to compute flags from projected names, then again for the score.
    with_flags = f"SELECT *, {', '.join(flags)} FROM ({base})"
    return f"SELECT *, {score} FROM ({with_flags})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", help="Path to tbia_*.zip (auto-detected if omitted)")
    ap.add_argument("--db", default=DEFAULT_DB, help="Output DuckDB path")
    ap.add_argument("--limit", type=int, default=None, help="Row limit for a dev sample")
    ap.add_argument("--include-gbif", action="store_true",
                    help="Include GBIF datasets (excluded by default)")
    args = ap.parse_args()

    exclude_gbif = not args.include_gbif
    zip_path = find_zip(args.zip)
    print(f"Source zip : {zip_path}")
    print(f"Target DB  : {args.db}")
    print(f"GBIF rows  : {'excluded' if exclude_gbif else 'included'}")
    csv_path = ensure_csv(zip_path)

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)

    con = duckdb.connect(args.db)
    con.execute("PRAGMA threads=4")

    t0 = time.time()
    print("Loading occurrences ...")
    con.execute(f"CREATE TABLE occurrences AS {build_select(csv_path, args.limit, exclude_gbif)}")
    n = con.execute("SELECT count(*) FROM occurrences").fetchone()[0]
    print(f"  loaded {n:,} rows in {time.time() - t0:.1f}s")

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

    # Quick completeness summary for sanity.
    summ = con.execute(
        """
        SELECT
          round(100.0 * avg(CAST(has_identification AS INT)), 1) AS pct_ident,
          round(100.0 * avg(CAST(has_coordinates AS INT)), 1)    AS pct_coord,
          round(100.0 * avg(CAST(has_date AS INT)), 1)           AS pct_date,
          round(100.0 * avg(CAST(has_media AS INT)), 1)          AS pct_media
        FROM occurrences
        """
    ).fetchone()
    print(f"  completeness%: ident={summ[0]} coord={summ[1]} date={summ[2]} media={summ[3]}")
    con.close()
    print(f"Done in {time.time() - t0:.1f}s -> {args.db}")


if __name__ == "__main__":
    main()
