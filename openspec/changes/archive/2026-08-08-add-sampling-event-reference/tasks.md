## 1. Transcribe the chronology

- [x] 1.1 Read the three scans in `tmp/sampling-event/` and transcribe all ~50 rows, capturing every column verbatim: 年代, 植物分類學者, 國籍, 主要記事, 標本存放處
- [x] 1.2 Write `data/sampling_events.json` — one object per chronology row with `verbatim_event_date`, `event_date` (ISO 8601, `1861/1866` for ranges), `year_start`, `year_end`, `verbatim_locality`, `event_remarks` (標本存放處), `narrative` (full 主要記事), `location_according_to` (`許建昌, 1975; 黃增泉, 1983, 1986`), `source_page`, `seq`, and an `actors` array of `{recorded_by, nationality, position}`
- [x] 1.3 Expand elided ranges (`1960-62` → 1960/1962) into `year_start`/`year_end` while keeping `verbatim_event_date` as printed
- [x] 1.4 Split multi-person rows into separate actors, preserving source order — verify against the 1905–1908 entry (fifteen names) and 1898–1902 (松村任三 日 / V. Faurie 英)
- [x] 1.5 Proofread the CJK names against the images (川上瀧彌、佐佐木舜一、伊藤太佑衛門、早田文藏 …); note in the file's header comment that it is hand-curated and diff-reviewed
- [x] 1.6 Add `!/data/sampling_events.json` to `.gitignore` beside the existing `!/data/registry.json` (line 17) — `/data/*` is ignored wholesale, so without this the curated file silently never gets committed

## 2. Schema + seeding

- [x] 2.1 Add `SamplingEvent` to `models.py`: `id`, `event_date`, `verbatim_event_date`, `year_start`, `year_end` (indexed), `verbatim_locality`, `event_remarks`, `location_according_to`, `narrative`, `source_page`, `seq`, `created`
- [x] 2.2 Add `SamplingEventActor`: `id`, `event_id` FK (indexed), `recorded_by`, `collector_id` nullable FK to `collectors` (indexed), `nationality`, `position`; relationship both ways
- [x] 2.3 Write `app/seed_sampling_events.py` (`python -m app.seed_sampling_events`): load the JSON, validate required fields, replace both tables in one transaction so re-runs are idempotent
- [x] 2.4 Resolve actors to collectors in the seeder: exact `CollectorAlias.recorded_by`, then exact `Collector.name` / `name_en`, then a normalized (whitespace + punctuation folded) comparison; leave `collector_id` null on no match
- [x] 2.5 Report at the end of seeding: events loaded, actors loaded, actors resolved, and the list of unmatched names
- [x] 2.6 Fail with a clear message on malformed JSON, a missing `year_start`, or an empty `actors` array — rather than seeding a partial chronology
- [x] 2.7 Add `make seed-sampling-events` to the Makefile

## 3. API

- [x] 3.1 Create `app/api/sampling_events.py` with `router = APIRouter(prefix="/api", tags=["sampling-events"])`; register it in `main.py`
- [x] 3.2 `GET /api/sampling-events` — ordered by `year_start` ascending, each event carrying its actors (with resolved collector id/label where present)
- [x] 3.3 Add `year_from` / `year_to` filters using span **overlap** (`year_start <= year_to AND year_end >= year_from`), not containment
- [x] 3.4 Add `collector_id` filter (join through `sampling_event_actor`)
- [x] 3.5 Add free-text `q` — substring/`ILIKE` across actor names, `verbatim_locality`, `event_remarks` and `narrative`, matching the platform's no-tokenizer convention
- [x] 3.6 `GET /api/sampling-events/{id}` — one event with actors; 404 when absent
- [x] 3.7 Extend `collector_career` in `api/collectors.py` with `reference_events` (SQLite join on `sampling_event_actor.collector_id`), leaving `summary` / `years` / `trips` shapes untouched
- [x] 3.8 Confirm an unseeded database returns an empty list from both endpoints rather than erroring

## 4. Frontend

- [x] 4.1 Add the response types to `frontend/src/api/types.ts` and client calls to `api/client.ts`
- [x] 4.2 Build `pages/History.tsx` — chronological timeline, one entry per event, showing period, participants, locality, repository and narrative
- [x] 4.3 Add era / collector / locality / repository filters to the page, wired to the endpoint's query params
- [x] 4.4 Link an entry's participant to `/collectors/{id}` when resolved; render plain text when not
- [x] 4.5 Route `/history` in `App.tsx` and add the nav entry in `AppHeader.tsx`
- [x] 4.6 Add a reference-events section to `pages/Collector.tsx`, presented beside the derived trips and labelled so the two are not confused (documented survey record vs. trips derived from record dates)
- [x] 4.7 Add all new label keys to `i18n/index.ts` in **both** `en` and `zh`; keep chronology data values in Chinese
- [x] 4.8 State the source citation (`許建昌, 1975; 黃增泉, 1983, 1986`) visibly on `/history` — it is the provenance of everything on the page

## 5. Tests

- [x] 5.1 Extend `backend/tests/conftest.py` with a small sampling-event fixture (a single-year event, a range event, a multi-actor event, one resolved and one unresolved actor)
- [x] 5.2 `test_sampling_events.py`: default chronological order; year-range overlap including an event that starts before the range; collector filter; free-text match; 404 on unknown id
- [x] 5.3 Test date parsing directly: `1854`, `1861-1866`, `1960-62`
- [x] 5.4 Test the seeder is idempotent (run twice → identical rows) and that an unmatched actor is retained with a null `collector_id`
- [x] 5.5 Test `career` returns `reference_events` for a documented collector, an empty list for an undocumented one, and an unchanged `trips` shape in both
- [x] 5.6 `make test` green; `cd frontend && npx tsc -b` and `make build` clean

## 6. Documentation

- [x] 6.1 Document the two-store split in `CLAUDE.md` — `data/sampling_events.json` as curated tracked data, and `make seed-sampling-events` in the Commands block
- [x] 6.2 Note in `CLAUDE.md` that "trip" now names two distinct things (derived session vs. documented survey event) and which API key is which
- [x] 6.3 Record in `CLAUDE.md` that sampling events assert no specimen provenance, so a later contributor does not "fix" it by linking occurrences
- [x] 6.4 Ask the user to confirm `/history` and the career-page section visually — Chrome automation is not connected in this environment
