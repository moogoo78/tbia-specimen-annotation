# CLAUDE.md

Guidance for working in this repo. Pairs with `README.md` (user-facing setup).

## What this is

A collaborative annotation platform for TBIA natural-history specimen data (TDWG 2026
abstract: *Closing Gaps in Specimen Metadata*). Users find records with metadata **gaps**
(missing identification / coordinates / date), fill them manually or with AI-assisted label
transcription, and reviewed enrichments are exported back to data providers.

## Architecture (important)

Occurrence data is **read-only**; enrichment lives only as annotations. Hence two stores:

- **DuckDB** (`data/tbia.duckdb`) — built from a downloaded TBIA export by
  `backend/ingest/` (see *Data refresh*): table `occurrence` (~1.89M rows, 942 datasets)
  + table `dataset` (one row per `tbia_dataset_id`). Read-only at serve time; columnar →
  fast facets/completeness aggregation; queries run in a threadpool (`app/duck.py`).
  `build.py` loads the export's own columns; `make prepare` adds the derived ones.
- **SQLite** (`data/annotations.sqlite`) — annotations + users (writes) via SQLAlchemy.
- **Federated joins**: DuckDB `ATTACH`es the SQLite file (`sqlite_scanner`, read-only) so
  dashboard/export queries join occurrences ↔ annotations in one SQL pass.
- **Backend**: FastAPI, JWT auth, roles `contributor | reviewer | admin`.
- **Frontend**: React + Vite + TS, bilingual zh-TW / English (i18next). Reuses the design
  tokens/components ported from the `naturedb-portal.zip` mockup.

## Commands

```bash
make install        # backend venv (backend/.venv) + npm install
make inspect ZIP=tmp/tbia_x.zip        # 1. survey an export + diff vs registry.json
#                                        2. edit data/registry.json by hand
make build-db ZIP=tmp/tbia_x.zip DB=…  # 3. load it into a new DuckDB (~75s)
make prepare DB=data/tbia.new.duckdb   # 4. derive flags/indexes (~12s); DB= optional
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
backend/ingest/     common.py (export access, registry, column baseline), inspect.py
                    (survey an export), build.py (export -> DuckDB), prepare.py
                    (derive flags), columns.json (the pinned export header)
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

## Data refresh

`backend/ingest/` owns the whole path from a downloaded export to a servable store. Four
steps, one of which is a human:

```bash
make inspect ZIP=tmp/tbia_xxx.zip         # 1. ~3 min; writes <name>-summary.md + -datasets.csv
                                          # 2. read the summary, edit data/registry.json
make build-db ZIP=tmp/tbia_xxx.zip DB=data/tbia.new.duckdb   # 3. ~75s
make prepare DB=data/tbia.new.duckdb                          # 4. ~12s
mv data/tbia.new.duckdb data/tbia.duckdb                      # swap in
```

- **inspect.py** is read-only and streams the zip (constant memory, no extraction). Its
  summary carries the counts, the registry diff and the column diff.
- **build.py** extracts the CSV once (~1.9 GB into `tmp/`, gitignored) and lets DuckDB scan
  it. `occurrence` mirrors the export's columns snake_cased — every column, no hand-kept
  list — plus the registry's `institution_code / institution_name / dataset_code / groups`.
  `dataset` is rolled up from the rows actually loaded, so its counts cannot drift.
- Downloaded exports live in `tmp/`; `find_zip()` looks there first, then the repo root.

The 2026-08-05 export (`tbia_6a72e385d2fb88001772ccd4`): 2,113,068 rows / 1,018 datasets /
66 columns in, **1,889,955 rows / 942 datasets** (17 curated + 925 GBIF) out.

## registry.json

`data/registry.json` maps source → datasets, two-level:
`{ institutions: {...}, aggregators: {...} }`, each `CODE: { name, datasets: { <tbia_dataset_id>: { name, groups[] } } }`.
`groups` vocabulary: `Aves, Amphibia, Reptilia, Mammalia, Actinopterygii, Mollusca,
Arachnida, Insecta, Plantae, Fungi, Protozoa` (plus `Zoology`/`Other` used as broad tags).

It is **hand-curated (tracked in git), holds only the 17 stable institution datasets**
across 8 institutions, and **decides what gets ingested**: `build.py` keeps a row only if
its `tbiaDatasetID` is listed here or its `rightsHolder` is `GBIF`. Deleting an entry
deletes those records from the next store, so edit it from `make inspect`'s report rather
than from memory. The GBIF
aggregator's datasets (925 of them) turn over with every TBIA export, so their ids are
*not* pinned here — `GET /api/registry` reads them from the `dataset` table at request
time and merges them under `aggregators`, keyed by `institution_code`. The GBIF uuid
comes from `source_dataset_id` (the export's own `gbif_dataset_id` is empty). Curated
entries always win: anything registry.json lists is left untouched, so promoting a
dataset to "stable" is just adding it to the file.

**Anything uncurated falls into `aggregators`, not just GBIF** (`occurrences.py`, the
`reg["aggregators"].setdefault(...)` merge). So an institution missing from registry.json
shows up in the UI under 整合平台 instead of 典藏機構 — and because entries are matched on
`tbia_dataset_id`, a stale *code* keeps working silently while the sidebar shows the old
name. `make inspect` reports exactly this — curated-but-absent, present-but-uncurated, and
renamed-upstream — so run it before every refresh and edit from its output.

`../tbia-data/registry-institutions.json` is a **separate, upstream** filter and no longer
something to mirror: it gates which records reach the *export* (TBIA's own ETL drops
anything not listed there or held by GBIF), while `data/registry.json` gates which of the
exported records reach *our store*. The dependency is one-way — an institution dropped
upstream never appears in the export, and no edit here brings it back.

Reconciled against the 2026-08-05 list (8 institutions / 17 datasets): NMNS gained the
鳥獸學門 mammal + bird and 古生物學門 datasets, `NTU` (TAI) was added, 林業試驗所 is split
back into `TAIF` (herbarium) and `TFRI` (insect museum) — same display name, two entries —
NMNS dataset codes went Chinese→Latin (`維管束`→`TNM`, `昆蟲`→`ENT`, …), the 農業部 prefix
was dropped from names, and `TBRI` (TESRI moth + the two TAIE sets, ~138k rows) is gone
from the institution list, so those records drop out of the next export.

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
- **`NDB_DEV_MODE` is the "throwaway local environment" switch, default off.** It
  permits the placeholder `NDB_JWT_SECRET` (the repo is public, so a deploy that
  keeps it is trivially forgeable — `Settings` raises at import otherwise) and is
  required alongside `NDB_DEV_LOGIN` for the password-less demo sign-in. Check
  `settings.dev_login_enabled`, never `settings.dev_login`. `docker-compose.yml`
  (dev) sets `NDB_DEV_MODE=true`; `docker-compose.prod.yml` must never set it.
- A freshly built store has no completeness flags, so the API errors on every query until
  `make prepare` has run over it. **Build to a side path and swap after preparing** —
  building straight onto `data/tbia.duckdb` leaves the live API broken for the ~90s in
  between.
- **`backend/ingest/columns.json` pins the export's 66 columns.** `build.py` compares the
  export header against it (falling back to the target store's schema, then to recording a
  new baseline) and **aborts before loading** on any difference — the app reads
  `standard_date`, `class`, `order` and friends by name, so an upstream rename would load
  clean and then fail every query. A rename shows as one `+` and one `-`. Accept a change by
  editing the file and committing it; there is deliberately no override flag.
- The Chrome browser-automation tools aren't connected in this environment — verify UI
  changes via `tsc`/`vite build` + API checks, and ask the user for visual confirmation.
