# CLAUDE.md

Guidance for working in this repo. Pairs with `README.md` (user-facing setup).

## What this is

A collaborative annotation platform for TBIA natural-history specimen data (TDWG 2026
abstract: *Closing Gaps in Specimen Metadata*). Users find records with metadata **gaps**
(missing identification / coordinates / date), fill them manually or with AI-assisted label
transcription, and reviewed enrichments are exported back to data providers.

## Architecture (important)

Occurrence data is **read-only**; enrichment lives only as annotations. Hence two stores:

- **DuckDB** (`data/occurrences.duckdb`) — ~2M occurrence rows, read-only at serve time.
  Columnar → fast facets/completeness aggregation. Opened read-only; queries run in a
  threadpool (`app/duck.py`).
- **SQLite** (`data/annotations.sqlite`) — annotations + users (writes) via SQLAlchemy.
- **Federated joins**: DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) so
  dashboard/export queries join occurrences ↔ annotations in one SQL pass.
- **Backend**: FastAPI, JWT auth, roles `contributor | reviewer | admin`.
- **Frontend**: React + Vite + TS, bilingual zh-TW / English (i18next). Reuses the design
  tokens/components ported from the `naturedb-portal.zip` mockup.

## Commands

```bash
make install        # backend venv (backend/.venv) + npm install
make ingest         # load all ~2M rows -> data/occurrences.duckdb  (~35s)
make ingest-sample  # 50k-row dev slice
make seed           # SQLite schema + demo users
make api            # FastAPI on :8000   (frontend proxies /api here)
make web            # Vite dev server on :5173
make test           # pytest (backend)
make build          # frontend production build (also typechecks)
```

Backend runs from `backend/` using `backend/.venv`. Typecheck frontend with
`cd frontend && npx tsc -b`.

Demo accounts (pw `demo1234`): `curator@tbia.test` (contributor),
`reviewer@tbia.test` (reviewer), `admin@tbia.test` (admin).

## Layout

```
backend/app/        main.py, duck.py, db.py, models.py, search.py, extract.py, auth.py, config.py
backend/app/api/    occurrences.py, annotations.py, auth.py, export.py
backend/ingest/     ingest_tbia.py     (DuckDB read_csv loader)
backend/tests/      conftest.py builds a tiny DuckDB+SQLite; test_search, test_annotations
frontend/src/       pages/ (Explore, RecordDetail, Dashboard, Login), components/, api/, i18n/, design/
data/               generated DBs + registry.json + datasets.csv (gitignored)
```

## Conventions

- **Data values stay Chinese** (taxonomy `bio_group`/`kingdom_c`/…, county names). Only UI
  chrome is bilingual — add label keys to `frontend/src/i18n/index.ts` (both `en` and `zh`).
- **Completeness flags** are the product's core: `has_identification / has_coordinates /
  has_date / has_media` + `completeness_score` (0–4), computed at ingest in
  `ingest_tbia.py`. Default search sort = `completeness_score asc` (gaps first).
- Occurrence columns are snake_case (DuckDB); the CSV→column mapping lives in `COLUMNS` in
  `ingest_tbia.py`. **Changing which columns are ingested requires re-running `make ingest`**
  (DuckDB is rebuilt from scratch each run).
- Search/facet SQL is built once in `app/search.py` (`build_where`) and reused by list,
  count, and facet endpoints. Free-text is substring/`ILIKE` (no CJK tokenizer).
- AI extraction (`app/extract.py`) is a **stub** shaped like a real vision response
  (per-field value + confidence). Swap it for a Claude vision call; the UI already consumes
  this shape.

## registry.json

`data/registry.json` maps source → datasets, two-level:
`{ institutions: {...}, aggregators: {...} }`, each `CODE: { name, datasets: { <tbia_dataset_id>: { name, groups[] } } }`.
`groups` vocabulary: `Aves, Amphibia, Reptilia, Mammalia, Actinopterygii, Mollusca,
Arachnida, Insecta, Plantae, Fungi, Protozoa` (plus `Zoology`/`Other` used as broad tags).
The Explore **Source** facet is driven by this file (served via `GET /api/registry`);
selecting a source expands to the union of its `tbia_dataset_id`s.

## Gotchas

- Password hashing uses **pbkdf2_sha256** (not bcrypt) — passlib+bcrypt 4.x is broken here.
- `LoginRequest.email` is plain `str`, not `EmailStr` — demo `.test` TLD is rejected by
  email-validator.
- SQLite schema is created via `metadata.create_all` at startup (no Alembic yet).
- `init_db()` must run before `duck.connect()` (lifespan order in `main.py`) so the ATTACH
  finds the SQLite file; otherwise `annotations_attached` is false and export falls back to
  a Python-side join.
- Settings via env with `NDB_` prefix (`app/config.py`): `NDB_DUCKDB_PATH`,
  `NDB_SQLITE_PATH`, `NDB_JWT_SECRET`, `NDB_CORS_ORIGINS`.
- The Chrome browser-automation tools aren't connected in this environment — verify UI
  changes via `tsc`/`vite build` + API checks, and ask the user for visual confirmation.
