## Why

Step 2 of the TBIA data ETL process (`task-tbia-data-etl.md`) is a human review gate: before
any dataset reaches `make ingest`, a person has to look at what a fresh export actually
contains and decide which datasets belong in `data/registry.json`. Today that review has no
written record — `scripts/list_tbia_datasets.py` prints headline counts to the terminal and
they vanish, so there is nothing to diff between the two exports already sitting in the repo
(`tbia_6a2912275e9edc001925b00c.zip`, `tbia_6a56e7a62a75e6001769cb69.zip`) and no artifact to
share with providers.

The per-dataset CSV it does write is also missing the two identifiers needed to trace a
dataset back to its origin: `sourceDatasetID` (the provider's own id) and `gbifDatasetID`.
Without them, deciding whether a dataset is a natural-history collection means leaving the CSV
and going back to the source.

## What Changes

- `scripts/list_tbia_datasets.py` gains a **markdown summary report** written to a file
  (default `data/tbia_export_summary.md`), covering the export as a whole: export file name,
  export file created date (filesystem mtime of the zip/CSV), total rows, distinct dataset
  count, and distinct `rightsHolder` count.
- The report also carries the registry-diff counts the script already computes (registered vs.
  unregistered datasets, and records behind each), so the review gate is captured in one file
  rather than scrollback.
- The per-dataset CSV export gains **`source_dataset_id`** and **`gbif_dataset_id`** columns,
  sourced from the export's `sourceDatasetID` / `gbifDatasetID` fields.
- Both outputs come from the **same single scan** of the 1.85 GB export — no second pass.
- Not a breaking change: existing CSV columns and their names are preserved, the new columns
  are additive, and the markdown report is new output alongside the unchanged stdout summary.

## Capabilities

### New Capabilities
- `tbia-export-inventory`: Scanning a raw TBIA export (zip or extracted CSV) to produce a
  human-reviewable inventory of it — an export-level markdown summary and a per-dataset CSV
  including source/GBIF identifiers and registry membership — as the review gate that precedes
  ingest.

### Modified Capabilities
<!-- None. openspec/specs/ is empty; this change introduces the first spec. -->

## Impact

- **Code**: `scripts/list_tbia_datasets.py` (extended — currently untracked, so this change also
  brings it under version control). Reuses `find_zip` / `ensure_csv` from
  `backend/ingest/ingest_tbia.py`; no change to either ingest loader.
- **Outputs**: new `data/tbia_export_summary.md`; `data/tbia_datasets.csv` gains two columns.
  `data/` is gitignored, so no committed artifacts change.
- **Dependencies**: none new — DuckDB and the stdlib are already in `backend/.venv`.
- **Data pipeline**: unaffected. `data/occurrences.duckdb` is not rebuilt and `make ingest`
  needs no re-run; this change only reads the export.
- **Docs**: `task-tbia-data-etl.md` step 2 and `data-flow.md` describe this step and should
  point at the new report.
