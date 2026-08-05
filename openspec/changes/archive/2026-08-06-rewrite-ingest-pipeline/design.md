## Context

See proposal.md — Why. The technical facts that shape the approach:

- The live store (`tbia.duckdb`, 1.92M rows / 930 datasets) has an `occurrence` table of 76
  columns and a `dataset` table of 17. `prepare.py` and `GET /api/datasets` read
  `dataset.{tbia_dataset_id, dataset_name, source_dataset_id, gbif_dataset_id, rights_holder,
  institution_code, institution_name, dataset_code, groups, in_registry, num_of_rows,
  n_source_dataset_ids}` — but `../tbia-data/tbia-to-duckdb.py` only ever creates `occurrence`.
  The `dataset` table was built by SQL that exists in no file. **Reproducing it is the main new
  work.**
- The 2026-08-05 export is 2,113,068 rows / 1,018 datasets / 12 rights holders, and carries a
  column (`misapplied`) the old hand-maintained loader column list does not know about — which is
  why the new `occurrence` mirrors the CSV header instead of enumerating columns.
- `data/registry.json` is two-level (`institutions` / `aggregators`), whereas
  `../tbia-data/registry-institutions.json` is flat institutions. The build must walk both sections.
- Three existing modules overlap with the new ones: `../tbia-data/tbia-stats.py` (streaming stats),
  `scripts/list_tbia_datasets.py` (DuckDB stats **plus** a registry diff), and
  `../tbia-data/tbia-to-duckdb.py` (the filtered load).
- Frozen decisions from the proposal round: build and prepare stay separate commands; the legacy
  loaders are deleted; the zip is extracted to a CSV once and DuckDB reads the file.

## Goals / Non-Goals

**Goals:**

- One command per step, all inside `backend/ingest/`, all driven by `data/registry.json`.
- An `occurrence` schema that survives TBIA adding or renaming columns without a code edit.
- A `dataset` table that is reproducible from the export, closing the "built by lost SQL" gap.
- Refresh a live deployment without a window where the API serves a flag-less store.

**Non-Goals:**

- Changing `prepare.py`'s derivation logic, the API, or the frontend.
- Incremental / delta loads. A refresh is a full rebuild.
- Automating the registry edit — it stays a human decision, which is the point of the inspect step.
- Retiring `../tbia-data`. It keeps producing the export; this repo stops depending on its registry.

## Decisions

### The inspect step streams with `csv`; the build step hands the file to DuckDB

`inspect.py` is a port of `tbia-stats.py`: `csv.reader` over a `zipfile` member, constant memory,
no DuckDB. `build.py` goes the other way — `read_csv(...)` on an extracted file, so DuckDB's
parallel scanner does the work and no row passes through Python.

*Why not one engine for both:* the inspect step runs before anything is trusted, on a file that may be
ragged or missing columns, and must degrade to a readable error — Python's `csv` gives that. The
build moves 2M×70 fields, where a Python row loop is the wrong tool. *Why not DuckDB for
inspect too* (as `scripts/list_tbia_datasets.py` does): it makes inspect inherit the build's
failure modes for no gain, and the streaming version already exists and is proven on multi-GB exports.

Two consequences to carry over from `tbia-stats.py`: raise `csv.field_size_limit` (TBIA `synonyms`
/ `associatedMedia` exceed the 128 KB default) and write both outputs as `utf-8-sig` so Excel reads
the Chinese names.

### `inspect.py` absorbs `scripts/list_tbia_datasets.py`'s registry diff

The diff — curated-but-absent, present-but-uncurated, renamed — is the part that actually tells the
operator what to edit, and it already exists in `scripts/list_tbia_datasets.py`. Rather than keep
two scripts that scan the same export, `inspect.py` grows a reconciliation section over the counts
it already has and `scripts/list_tbia_datasets.py` is deleted.

GBIF datasets are counted, not listed: there are ~900 of them, they are ingested without curation,
and enumerating them buries the dozen rows the operator must act on.

### `occurrence` is projected from the CSV header, not from a column list

`build.py` reads the header row, snake-cases each name (`tbiaDatasetID` → `tbia_dataset_id`,
`verbatimSRS` → `verbatim_srs`), and emits one projection per column. Only three sets are cast:
DOUBLE (`standardLatitude`, `standardLongitude`, `standardOrganismQuantity`,
`standardRawLatitude`, `standardRawLongitude`), TIMESTAMP (`created`, `modified`, `standardDate`,
`sourceCreated`, `sourceModified`), BOOLEAN (`dataGeneralizations`, `match_higher_taxon`).
Everything else stays VARCHAR, matching the fields doc and the live store.

Casts are `TRY_CAST` off an `all_varchar=true` read, so one unparseable coordinate NULLs a field
instead of failing the load or dropping the row.

*Alternative rejected:* the `ingest_tbia.py` model of an explicit `(raw, target, expr)` table. It
gives per-column control but silently drops anything TBIA adds — `misapplied` is already missing
from it — and every refresh becomes a code edit. Mechanical naming costs us `class` / `order` /
`references` needing quoting downstream, which the app already handles.

### A changed column set aborts the build, checked against a manifest with the store as fallback

Mirroring the CSV header makes the build survive an upstream column change — which is exactly the
problem: `search.py` reads `standard_latitude` / `standard_date` / `class` / `order` by name, and a
rename upstream would produce a store that loads cleanly and then 500s on every query. So the
header is pinned.

`backend/ingest/columns.json` holds the expected raw CSV column names, in export order, tracked in
git. Before loading a single row, `build.py` compares the export's header against it as a **set**
(order is irrelevant — the projection matches by name) and aborts on any difference, printing the
added and removed names. A rename shows up as one of each.

When the manifest is absent, the baseline falls back to the existing store's `occurrence` columns,
minus the four the build adds itself (`institution_code`, `institution_name`, `dataset_code`,
`groups`) and the six `prepare.py` adds (`has_coordinates`, `has_date`, `has_identification`,
`has_media`, `year`, `completeness_score`) — comparing snake_cased export names against store
column names. With neither manifest nor store, the build records the export's header as the
manifest and proceeds; that is the first-build case on a fresh checkout, where there is nothing to
diverge from yet.

Accepting a change is a hand edit of `columns.json` — no override flag. The flag would be the thing
people reach for under time pressure, which is how a renamed column reaches production; an edit
that has to be committed puts the change in front of a reviewer, next to the code that reads those
column names.

The inspect step performs the same comparison and reports it in the summary, but never fails on it
— so the operator learns the build will stop *before* spending time reconciling the registry.

*Alternative rejected:* checking only the columns the app actually reads. It is the narrower, more
targeted guard, but it needs a hand-maintained list of app-facing columns that would drift from
`search.py` and `prepare.py` — and a dropped column nobody reads today is still a signal that the
export changed shape.

### The registry is joined in SQL via a temp table, not filtered in Python

`build.py` flattens `data/registry.json` (both `institutions` and `aggregators`) into one row per
dataset — `{tbia_dataset_id, institution_code, institution_name, dataset_code, groups}` — writes it
to a temp JSON file, and loads it with `read_json` into a TEMP table. The load is then a single
statement:

```
LEFT JOIN registry_map r ON s."tbiaDatasetID" = r.tbia_dataset_id
WHERE r.tbia_dataset_id IS NOT NULL OR s."rightsHolder" = 'GBIF'
```

with `COALESCE(r.institution_code, 'GBIF')` supplying attribution. This is `tbia-to-duckdb.py`'s
proven shape; the change is that it walks two sections and that `groups` arrives as a real
`VARCHAR[]` through `read_json` rather than a delimited string.

Flattening is also where the duplicate-id check lives: the same `tbia_dataset_id` under two
institutions is an operator error in the registry and aborts the build, because a silent
`LEFT JOIN` would fan the row out into duplicates.

### `dataset` is derived from `occurrence` after the load

One `INSERT ... SELECT ... GROUP BY tbia_dataset_id` over the loaded rows: `num_of_rows` =
`count(*)`, `n_source_dataset_ids` = `count(DISTINCT source_dataset_id)`, `in_registry` =
`institution_code <> 'GBIF'` resolved against the registry map (not the string, so a curated GBIF
entry would still read true), and `any_value(...)` for the descriptive columns. Deriving it from
the loaded rows rather than the registry means the counts can never disagree with `occurrence`.

The completeness roll-up columns are deliberately *not* created here — `prepare.py` adds them with
`ALTER TABLE ... ADD COLUMN`, and it drops-then-adds, so it is indifferent to whether they exist.

### The engine is the `duckdb` Python module

`tbia-to-duckdb.py` supports both the CLI and the module. `backend/requirements.txt` already pins
`duckdb`, `prepare.py` uses the module, and `make` runs everything through `backend/.venv` — so
requiring the CLI on PATH would be a new deploy dependency for no benefit. Module only.

### Refreshing a live store: build to a side path, prepare, then swap

`build.py` replaces whatever is at its target path, so building straight onto `data/tbia.duckdb`
leaves the API serving a flag-less store until `make prepare` finishes — every query errors in
between. The documented refresh therefore builds to `data/tbia.new.duckdb`, prepares that, and
moves it into place. `build.py` ends by printing the prepare command with its `--db` already
filled in.

*Alternative rejected:* chaining prepare into build. The operator explicitly chose to keep the
steps separate, and separate steps are what make the side-path swap possible.

### `ingest/common.py` holds what outlives the legacy loaders

`REPO`, `SPECIES_RANKS`, `find_zip()`, `ensure_csv()` and `camel_to_snake()` move into
`ingest/common.py`; `prepare.py`'s `from ingest.ingest_tbia import REPO, SPECIES_RANKS` becomes an
import from there. Nothing else in `backend/` or `frontend/` imports the deleted modules.

## Risks / Trade-offs

- **A dataset silently dropped from `data/registry.json` deletes its records from the next store.**
  → The inspect step's "missing from export" / "not in registry" sections are the guard, and
  `build.py` reports per-institution counts plus unmatched registry ids at the end. Registry.json is
  tracked in git, so a bad edit is one `git diff` away from being caught.
- **The registry becomes load-bearing in two repos.** `../tbia-data/registry-institutions.json` is
  still the ETL's own filter, so an institution dropped *there* never reaches the export and no
  edit here can bring it back. → Documented in CLAUDE.md as a one-way dependency: that file gates
  the export, `data/registry.json` gates the store.
- **The column manifest is a second thing to keep in sync**, and an operator who edits it without
  reading the diff defeats the guard entirely. → It is one file of ~70 strings, it only changes when
  TBIA changes, and the edit lands in a commit next to the code reading those names. The review
  step reporting the same diff means the operator has usually seen it before the build stops them.
- **The guard is on column names, not on what the columns contain.** An upstream change that keeps
  `standard_date` but starts filling it with a different format passes the check. → Out of scope
  here; the inspect step's counts and the completeness percentages `prepare.py` prints are where a
  content change surfaces.
- **Extraction costs ~2 GB of disk** on top of the zip and the store. → `ensure_csv()` skips
  re-extraction when the file is already there at the right size, and the CSV can be deleted after
  the build.
- **Full rebuild, no incremental path.** A refresh is ~2M rows; acceptable at this size, and it
  keeps the store a pure function of (export, registry).

## Migration Plan

1. Land the new modules alongside the old ones; delete the legacy loaders and
   `scripts/list_tbia_datasets.py` in the same change.
2. Rebuild the current store from the 2026-08-05 export through the new path and compare against
   the live `tbia.duckdb`: row count, dataset count, per-institution counts, and the `occurrence` /
   `dataset` column sets. Row counts will differ legitimately — `TBRI` left the ETL's institution
   list, and the export itself moved — so the comparison is a sanity check on shape, not equality.
3. Swap the store in, run the API's test suite plus a manual Explore/Dashboard check.
4. Rollback is keeping the previous `tbia.duckdb` file until step 3 passes.

## Open Questions

- Whether `data/registry.json` should eventually carry the GBIF datasets too, replacing the
  request-time merge in `GET /api/registry`. Out of scope here: the merge works, and pinning ~900
  ids that turn over every export is the thing registry.json deliberately avoids.
