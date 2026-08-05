## Why

The data refresh path is currently split across two repos and three half-obsolete scripts. The
live `data/tbia.duckdb` is produced by `../tbia-data` (`tbia-stats.py`, `tbia-to-duckdb.py`, plus
an ad-hoc `dataset` roll-up that exists in no script at all), filtered by *that* repo's
`registry-institutions.json` — while this repo's `data/registry.json` is a second, hand-curated
copy of the same institution list that only labels the UI. Two registries drift, and the step
that actually built the `dataset` table cannot be re-run.

Meanwhile `backend/ingest/` still ships `ingest_tbia.py` and `ingest_filtered.py`, which build a
differently-shaped `occurrences.duckdb` the app no longer reads.

This change makes `backend/ingest/` own the whole refresh, with `data/registry.json` as the single
source of truth for what gets ingested.

## What Changes

- **New `ingest/inspect.py` (`make inspect ZIP=…`)** — streams a downloaded TBIA `.zip`/`.csv` and
  writes `<name>-summary.md` (row/dataset/rightsHolder counts) and `<name>-datasets.csv` (one row
  per `tbiaDatasetID` with name, source/GBIF ids, holders, row count), plus a **registry diff**:
  which curated datasets vanished from the export and which uncurated non-GBIF datasets are new.
  Ported from `../tbia-data/tbia-stats.py`, which stays where it is — this is the in-repo copy the
  refresh workflow uses. Read-only: it never touches the store or the registry.
- **Human step**: the operator reads the review output and edits `data/registry.json` by hand.
- **New `ingest/build.py` (`make build-db ZIP=…`)** — extracts the CSV once, then has DuckDB load
  it into a fresh `data/tbia.duckdb`:
  - `occurrence` keeps **every CSV column**, snake_cased (`tbiaDatasetID` → `tbia_dataset_id`),
    with only coordinates/dates/booleans cast off `VARCHAR`.
  - A row is kept when its `tbiaDatasetID` is listed in `data/registry.json` **or** its
    `rightsHolder` is `GBIF`. Everything else is dropped.
  - Registry columns (`institution_code`, `institution_name`, `dataset_code`, `groups`) are joined
    on during the load; GBIF rows get `institution_code = 'GBIF'`.
  - The `dataset` table is built from the loaded rows (`num_of_rows`, `n_source_dataset_ids`,
    `in_registry`, …) — the roll-up that currently exists only as lost ad-hoc SQL.
- **New column guard**: an export whose column set differs from the recorded baseline **stops the
  build before it loads a row**, leaving the existing store intact. Mirroring the CSV header would
  otherwise let an upstream rename produce a store that loads cleanly and then 500s on every query,
  because `search.py` reads `standard_latitude` / `standard_date` / `class` / `order` by name. The
  baseline is a tracked `backend/ingest/columns.json`, falling back to the existing store's schema
  and, on a fresh checkout, recorded from the first export. Accepting a change is a hand edit of
  that file — deliberately no override flag. `inspect.py` reports the same diff without failing, so
  the operator sees it before reconciling the registry.
- **`ingest/prepare.py` stays a separate step** (`make prepare`), unchanged in behaviour: it adds
  the completeness flags, `year`, `completeness_score`, indexes and per-dataset roll-ups. `build.py`
  finishes by reminding the operator to run it.
- **BREAKING — legacy loaders removed**: `ingest/ingest_tbia.py`, `ingest/ingest_filtered.py` and
  the `ingest` / `ingest-sample` make targets are deleted. `SPECIES_RANKS` and `REPO`, which
  `prepare.py` imports from `ingest_tbia`, move into a shared `ingest/common.py`.
- **`data/registry.json` becomes the ingest filter**, not just a display map. `../tbia-data`'s
  `registry-institutions.json` is no longer this repo's upstream to mirror; the CLAUDE.md
  reconciliation instruction is rewritten to match.

## Capabilities

### New Capabilities
- `tbia-export-inspect`: inspecting a downloaded TBIA export before ingest — inventory of datasets
  and rights holders, and the diff against the curated registry that tells the operator what to
  edit.
- `occurrence-store-build`: building `data/tbia.duckdb` from an export — the registry ∪ GBIF row
  filter, the CSV-faithful `occurrence` schema, and the derived `dataset` table.

### Modified Capabilities
<!-- none — openspec/specs/ is empty; the two capabilities above are the first specs in this repo. -->

## Impact

- **Code**: `backend/ingest/` rewritten — `inspect.py`, `build.py`, `common.py` added;
  `ingest_tbia.py`, `ingest_filtered.py` deleted; `prepare.py` re-pointed at `common.py`.
- **New tracked file**: `backend/ingest/columns.json`, the expected export header. It has to be
  edited (and committed) whenever TBIA changes the export's columns, or no build will run.
- **Build**: `Makefile` loses `ingest` / `ingest-sample`, gains `inspect` / `build-db`.
- **Data**: `data/registry.json` gains a load-bearing role (a dataset dropped from it disappears
  from the next store). Its shape is unchanged, so `GET /api/registry` and the Explore Source
  facet are unaffected.
- **Schema**: `occurrence` keeps its current column names and adds the CSV columns the old ETL
  dropped; `dataset` keeps the exact columns `prepare.py` and `GET /api/datasets` already read.
- **Docs**: CLAUDE.md (commands, registry.json, gotchas) and README.md refresh instructions.
- **Not affected**: the API, the frontend, `annotations.sqlite`, and the ATTACH-based export join.
