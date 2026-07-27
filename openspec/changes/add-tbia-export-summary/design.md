## Context

`scripts/list_tbia_datasets.py` already scans a TBIA export with DuckDB and writes
`data/tbia_datasets.csv`, one row per `tbiaDatasetID`, with a registry diff. It is untracked
WIP. Two exports sit at the repo root as zips; one is currently extracted to
`source/tbia_6a56e7a62a75e6001769cb69.csv` (1.85 GB, ~72 columns).

The gap is durability and traceability: the export-level figures a reviewer needs (rows,
datasets, rights holders) only ever reach stdout, and the CSV lacks the identifiers
(`sourceDatasetID`, `gbifDatasetID`) that let a reviewer trace a dataset to its origin without
leaving the file.

Constraints that shape the design:

- The export is large enough that a second full pass is a real cost, and `ensure_csv` already
  materializes ~1.85 GB into `data/`. One scan.
- The script must keep working on both exports, which may not carry an identical column set.
- Everything downstream of this step is human (`task-tbia-data-etl.md` step 3 updates
  `registry.json` by hand), so output is optimized for reading, not for machine consumption.

## Goals / Non-Goals

**Goals:**

- Persist the export-level summary as markdown a reviewer can read, diff between exports, and
  hand to a provider.
- Put `sourceDatasetID` / `gbifDatasetID` in the per-dataset CSV.
- Keep both outputs honest and mutually consistent, from a single scan.

**Non-Goals:**

- Updating `registry.json`. That stays a human decision (ETL step 3).
- Filtering datasets or building a DuckDB (ETL steps 4–5, `ingest_filtered.py`).
- Diffing two exports against each other. The markdown file makes that possible with `diff`
  later; the script compares an export against the registry only.
- Touching `make ingest` or `data/occurrences.duckdb`.

## Decisions

### Fold the export into a small grouped table in one scan; derive both outputs from it

`CREATE TEMP TABLE facts AS SELECT ... count(*) FROM read_csv(...) GROUP BY tbia_dataset_id,
rights_holder, source_dataset_id, gbif_dataset_id, bio_group`, then compute the report figures
and the per-dataset rows from `facts`.

Alternative considered: keep the current multi-CTE query and add the report figures as extra
aggregates. Rejected because whether DuckDB scans `read_csv` once or twice then depends on CTE
inlining behavior rather than on anything the script states, and a second aggregate over the raw
rows risks a second 1.85 GB pass. Folding first makes "one scan" a property of the code, and the
fold's cardinality is bounded by datasets × holders × groups — hundreds of rows, not millions.

### Count distinct rights holders from the fold, not from the per-dataset rows

The existing query takes `any_value(rightsHolder)` per dataset. Counting distinct values of that
column would undercount whenever one dataset carries more than one holder. The report counts
`count(DISTINCT rights_holder)` across `facts`, independent of dataset grouping.

### Representative per-dataset values are the most frequent non-empty value

`any_value()` picks arbitrarily when a dataset carries several names or holders. The fold already
has counts, so per-dataset `dataset_name`, `rights_holder`, `source_dataset_id`, and
`gbif_dataset_id` become the highest-count non-empty value — deterministic, and consistent with
how `bio_groups` is already ranked by frequency. This can change an existing column's value only
where `any_value` was arbitrary to begin with.

### Export created date = filesystem mtime of the input

Per the choice made when proposing: the mtime of the zip when the script resolved one, otherwise
the mtime of the CSV given with `--csv`. The report names which file the date came from, since
`ensure_csv`'s extracted CSV has an mtime reflecting extraction, not the export. The data's own
`created` column is not read — a record-age span is a different question, and skipping it keeps
the column out of the scan.

### `--new-only` narrows the CSV, never the report

The report always describes the whole export; the flag filters CSV rows only. A report whose
"total rows" silently meant "rows in unregistered datasets" would be actively misleading in the
exact artifact meant to be trusted and diffed.

### Report layout

Headline figures as a small table (export file, created date, total rows, datasets, rights
holders), then the registry review (registered vs. not, with record counts; datasets registered
but absent from the export), then the largest unregistered datasets. Written with plain string
building — no template dependency. Existing stdout output stays as-is.

## Risks / Trade-offs

- **Older exports may lack `sourceDatasetID` / `gbifDatasetID`; naming a missing column in the
  SELECT is a DuckDB binder error that would kill the whole run** → probe the header once
  (`DESCRIBE`/`LIMIT 0` against `read_csv`, no full scan) and substitute `NULL` for absent
  columns, so the run degrades to an empty column instead of failing. Both repo zips should be
  checked during implementation.
- **`ignore_errors=true` (kept from the existing readers) silently drops malformed rows, so
  "total rows" means rows parsed, not lines in the file** → say "rows parsed" in the report
  rather than implying a file-level guarantee.
- **The fold changes the shape of the existing query, which currently produces a CSV the user has
  already been reading** → existing column names and ordering are preserved; verify the new run's
  dataset count and `n_records` against the current `data/tbia_datasets.csv` before accepting.
- **`data/` is gitignored, so the report is not itself a version-controlled record** → acceptable;
  it is an artifact to read and share, and can be copied into the repo deliberately if a given
  export's review is worth committing.
