# TBIA Specimen Annotation & Feedback Platform

A collaborative annotation platform for natural-history collection data from the
**Taiwan Biodiversity Information Alliance (TBIA)**. It ingests ~2 million occurrence
records, lets contributors **find specimens with metadata gaps** (missing taxonomic
identification, coordinates, or collection date) by completeness and holding institution,
**fill those gaps** manually or with AI-assisted label transcription, and exports the
**aggregated, reviewed annotations back to the original data providers** — a trackable
feedback loop. (TDWG 2026 abstract: *Closing Gaps in Specimen Metadata*.)

See [`docs/build-summary.md`](docs/build-summary.md) for the story of how the platform was
built — the concept, the design decisions, and the development history.

## Architecture

| Concern | Choice |
|---|---|
| Occurrence store (read-only, ~2M rows) | **DuckDB** — columnar; fast faceting / completeness aggregation; trivial ingest |
| Annotations + users (shared writes) | **SQLite** via SQLAlchemy |
| Federated joins (dashboard / provider export) | DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) → one SQL query |
| API | **FastAPI** (DuckDB queries run in a threadpool; JWT auth with contributor/reviewer/admin roles) |
| Frontend | **React + Vite + TypeScript**, bilingual zh-TW / English (i18next) |
| AI label transcription | Stubbed extractor (`backend/app/extract.py`) shaped for a drop-in Claude vision call |

Occurrence data is never mutated; enrichment lives entirely as annotations, which is why
the read store (DuckDB) and the write store (SQLite) are separate.

## Quick start (local)

Prereqs: Python 3.11+, Node 20+, and the TBIA export `tbia_*.zip` in the repo root.

```bash
make install        # python venv + npm install
make ingest         # load all ~2M rows -> data/occurrences.duckdb (~35s)
make seed           # create SQLite schema + demo users
make api            # terminal 1: FastAPI on :8000
make web            # terminal 2: Vite dev server on :5173
```

Open http://localhost:5173. Use `make ingest-sample` for a fast 50k-row slice during dev.

**Demo accounts** (password `demo1234`):
`curator@tbia.test` (contributor) · `reviewer@tbia.test` (reviewer) · `admin@tbia.test` (admin)

### Docker (alternative)
`make ingest && make seed` on the host, then `docker compose up` (serves API on :8000 and
the frontend on :5173). The embedded DuckDB/SQLite files in `./data` are mounted in.

## Using it

- **Explore** — facet by biological group, county, institution, taxon rank, and especially
  **Data completeness** (missing identification / coordinates / date / has images). Default
  sort surfaces the least-complete records first. Switch between table, card grid, and a
  Taiwan map; the four-dot badge on every row shows which fields are present.
- **Record / Annotate** — open a record to see its fields with **gaps flagged in red** and
  the specimen images. Sign in, then propose values per field, or click **AI extract** to
  pre-fill drafts from the label image (verify → edit → submit).
- **Dashboard** — annotation counts by status, your/all contributions, per-institution
  completeness bars, and (reviewers) **export accepted deltas** to return to a provider.

## Layout

```
backend/   FastAPI app (app/), DuckDB ingest (ingest/), pytest (tests/)
frontend/  React + Vite + TS (src/: components, pages, api, i18n, design)
data/      generated DuckDB + SQLite (gitignored)
```

## Tests

```bash
make test     # pytest: search/facets, completeness flags, annotation lifecycle + role gating, export
```

## Notes & next steps

- Schema for the SQLite side is created via `metadata.create_all` (MVP). Swap in Alembic
  migrations for production.
- Replace the stub in `app/extract.py` with a real Claude vision call (the response shape
  — per-field value + confidence — is already what the UI consumes).
- DuckDB free-text search is substring/`ILIKE` (good for facets + Latin names); add a
  dedicated index if ranked fuzzy Chinese search becomes important.
