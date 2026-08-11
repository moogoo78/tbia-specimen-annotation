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
  `backend/ingest/` (see *Data refresh*): table `occurrence` (~2.08M rows, 945 datasets)
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
make seed-sampling-events   # curated chronology (data/sampling_events.json) -> SQLite
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

## Sampling events (the other "trip")

**"Trip" names two different things in this codebase; do not merge them.**

- **Derived trips** — `api/collectors.py:trips_sql` sessionizes a collector's dated
  occurrence rows into runs separated by more than `gap` idle days. Bottom-up, inferred,
  returned as `trips` on `GET /api/collectors/{id}/career`.
- **Sampling events** — a *curated chronology* of documented collecting expeditions,
  transcribed from published literature. Top-down, cited, returned as `reference_events`
  on the same endpoint and browsable at `GET /api/sampling-events` + `/history`, which is
  the first topic of `/story` (`pages/Story.tsx` — its `STORY_TOPICS` array is both the
  index and what the navbar tab highlights on).

The source is 附錄一：台灣植物調查研究史年表 (許建昌, 1975; 黃增泉, 1983, 1986) — 37 entries,
1854–1988, transcribed from the scans in `tmp/sampling-event/` into
**`data/sampling_events.json`**, which is hand-curated and **tracked in git** (see the
`!/data/sampling_events.json` un-ignore, since `/data/*` is ignored wholesale). There is no
runtime vision extraction; `extract.py` remains the specimen-label stub.

Darwin Core mapping — `recordedBy` (植物分類學者), `eventDate` + `verbatimEventDate` (年代),
`verbatimLocality` (places pulled out of 主要記事), **`eventRemarks` (標本存放處)**, and
`locationAccordingTo` (the chronology's citation, stored per-row so a second source needs no
code change). The full 主要記事 text is kept in a non-DwC `narrative` column, so the locality
extraction stays a convenience index over the source rather than a replacement for it.

Two tables (`models.py`): `sampling_event` and `sampling_event_actor`. Actors are separate
because a row is often a *party* — the 1905–1908 entry names fifteen people — and each
participant carries their own 國籍 and resolves to their own collector. `seed_sampling_events.py`
matches each name against `Collector.name` / `name_en` / `CollectorAlias.recorded_by`
(exact, then whitespace/punctuation-folded — nothing fuzzier), leaves `collector_id` null on a
miss, and prints the misses. 32 of 57 actors currently resolve; the rest are mostly
19th-century botanists holding no records in the export, which is expected rather than a bug.

**Sampling events assert no specimen provenance.** Nothing links an occurrence row to an
event, and nothing should: an event overlapping a derived trip is context for the reader, not
a claim that any specimen came from that expedition. Adding such a link would manufacture
provenance the source does not support and would flow into provider exports as curated fact.

`GET /api/sampling-events/counts` is the one place the chronology touches DuckDB: per event,
how many records its *resolved* actors hold within its years — one grouped join, cached on the
actor/year signature so a re-seed invalidates it. `/history` shows that number as the specimen
column and links it into Explore (collectors + `year_from/year_to`, `has_media` cleared so the
result matches the count); zero renders as an em dash rather than a link into nothing. It
stores nothing and associates nothing — a counted record may well come from other fieldwork
the same person did those years — so keep it out of the export path.

Enrichment-side data, like collectors and annotations — a `make build-db` rebuild of the
DuckDB store never invalidates it. Re-run `make seed-sampling-events` after correcting a
transcription; it replaces both tables, so it is idempotent.

## The species index (`/species`)

The taxonomic index: one row per distinct `scientific_name` in the store (44,874 of them;
33,810 identified to species rank or below), searchable, sortable and paged, reached from
its own navbar tab. `api/species.py` rolls the whole thing up in **one grouped scan (~2.2s,
of which the modal descriptive columns are ~1.2s)**, caches it on a TTL behind a lock, and
applies scope / search / sort / paging in memory — the `collector_board` pattern, for the
same reason: DuckDB cannot page a grouped aggregate without first computing the whole
grouping, so paging in SQL would pay the full scan per request. Nothing is persisted, so a
`make build-db` rebuild cannot leave it stale and there is no seeding step.

- **A name is not a taxon.** Names are listed exactly as the store holds them. Nothing is
  reconciled against TaiCOL, WCVP or any other checklist: synonyms are not merged
  (`Lycopersicon esculentum` stays its own row), spelling and gender variants stay separate
  (`Trema orientalis` / `Trema orientale`), and a string used under two kingdoms is **one**
  row — because the row's link filters on the name alone, so grouping any finer would print
  a count no link could reproduce. `n_kingdoms > 1` flags those 21 names in the UI.
- **The default scope filters on `has_identification`, not on a rank list of its own.** That
  flag already means "rank species-or-below with a name" (`ingest/common.py`
  `SPECIES_RANKS`), so the index and the completeness gap can never disagree about what
  counts as identified. Widening to all ranks is what surfaces the 319,916 genus-level and
  123,821 family-level identifications — the identification gap, seen taxonomically.
- Descriptive columns (rank, family, genus, kingdom, common name) come from each name's
  **most-numerous** group (`mode`), never an arbitrary `any_value`.

`scientific_name` is an **exact, multi-valued filter** on the occurrence search
(`search.py` `Filters` + `build_where`, so list/count/facet all get it) and is deliberately
**not** in `FACET_COLUMNS` — 44,874 values is not a facet list, and the species page is the
picker. A row links into Explore through router `state` (the `/history` mechanism) and must
clear `has_media`, which `emptyFilters()` defaults to `true`; without that the landing page
would report fewer records than the row it was opened from.

## Curated stories (`/story`)

`/story` is the narrative layer: `pages/Story.tsx` holds `STORY_TOPICS`, which is both the
index and what the navbar tab highlights on. Two topics so far — the sampling-event
chronology (`/history`, seeded into SQLite, above) and **彭鏡毅's Begonia expeditions**
(`/story/begonia`).

The Begonia story is a different mechanism from the chronology and deliberately lighter:
`data/story_begonia.json` (hand-curated, tracked in git via the `!/data/story_begonia.json`
un-ignore) is a transcription of a BRMAS digital curation — regions → trips (verbatim date,
ISO range, `precision: day|month`, narrative, party, notes) plus the species described.
**Nothing is seeded**; `api/stories.py` reads the file at request time, caches on its mtime,
and answers it against the store:

- `trips[].n_records` — the subject collector's records inside the trip's dates.
- `species[].n_records` — records held under that binomial, store-wide.
- `focus` — the subject's records in the story's genus, and how many stop at the bare genus
  (886 of 1,468 for Peng: the identification gap, inside the story).
- `trips[].party[].collector_id` — companions matched to collectors by `app/names.py`
  (`fold` + `collector_index`, shared with the chronology seeder, which keeps them under
  their old `_norm`/`_resolver` names). 12 of 18 resolve; the misses are the overseas hosts
  and are kept verbatim, exactly as an unresolved chronology actor is.

Correct a transcription and the next request serves it — no `make` step. The same rule as
the chronology holds: **a count is not provenance.** Records are matched by collector and
date window, so a specimen counted under a trip is one that person collected those days, not
one the trip is claimed to have produced.

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
66 columns in, **2,079,798 rows / 945 datasets** (20 curated + 925 GBIF) out.

## registry.json

`data/registry.json` maps source → datasets, two-level:
`{ institutions: {...}, aggregators: {...} }`, each `CODE: { name, datasets: { <tbia_dataset_id>: { name, groups[] } } }`.
`groups` vocabulary: `Aves, Amphibia, Reptilia, Mammalia, Actinopterygii, Mollusca,
Arachnida, Insecta, Plantae, Fungi, Protozoa` (plus `Zoology`/`Other` used as broad tags).

It is **hand-curated (tracked in git), holds only the 20 stable institution datasets**
across 9 institutions, and **decides what gets ingested**: `build.py` keeps a row only if
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

Reconciled against the 2026-08-05 list (now 9 institutions / 20 datasets): NMNS gained the
鳥獸學門 mammal + bird and 古生物學門 datasets, `NTU` (TAI) was added, 林業試驗所 is split
back into `TAIF` (herbarium) and `TFRI` (insect museum) — same display name, two entries —
NMNS dataset codes went Chinese→Latin (`維管束`→`TNM`, `昆蟲`→`ENT`, …), the 農業部 prefix
was dropped from names. `TBRI` (TESRI moth + the two TAIE sets) is gone from the *upstream*
list, but its three datasets are still in the export — held by 台灣生物多樣性網絡 TBN, not by
TBRI — so only their absence here excluded them; they are curated back in and contribute
189,843 rows. Upstream absence therefore does not by itself mean a source is unavailable:
check the export before dropping an entry.

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
