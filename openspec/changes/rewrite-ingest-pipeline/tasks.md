## 1. Shared ingest module

- [x] 1.1 Create `backend/ingest/common.py` with `REPO`, `SPECIES_RANKS`, `camel_to_snake()`, `find_zip()` and `ensure_csv()`, lifted from `ingest_tbia.py` and `../tbia-data/tbia-to-duckdb.py`
- [x] 1.2 Add `open_export()` to `common.py` — a context manager yielding `(text_stream, member_name)` for a `.zip` holding one CSV or a plain `.csv`, plus the `csv.field_size_limit` bump (ported from `../tbia-data/tbia-stats.py`)
- [x] 1.3 Add `load_registry()` / `flatten_registry()` to `common.py`: read `data/registry.json`, walk **both** `institutions` and `aggregators`, and return one row per dataset (`tbia_dataset_id`, `institution_code`, `institution_name`, `dataset_code`, `groups`); raise on missing file, invalid JSON, and on the same `tbia_dataset_id` appearing under two sources
- [x] 1.4 Add `column_baseline()` / `compare_columns()` to `common.py`: read `backend/ingest/columns.json` when present, else derive the baseline from the target store's `occurrence` columns minus the build-added (`institution_code`, `institution_name`, `dataset_code`, `groups`) and prepare-added (`has_coordinates`, `has_date`, `has_identification`, `has_media`, `year`, `completeness_score`) ones, else report no baseline; compare as sets and return added/removed names
- [x] 1.5 Point `prepare.py` at `common.py` (`from ingest.common import REPO, SPECIES_RANKS`) and confirm `make prepare` still runs against a store built by the old path

## 2. Inspect step (`ingest/inspect.py`)

- [x] 2.1 Scaffold the CLI: positional export path (`.zip` or `.csv`), `-o/--outdir` (default: next to the export), `--registry` (default `data/registry.json`)
- [x] 2.2 Single streaming pass collecting total rows, per-`tbiaDatasetID` (`datasetName`, `sourceDatasetID`, `gbifDatasetID`, count, holder set), per-`rightsHolder` counts, and ragged-row count; fill in identifiers left blank on the dataset's first row
- [x] 2.3 Exit with a message naming the missing column(s) when any of `tbiaDatasetID`, `datasetName`, `sourceDatasetID`, `gbifDatasetID`, `rightsHolder` is absent from the header, writing no output
- [x] 2.4 Write `<name>-datasets.csv` (`utf-8-sig`), grouped by rights holder, largest datasets first within each holder
- [x] 2.5 Write `<name>-summary.md` (`utf-8-sig`) with the totals table, the rights-holder breakdown with shares, and the ragged-row note
- [x] 2.6 Add the registry reconciliation section to the summary: curated-but-missing-from-export, in-export-but-not-curated (non-GBIF only, with holder + row count), renamed (curated name vs export `datasetName`), and GBIF datasets as a single count
- [x] 2.7 Degrade gracefully when `data/registry.json` is absent: still write both files, say so in the reconciliation section
- [x] 2.8 Add the column-change section to the summary: added/removed names against the baseline and the warning that the build will abort; a one-line "matches baseline" when it does; the export's column list plus "no baseline found" when there is none — always exiting successfully
- [x] 2.9 Verify against `../tbia-data/tbia-260805/` — the summary's totals must match the existing `tbia_6a72e385d2fb88001772ccd4-summary.md` (2,113,068 rows / 1,018 datasets / 12 rights holders)

## 3. Build step (`ingest/build.py`)

- [x] 3.1 Scaffold the CLI: `--zip` / `--csv` input (auto-detect `tbia_*.zip` when neither is given), `--db` (default `data/tbia.duckdb`), `--table` (default `occurrence`), `--registry`
- [x] 3.2 Extract the CSV via `ensure_csv()` (skip when already extracted at the matching size) and read its header
- [x] 3.3 Guard on the column set **before any load**: compare the header against the baseline and exit non-zero naming added/removed columns, leaving an existing store at the target path intact; when neither manifest nor store exists, write `backend/ingest/columns.json` from the header, report the recording, and continue
- [x] 3.4 Generate the initial `backend/ingest/columns.json` from the 2026-08-05 export and commit it
- [x] 3.5 Build the projection from the header: snake-cased names, `TRY_CAST` to DOUBLE / TIMESTAMP / BOOLEAN for the three named column sets, everything else VARCHAR off `all_varchar=true`
- [x] 3.6 Write the flattened registry to a temp JSON and load it into a TEMP table with `read_json` so `groups` arrives as `VARCHAR[]`
- [x] 3.7 Create `occurrence`: `LEFT JOIN` the registry map on `tbiaDatasetID`, keep rows where the join matched **or** `rightsHolder = 'GBIF'`, and append `institution_code` / `institution_name` (COALESCEd to `'GBIF'`) / `dataset_code` / `groups`
- [x] 3.8 Replace the target file when one already exists, so a rebuild never inherits rows from a previous store
- [x] 3.9 Create `dataset` by grouping `occurrence` on `tbia_dataset_id`: `num_of_rows`, `n_source_dataset_ids` (distinct `source_dataset_id`), `in_registry` from the registry map, and `any_value()` for `dataset_name` / `source_dataset_id` / `gbif_dataset_id` / `rights_holder` / `institution_code` / `institution_name` / `dataset_code` / `groups`
- [x] 3.10 Report on completion: per-institution rows + dataset counts, total rows, registry datasets that matched nothing in the export, and the exact `make prepare` / `--db` command to run next
- [x] 3.11 Assert `sum(dataset.num_of_rows) = count(*) FROM occurrence` before reporting success

## 4. Remove the legacy path

- [x] 4.1 Delete `backend/ingest/ingest_tbia.py` and `backend/ingest/ingest_filtered.py`
- [x] 4.2 Delete `scripts/list_tbia_datasets.py` (superseded by `ingest/inspect.py`)
- [x] 4.3 Drop the `ingest` / `ingest-sample` targets from the `Makefile` and add `inspect` (`make inspect ZIP=…`) and `build-db` (`make build-db ZIP=…`), both running through `backend/.venv`
- [x] 4.4 Grep for stragglers referencing the deleted modules or `data/occurrences.duckdb` — `scripts/extract_recorded_by_people.py` (its own `DEFAULT_DB`) and `annotation.md` (points at `ingest_tbia.py`'s `COLUMNS`) both need re-pointing

## 5. Tests

- [x] 5.1 Add a fixture export (a few hundred rows: two curated datasets, one GBIF dataset, one uncurated non-GBIF dataset, one ragged row, one unparseable coordinate) plus a matching small registry
- [x] 5.2 Test the inspect step: totals, dataset inventory contents, missing-column exit, ragged-row padding, and each reconciliation section
- [x] 5.3 Test the build filter: curated rows and GBIF rows kept, uncurated non-GBIF rows dropped, dataset dropped from the registry disappears on rebuild
- [x] 5.4 Test the schema: every CSV column present under its snake_case name, the DOUBLE/TIMESTAMP/BOOLEAN casts, `TRY_CAST` NULLing a bad coordinate without dropping the row, `groups` as a list
- [x] 5.5 Test `dataset`: `num_of_rows` sums to the `occurrence` count, `in_registry` true only for curated datasets, `n_source_dataset_ids` on a multi-source dataset
- [x] 5.6 Test the guards: duplicate `tbia_dataset_id` across two institutions aborts, missing/invalid registry aborts without touching an existing store
- [x] 5.7 Test the column guard: an added column aborts, a removed column aborts, a rename reports one of each, reordered columns build fine, an existing store survives an abort, the manifest edited to match lets the build through, the store-schema fallback works with no manifest, and a first build with neither records the manifest
- [x] 5.8 Test that the inspect step reports the same column diff and still exits 0
- [x] 5.9 Test that a freshly built store has no completeness columns and that `prepare.py` then adds them and the per-dataset roll-ups
- [x] 5.10 `make test` green

## 6. Full-export dry run

- [ ] 6.1 Run `make inspect` on the 2026-08-05 export and reconcile `data/registry.json` against its output (review done; the registry edit is the operator's call — see the summary's 1 rename + ~75 uncurated non-GBIF datasets)
- [x] 6.2 Build to a side path (`data/tbia.new.duckdb`), run `make prepare --db` against it, and compare against the live store: row/dataset counts, per-institution counts, and the `occurrence` / `dataset` column sets
- [x] 6.3 Point the API at the new store, run `make test`, and check Explore facets, the Source sidebar and the Dashboard against it

## 7. Documentation

- [x] 7.1 CLAUDE.md — replace the `ingest` / `ingest-sample` command lines with `inspect` / `build-db`, update the Layout block, and describe the four-step refresh
- [x] 7.2 CLAUDE.md — rewrite the registry.json section: `data/registry.json` now gates ingest, `../tbia-data/registry-institutions.json` gates the export upstream, and the two are a one-way dependency
- [x] 7.3 CLAUDE.md — update the Gotchas entry about a fresh export having no completeness flags to name `make build-db` → `make prepare`, and document the side-path-then-swap refresh
- [x] 7.4 CLAUDE.md — document `backend/ingest/columns.json`: what it pins, that a differing export stops the build, and that accepting a change means editing and committing that file (no override flag)
- [ ] 7.5 README.md — document the refresh for an operator: download, review, edit registry, build, prepare, swap — including what to do when the build stops on a column change
