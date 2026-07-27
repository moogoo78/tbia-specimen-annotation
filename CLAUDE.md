# CLAUDE.md

Guidance for working in this repo. Pairs with `README.md` (user-facing setup).

## What this is

A collaborative annotation platform for TBIA natural-history specimen data (TDWG 2026
abstract: *Closing Gaps in Specimen Metadata*). Users find records with metadata **gaps**
(missing identification / coordinates / date), fill them manually or with AI-assisted label
transcription, and reviewed enrichments are exported back to data providers.

## Architecture (important)

Occurrence data is **read-only**; enrichment lives only as annotations. Hence two stores:

- **DuckDB** (`data/tbia.duckdb`) — the TBIA ETL's export (`task-tbia-data-etl.md`):
  table `occurrence` (~1.79M rows, 927 datasets) + table `dataset` (one row per
  `tbia_dataset_id`). Read-only at serve time; columnar → fast facets/completeness
  aggregation; queries run in a threadpool (`app/duck.py`). The ETL owns the raw
  columns; `make prepare` adds the derived ones the app needs.
- **SQLite** (`data/annotations.sqlite`) — annotations + users (writes) via SQLAlchemy.
- **Federated joins**: DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) so
  dashboard/export queries join occurrences ↔ annotations in one SQL pass.
- **Backend**: FastAPI, JWT auth, roles `contributor | reviewer | admin`.
- **Frontend**: React + Vite + TS, bilingual zh-TW / English (i18next). Reuses the design
  tokens/components ported from the `naturedb-portal.zip` mockup.

## Commands

```bash
make install        # backend venv (backend/.venv) + npm install
make prepare        # derive flags/indexes on the ETL's data/tbia.duckdb (~15s)
make ingest         # LEGACY CSV loader -> data/occurrences.duckdb
make ingest-sample  # LEGACY 50k-row dev slice
make seed           # SQLite schema + demo users
make api            # FastAPI on :8000   (frontend proxies /api here)
make web            # Vite dev server on :5173
make test           # pytest (backend)
make build          # frontend production build (also typechecks)
```

Backend runs from `backend/` using `backend/.venv`. Typecheck frontend with
`cd frontend && npx tsc -b`.

**Auth is ORCID-only** (OAuth Authorization Code). There is no password login. The
backend never sees a password: `GET /api/auth/orcid/config` hands the frontend the
authorize params, the browser round-trips through ORCID, and `POST /api/auth/orcid/callback`
exchanges the `code` for the iD+name (from the `/authenticate` token response) → upserts a
`User` keyed on `orcid` → issues our JWT. Config via plain `ORCID_*` env vars — no `NDB_` prefix (per-field `validation_alias` in
`config.py`); see `.env.example`. `ORCID_ADMIN_IDS` grants `admin` on first sign-in, else
`contributor`. `seed.py` still
creates the three demo `User` *rows* (`curator/reviewer/admin@tbia.test`, no password) so
local dev + tests have deterministic users; tests mint JWTs directly via `auth.create_token`
(`conftest.auth_header`). Switching ORCID client id later (personal→official) is just an
`.env` change — users are keyed on iD, so sessions and data survive.

## Layout

```
backend/app/        main.py, duck.py, db.py, models.py, search.py, extract.py, auth.py, config.py
backend/app/api/    occurrences.py, annotations.py, auth.py, export.py
backend/ingest/     prepare.py (derives flags on the ETL export — the live path);
                    ingest_tbia.py / ingest_filtered.py (legacy read_csv loaders)
backend/tests/      conftest.py builds a tiny DuckDB+SQLite; test_search, test_annotations
frontend/src/       pages/ (Explore, RecordDetail, Dashboard, Login), components/, api/, i18n/, design/
data/               tbia.duckdb (ETL export) + annotations.sqlite + registry.json (gitignored)
```

## Conventions

- **Data values stay Chinese** (taxonomy `bio_group`/`kingdom_c`/…, county names). Only UI
  chrome is bilingual — add label keys to `frontend/src/i18n/index.ts` (both `en` and `zh`).
- **Completeness flags** are the product's core: `has_identification / has_coordinates /
  has_date / has_media` + `completeness_score` (0–4) + `year`. The ETL does **not** produce
  them — `ingest/prepare.py` (`make prepare`) derives them in place on `occurrence`, and
  rolls the same counts up onto `dataset`. It is idempotent, so **re-run it after every ETL
  refresh** or the flags/indexes go missing. Default search sort = `completeness_score asc`
  (gaps first).
- Occurrence columns are the ETL's snake_case names, used verbatim from SQL through the API
  to the frontend: `standard_latitude / standard_longitude / standard_date` (a TIMESTAMP,
  narrowed to DATE on every read — see `DATE_EXPR` in `search.py`), and `class` / `order` /
  `references`, which need quoting in SQL and bracket access in TS.
- `bio_group` has ~21 fine-grained values in this export (`被子植物`, `蛾類`, … — the older
  coarse `維管束植物` / `昆蟲` are gone). `BIO_GROUP_TONE` in `design/tokens.ts` maps the
  splits onto the parent group's tone; unlisted groups take the neutral fallback rather
  than a new hue.
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

It is **hand-curated and holds only the 13 stable institution datasets.** The GBIF
aggregator's datasets (914 of them) turn over with every TBIA export, so their ids are
*not* pinned here — `GET /api/registry` reads them from the `dataset` table at request
time and merges them under `aggregators`, keyed by `institution_code`. The GBIF uuid
comes from `source_dataset_id` (the export's own `gbif_dataset_id` is empty). Curated
entries always win: anything registry.json lists is left untouched, so promoting a
dataset to "stable" is just adding it to the file.

The Explore **Source** facet is driven by that merged response; selecting a source
expands to the union of its `tbia_dataset_id`s.

## Gotchas

- Password hashing uses **pbkdf2_sha256** (not bcrypt) — passlib+bcrypt 4.x is broken here.
- `LoginRequest.email` is plain `str`, not `EmailStr` — demo `.test` TLD is rejected by
  email-validator.
- SQLite schema is created via `metadata.create_all` at startup (no Alembic yet).
- `init_db()` must run before `duck.connect()` (lifespan order in `main.py`) so the ATTACH
  finds the SQLite file; otherwise `annotations_attached` is false and export falls back to
  a Python-side join.
- Settings via env with `NDB_` prefix (`app/config.py`): `NDB_DUCKDB_PATH` (defaults to
  `data/tbia.duckdb`), `NDB_SQLITE_PATH`, `NDB_JWT_SECRET`, `NDB_CORS_ORIGINS`.
- A fresh ETL export has no completeness flags, so the API errors on every query until
  `make prepare` has run over it.
- The Chrome browser-automation tools aren't connected in this environment — verify UI
  changes via `tsc`/`vite build` + API checks, and ask the user for visual confirmation.
