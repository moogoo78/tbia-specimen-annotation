# TBIA Specimen Annotation & Feedback Platform

A collaborative annotation platform for natural-history collection data from the
**Taiwan Biodiversity Information Alliance (TBIA)**. It serves ~2.08 million occurrence
records across 945 datasets, lets contributors **find specimens with metadata gaps**
(missing taxonomic identification, coordinates, or collection date) by completeness and
holding institution, **fill those gaps** manually or with AI-assisted label transcription,
and exports the **aggregated, reviewed annotations back to the original data providers** —
a trackable feedback loop. (TDWG 2026 abstract: *Closing Gaps in Specimen Metadata*.)

See [`docs/build-summary.md`](docs/build-summary.md) for the story of how the platform was
built — the concept, the design decisions, and the development history. For an end-user
walkthrough there is a slide deck in both languages:
[`docs/user-manual-slides.md`](docs/user-manual-slides.md) /
[`docs/user-manual-slides.zh-TW.md`](docs/user-manual-slides.zh-TW.md).

## Architecture

| Concern | Choice |
|---|---|
| Occurrence store (read-only, ~2.08M rows) | **DuckDB** — built from a TBIA export by `backend/ingest/`; columnar, so faceting / completeness aggregation stays fast |
| Annotations + users (shared writes) | **SQLite** via SQLAlchemy |
| Federated joins (dashboard / provider export) | DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) → one SQL query |
| API | **FastAPI** (DuckDB queries run in a threadpool; JWT auth with contributor/reviewer/admin roles) |
| Frontend | **React + Vite + TypeScript**, bilingual zh-TW / English (i18next) |
| AI label transcription | Two-stage Claude vision pipeline (`backend/app/pipeline.py`): Sonnet OCRs the label, Opus turns that text into schema fields. Run as a batched queue by the platform, or by the contributor in their own AI chat via a copy-paste prompt |

Occurrence data is never mutated; enrichment lives entirely as annotations, which is why
the read store (DuckDB) and the write store (SQLite) are separate.

## Quick start (local)

Prereqs: Python 3.11+, Node 20+, and an occurrence store at `data/tbia.duckdb`. If you
don't have one, build it from a TBIA export first — see
[Refreshing the data](#refreshing-the-data).

```bash
make install               # python venv + npm install
make seed                  # SQLite schema + demo users
make seed-collectors       # collector index, parsed out of recorded_by
make seed-sampling-events  # the curated survey chronology behind /history
make api                   # terminal 1: FastAPI on :8000
make web                   # terminal 2: Vite dev server on :5173
```

Open http://localhost:5173.

`make seed` sets up the schema and demo users and nothing more. The last two
seeders fill tables that the first one only creates, so skipping them leaves
`/collectors` and `/history` rendering as empty pages rather than as errors.
Both read from the DuckDB store or from a git-tracked JSON file, both are safe
to re-run, and neither touches annotations.

**Sign-in is ORCID-only.** Copy `.env.example` to `.env` and fill in
`ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` (register a client at
[orcid.org/developer-tools](https://orcid.org/developer-tools), scope `/authenticate`,
redirect URI `http://localhost:5173/auth/orcid/callback`). List your own ORCID iD in
`ORCID_ADMIN_IDS` to get the `admin` role on first sign-in. New users default to
`contributor`. Until a client id is set, `/api/auth/orcid/*` returns 503.

### Docker (alternative)
Run the three seeders on the host (with a store already at `data/tbia.duckdb`), then
`docker compose up` (serves API on :8000 and the frontend on :5173). The embedded
DuckDB/SQLite files in `./data` are mounted in.

## Refreshing the data

TBIA publishes a periodic export — one CSV in a zip, ~2.1M rows and 66 columns. Building a
store from it is four steps, and **one of them is a person**: deciding which datasets the
platform should carry is a curation call, not something to automate.

Download the export and drop it in `tmp/` (gitignored), then:

```bash
# 1. inspect the export — read-only, ~3 min
make inspect ZIP=tmp/tbia_xxx.zip

# 2. act on what it found
$EDITOR data/registry.json

# 3. build a new store (~1 min)  4. derive the flags the API needs (~15 s)
make build-db ZIP=tmp/tbia_xxx.zip DB=data/tbia.new.duckdb
make prepare DB=data/tbia.new.duckdb

# swap it in, then restart the API
mv data/tbia.new.duckdb data/tbia.duckdb
```

**1. Inspect.** Streams the zip without extracting it and writes two files next to it:
`<name>-summary.md` (row/dataset/rights-holder counts, plus the diffs below) and
`<name>-datasets.csv` (one row per dataset — open it in a spreadsheet). It never writes to
the store or the registry, so it is safe to run on anything.

**2. Edit the registry.** `data/registry.json` decides what gets ingested: a row survives
only if its `tbiaDatasetID` is listed there, or its `rightsHolder` is `GBIF`. The summary
tells you exactly what to reconcile —

- *Curated but missing from this export* — the dataset is gone upstream; its entry now
  ingests nothing.
- *In this export but not in the registry* — new datasets you may want to carry. Add an
  entry to pull them in. (GBIF-held datasets are ingested regardless and are summarised as
  a count rather than listed.)
- *Renamed upstream* — the export's name for a dataset no longer matches yours. Copy the
  export's name over so the sidebar reads correctly.

Keep the file in git: it is the record of what the platform deliberately carries, and a
`git diff` is the cheapest review of a refresh.

**3. Build.** Extracts the CSV once (~1.9 GB into `tmp/`; delete it afterwards, it
re-extracts in a minute) and has DuckDB load it into a **new** store. `occurrence` mirrors
the export's columns, snake_cased, plus the registry's institution attribution; `dataset`
is rolled up from the rows actually loaded. Finishes by reporting rows per source and any
registry dataset that matched nothing.

**4. Prepare.** Adds the completeness flags, `completeness_score`, `year`, the indexes, and
the per-dataset roll-ups. **A store without this cannot be served** — every API query
errors. It is idempotent, so re-running it is always safe.

Build to a side path and swap only after preparing, as above. Building straight onto
`data/tbia.duckdb` leaves the API serving a flag-less store for the minute in between. To
roll back, keep the previous file until the new one has run for a while.

### If the build stops on a column change

`backend/ingest/columns.json` pins the export's column names. If they move, the build
refuses **before loading a row**, leaving any existing store intact:

```
EXPORT COLUMNS CHANGED vs backend/ingest/columns.json
  + collectionDate  (new in this export)
  - standardDate    (gone from this export)
```

This is deliberate. The app reads columns like `standard_date`, `class` and `order` by
name, so an upstream rename would otherwise load cleanly and then fail every query. A
rename appears as one `+` and one `-`.

To accept the change, edit `columns.json` to match the export and commit it — there is no
override flag, so that the change lands in a review next to the code reading those names.
If a column the app depends on was renamed or dropped, update `backend/app/search.py` and
`backend/ingest/prepare.py` in the same commit.

## Using it

- **Explore** — facet by biological group, county, institution, taxon rank, and especially
  **Data completeness** (missing identification / coordinates / date / has images). Default
  sort surfaces the least-complete records first. Switch between table, card grid, and a
  Taiwan map; the four-dot badge on every row shows which fields are present.
- **Record / Annotate** — open a record to see its fields with **gaps flagged in red** and
  the specimen images. Sign in, then propose values in the tabbed form (collection, event,
  taxonomy, locality, annotation-only). **Read the label with AI** offers two routes: add
  the record to the platform's batch queue, or copy the prompt into your own AI chat and
  paste the JSON reply back. Either way the values land as reviewable drafts — you verify,
  edit, and submit, and each field records whether it stayed AI, was AI·edited, or manual.
- **Dashboard** — annotation counts by status, your/all contributions, per-institution
  completeness bars, and (reviewers) **export accepted deltas** to return to a provider.

## Layout

```
backend/   FastAPI app (app/), the export -> DuckDB pipeline (ingest/), pytest (tests/)
frontend/  React + Vite + TS (src/: components, pages, api, i18n, design)
data/      tbia.duckdb (built by ingest/) + annotations.sqlite + registry.json
tmp/       downloaded TBIA exports and inspect reports (gitignored)
```

## Tests

```bash
make test     # pytest: search/facets, completeness flags, annotation lifecycle + role gating, export
```

## Notes & next steps

- Schema for the SQLite side is created via `metadata.create_all` (MVP). Swap in Alembic
  migrations for production.
- The transcription worker (`app/worker.py`) is **manual / on-demand** — queued records are
  processed when someone runs a batch, not by a scheduler. Wire it to a cron or queue
  runner if the volume justifies it.
- DuckDB free-text search is substring/`ILIKE` (good for facets + Latin names); add a
  dedicated index if ranked fuzzy Chinese search becomes important.
