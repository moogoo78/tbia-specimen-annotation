# TBIA Specimen Annotation & Feedback Platform

A collaborative annotation platform for natural-history collection data from the
**Taiwan Biodiversity Information Alliance (TBIA)**. It serves ~1.79 million occurrence
records across 930 datasets, lets contributors **find specimens with metadata gaps**
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
| Occurrence store (read-only, ~1.92M rows) | **DuckDB** — the TBIA ETL's export; columnar, so faceting / completeness aggregation stays fast |
| Annotations + users (shared writes) | **SQLite** via SQLAlchemy |
| Federated joins (dashboard / provider export) | DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) → one SQL query |
| API | **FastAPI** (DuckDB queries run in a threadpool; JWT auth with contributor/reviewer/admin roles) |
| Frontend | **React + Vite + TypeScript**, bilingual zh-TW / English (i18next) |
| AI label transcription | Two-stage Claude vision pipeline (`backend/app/pipeline.py`): Sonnet OCRs the label, Opus turns that text into schema fields. Run as a batched queue by the platform, or by the contributor in their own AI chat via a copy-paste prompt |

Occurrence data is never mutated; enrichment lives entirely as annotations, which is why
the read store (DuckDB) and the write store (SQLite) are separate.

## Quick start (local)

Prereqs: Python 3.11+, Node 20+, and the TBIA ETL export at `data/tbia.duckdb`
(tables `occurrence` + `dataset`; see `task-tbia-data-etl.md`).

```bash
make install        # python venv + npm install
make prepare        # derive completeness flags + indexes on data/tbia.duckdb (~15s)
make seed           # create SQLite schema + demo users
make api            # terminal 1: FastAPI on :8000
make web            # terminal 2: Vite dev server on :5173
```

Open http://localhost:5173.

`make prepare` is what turns a raw export into something the API can serve — it adds the
completeness flags, `completeness_score`, `year` and the indexes, and rolls the same counts
up per dataset. It is idempotent, so **re-run it after every ETL refresh**.

**Sign-in is ORCID-only.** Copy `.env.example` to `.env` and fill in
`ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` (register a client at
[orcid.org/developer-tools](https://orcid.org/developer-tools), scope `/authenticate`,
redirect URI `http://localhost:5173/auth/orcid/callback`). List your own ORCID iD in
`ORCID_ADMIN_IDS` to get the `admin` role on first sign-in. New users default to
`contributor`. Until a client id is set, `/api/auth/orcid/*` returns 503.

### Docker (alternative)
`make prepare && make seed` on the host, then `docker compose up` (serves API on :8000 and
the frontend on :5173). The embedded DuckDB/SQLite files in `./data` are mounted in.

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
backend/   FastAPI app (app/), DuckDB prep + legacy loaders (ingest/), pytest (tests/)
frontend/  React + Vite + TS (src/: components, pages, api, i18n, design)
data/      tbia.duckdb (ETL export) + annotations.sqlite + registry.json (gitignored)
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
