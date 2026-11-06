# CLAUDE.md

Guidance for working in this repo. Pairs with `README.md` (user-facing setup).

## What this is

**ISLAND** — *Integrated Specimen Labels: Annotation, Network, Discovery* — a collaborative
annotation platform for TBIA natural-history specimen data (TDWG 2026 abstract: *Closing
Gaps in Specimen Metadata*). Users find records with metadata **gaps**
(missing identification / coordinates / date), fill them manually or with AI-assisted label
transcription, and reviewed enrichments are exported back to data providers.

## Architecture (important)

Occurrence data is **read-only**; enrichment lives only as annotations. Hence two stores:

- **DuckDB** (`data/tbia.duckdb`) — built from a downloaded TBIA export by
  `backend/ingest/` (see `backend/ingest/CLAUDE.md`): table `occurrence` (~2.08M rows, 945 datasets)
  + table `dataset` (one row per `tbia_dataset_id`). Read-only at serve time; columnar →
  fast facets/completeness aggregation; queries run in a threadpool (`app/duck.py`).
  `build.py` loads the export's own columns; `make prepare` adds the derived ones.
- **SQLite ×2** (`app/db.py`), split by **what it costs to lose the file**:
  - `data/annotations.sqlite` — `users`, `annotations`, `transcribe_requests`, `app_settings`
    (`Base` / `SessionLocal`). Irreplaceable; this is the one to back up, and it stays
    small (tens of KB until annotations accumulate).
  - `data/reference.sqlite` — `collectors`, `collector_alias`, `sampling_event`,
    `sampling_event_actor` (`RefBase` / `RefSessionLocal`). ~2.5 MB, and every row is
    rebuilt by `make seed-collectors` / `make seed-sampling-events`, so the file is
    disposable — delete it and re-seed. A seeder therefore **cannot** reach user work:
    it is writing a different file. Which `Base` a model inherits is what decides
    which file it lands in, and **no ForeignKey may cross the two**.
  - Deployments created before the split are migrated in place at startup by
    `db._move_reference_tables()` (copy → verify counts → drop → vacuum), in the same
    style as `_migrate_users()`. Idempotent; a restart is the whole upgrade.
- **Federated joins**: DuckDB `ATTACH`es both files read-only (`sqlite_scanner`) as
  `ann` and `ref`, so dashboard/export queries join occurrences ↔ annotations, and
  collector/story/search queries join occurrences ↔ `ref.collector_alias`, in one SQL
  pass. Each attaches independently — guard `ann.*` queries on `duck.annotations_attached()`
  and `ref.*` queries on `duck.reference_attached()`, or a missing file sends a caller
  into a query against a table DuckDB cannot see instead of its Python fallback.
- **Frontend** reuses the design tokens/components ported from the `naturedb-portal.zip` mockup.

## Commands

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
- AI extraction (`app/extract.py`) owns the field vocabulary and the copy-paste prompt;
  the real Claude vision calls live in `app/pipeline.py` (batch worker). `extract.extract()`
  is still a stub shaped like a vision response (per-field value + confidence).
- **AI transcription** — which images a request reads and at what size, why we send image
  bytes rather than URLs, the two transcription routes, AI output as a proposal (never an
  attributed contribution), and the admin route switch in `app/policy.py` — is in
  `backend/app/CLAUDE.md`. One rule from anywhere: **`transcribe-now` enforces the route
  switch** (admin always; anyone else only while it is `now`), because the endpoint is
  reachable without the UI.
- **Every annotation carries the licence its contributor released it under**, and
  the rules are **iNaturalist's** — that is the deliberate reference point, not a
  coincidence. `models.LICENSES`: `CC0-1.0` / `CC-BY-4.0` / `CC-BY-NC-4.0`, SPDX ids
  because a licence without a version is not a licence, and this value reaches data
  providers. Those three and no more: GBIF ingests only these, so iNat's fourth
  option (all-rights-reserved) would be a contribution the export could never
  deliver. Default **`CC-BY-NC-4.0`** — an unstated grant is the smallest one, never
  none — and it is also what the SQLite `ADD COLUMN` backfills onto rows written
  before the picker existed.
  - **`users.default_license` seeds; `annotations.license` binds.** An absent
    `license` on create resolves to the contributor's default; changing that default
    is prospective and touches nothing already contributed. The record form applies
    one choice to every field in a submission and may override for that submission
    alone (`frontend/src/licenses.ts` mirrors the vocabulary; nothing is kept in
    `localStorage` — the profile is the memory).
  - **Only the contributor may relicense, at any time, in any status.** A reviewer
    may edit a *value* but never restate someone else's terms, not even as admin.
    There is no freeze after `accepted`: what cannot be revoked is the copy a
    provider already took, not the record. An export is a **snapshot** — it states
    the terms in force when it ran, the delivered file keeps them, the next export
    carries the change. That is why `export.py` reads the current value and pins
    nothing.
  - `/api/export/provider` ships `license` + `license_uri` per row, because terms
    vary row by row. See *Licensing* in `docs/annotation-schema.md`.
- **A contributor's name is published only if they opted in.** `users.show_in_ranking`
  is one switch over *every* surface that names a contributor, not just the ranking it
  is named after: the contributor board, the public activity feed, a contributor's
  own page, a record's annotation history and its transcription queue line. `models.public_name()` is the
  single rule — `None` for everyone who has not opted in, else `public_display_name or
  display_name` — and it is applied **server-side**, because `GET /api/occurrences/{id}`
  is unauthenticated and edge-cached, so a name left in that payload is published however
  the page renders it. `contributor_name: null` therefore means "not for publication",
  never "no contributor": the id always ships and `frontend/src/contributors.ts` turns
  the pair into the same 未具名貢獻者 #<id> everywhere. The provider export is
  deliberately excluded (`api/export.py` ships the ORCID name) — there the name is the
  attribution the row's own CC-BY licence asks for, not site chrome, and only the
  verified one is checkable against an iD. See *Naming a contributor* in
  `docs/annotation-schema.md`.
  - **Whether to be named and *as what* are separate settings.**
    `users.public_display_name` (null = "use the ORCID name") is what an opted-in
    contributor is published as, edited beside the opt-in on `/me`. It is a
    second column rather than an edit to `display_name` because the ORCID callback
    overwrites *that* one from the token response on every sign-in, so an in-place
    edit would silently revert at the user's next login. Blank clears it back to null;
    60 chars max; retroactive, since it is a name and not a per-annotation byline.

## Feature guidance (loaded with the code)

Sampling events, the species index (`/species`), contributions public vs personal, and
curated stories (`/story`) are documented in `backend/app/CLAUDE.md`; the annotation
overlay on a record page is in `frontend/CLAUDE.md`. Rules that hold from anywhere:

- **"Trip" names two different things** — derived trips (`api/collectors.py:trips_sql`)
  and curated sampling events. Do not merge them.
- **A count is not provenance.** Never link an occurrence to a sampling event or a story
  trip; per-event/per-trip counts match by collector and date window only, and stay out
  of the export path.
- **Drafts are private.** They appear on `/me` and nowhere else — not the feed, a public
  contributor page, the ranking, or a record overlay (`draft` and `rejected` never overlay).

## Explore's URL

Explore's filter state is the query string, and every link into Explore must go through
`exploreUrl()`. The full rules (and why `has_media` is written both ways round) are in
`frontend/CLAUDE.md`, along with *Page metadata* (`src/seo/`).

## Data refresh and registry.json

The export → DuckDB path and `data/registry.json` curation are documented in
`backend/ingest/CLAUDE.md`. One rule that matters from anywhere: **`registry.json` decides what
is ingested — deleting an entry deletes those records from the next store.**

## Serving public traffic

Reads are unauthenticated and expensive (a facet rollup scans ~2M rows), so two
mechanisms bound what an open audience can cost. Both are policy in one file each —
change the policy there, not at the endpoints.

- **`app/cache.py`** stamps `Cache-Control` on every response from an **allowlist of
  route templates**, defaulting to `private, no-store`. A new endpoint is therefore
  uncached until it is added to `STATIC_ROUTES` (occurrence-store reads and seeded data,
  `s-maxage=3600`) or `LIVE_ROUTES` (moves as people annotate, 60s). `test_cache.py`
  asserts every listed template still matches a mounted route, so a rename fails the
  suite instead of quietly becoming origin load. Two invariants: a request carrying
  `Authorization` never gets a `public` response (so a shared cache can never store one
  produced under credentials, even if a listed route later grows per-user content), and
  non-200s are never cached (an error would outlive its cause at the edge).
- **`app/duck.py`** caps *concurrent* scans (`NDB_DUCK_MAX_CONCURRENCY`) rather than
  requests per client — the load that hurts arrives from many IPs at once, which per-IP
  limiting cannot see. Over the cap, a request waits `NDB_DUCK_QUEUE_TIMEOUT` then raises
  `DuckOverloaded` → 503 + `Retry-After`; a scan past `NDB_DUCK_QUERY_TIMEOUT` is
  cancelled via DuckDB's `interrupt()` (there is no `statement_timeout`) → `DuckTimeout`
  → 504. Both are plain `RuntimeError`s so `worker.py` and `import_results.py` see normal
  errors; `main.py` maps them to responses.

- **`frontend/public/robots.txt`** bounds the crawl before it starts, which the two
  mechanisms above cannot: a crawler's whole job is requesting URLs nobody has requested
  yet, so it is structurally a cache-miss generator. `/record/` (2.08M URLs) and
  `/explore` (unbounded filter permutations) are disallowed. That costs nothing worth
  having — TBIA's own portal and GBIF are canonical for the occurrence records, so ours
  would be a thin duplicate of upstream. The narrative layer stays crawlable, and it is
  the only part that is uniquely ours.

A CDN in front does nothing for `/api/*` until it is told to honour these headers, and
after an ETL refresh or a re-seed the edge must be purged — see DEPLOY.md step 7.

## Gotchas

- Password hashing uses **pbkdf2_sha256** (not bcrypt) — passlib+bcrypt 4.x is broken here.
- `LoginRequest.email` is plain `str`, not `EmailStr` — demo `.test` TLD is rejected by
  email-validator.
- SQLite schema is created via `metadata.create_all` at startup (no Alembic yet) — on
  **both** metadatas, `Base` and `RefBase`.
- `init_db()` must run before `duck.connect()` (lifespan order in `main.py`) so the ATTACH
  finds the SQLite files; otherwise `annotations_attached` / `reference_attached` are false
  and those callers fall back to a Python-side join.
- Settings via env with `NDB_` prefix (`app/config.py`): `NDB_DUCKDB_PATH` (defaults to
  `data/tbia.duckdb`), `NDB_SQLITE_PATH`, `NDB_REFERENCE_PATH`, `NDB_JWT_SECRET`,
  `NDB_CORS_ORIGINS`.
- **Every secret resolves through `Settings`, including `ANTHROPIC_API_KEY`** — never
  through a library's own env lookup. Nothing here calls `load_dotenv`, so
  `anthropic.Anthropic()` reading `os.environ` saw a *different* environment from the
  rest of the app: a key in `.env` reached it only when Compose happened to interpolate
  it, and a host `make transcribe` failed with the SDK's "Could not resolve
  authentication method" while the value sat in the file. `pipeline._client()` now passes
  it explicitly and refuses first with a message naming the file. The three env sources
  are genuinely different things: the root `.env` is read by the host (Makefile targets)
  and by **Compose's `${VAR}` interpolation** of `docker-compose.yml`; `backend/.env` is
  prod's `env_file:`, injected wholesale and the deployed container's *only* source
  (`REPO`-relative dotenv paths resolve outside the image); and a real env var beats
  both. `docker compose restart` does not re-read `env_file` — use `up -d`.
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
- **`tsc` and `vite build` say nothing about whether the UI works.** Both stayed green
  through a bug that broke every facet checkbox. For anything interactive, drive the real
  page: `make test-web` runs `frontend/tests/explore-url.mjs` (Explore's URL) and
  `nav-menu.mjs` (the header's dropdown groups, and that the row stays 38px down to 1024).
  Both are thin: `tests/cdp.mjs` holds the browser — a CDP client over Node's own
  WebSocket, `launchChrome`, and the `check`/`test`/`report` harness — so a new test is a
  `Page` subclass with the reads its own page needs, and there is one definition of how we
  drive Chrome. The browser-automation tools are connected when the Chrome extension is
  running, which is the other way to check.
