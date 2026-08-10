## Why

The platform already has a *trip* concept, but it is derived bottom-up. `GET
/api/collectors/{id}/career` (`app/api/collectors.py`, `trips_sql`) sessionizes a collector's
dated occurrence rows into runs of collecting days separated by more than `gap` idle days. That
works — dates are present on 98.7% of records where coordinates are not — but it can only ever
restate what the specimen rows already say. It cannot say **why** a collector was in a place, who
sent them, what the expedition produced, or where the specimens ended up. A Swinhoe record dated
1862 sits in the store with nothing to indicate it belongs to the 1861–1866 survey that produced
「台灣植物目錄」.

That upper layer already exists in the literature. 附錄一：台灣植物調查研究史年表 (許建昌, 1975;
黃增泉, 1983, 1986) is a curated chronology of Taiwan plant survey history — 37 entries
from 1854 to 1988, each naming the collector(s), the period worked, the localities, the
significance of the work, and the repository holding the resulting specimens. The platform holds
none of it. It exists here only as three page scans in `tmp/sampling-event/`.

This change transcribes that chronology into a first-class **sampling-event reference**: a curated,
Darwin Core–shaped record of historical collecting events that sits *above* individual occurrences,
and gives a second way into a collector's time/space data — starting from the documented expedition
rather than from the specimen rows.

## What Changes

- **New `data/sampling_events.json`** — the chronology transcribed once from
  `tmp/sampling-event/*.png` by a vision pass, then **hand-curated and tracked in git**, following
  the precedent of `data/registry.json`. The scans are a fixed historical source; there is no
  runtime extraction path and no upload flow.
- **New SQLite tables `sampling_event` + `sampling_event_actor`**, seeded from that JSON by
  `python -m app.seed_sampling_events` (`make seed-sampling-events`). Two tables because a single
  chronology row is frequently a *party*, not a person: the 1905–1908 entry names fifteen
  participants (川上瀧彌、森丑之助、島田彌市、佐佐木舜一 …), and 1898–1902 names 松村任三 and
  V. Faurie with different nationalities.
- **Darwin Core Event mapping**, per the field mapping you specified:

  | Chronology column | Field | DwC term |
  |---|---|---|
  | 植物分類學者 | `sampling_event_actor.recorded_by` | `recordedBy` |
  | 年代 | `event_date` (+ `verbatim_event_date`) | `eventDate` |
  | 主要記事 → places | `verbatim_locality` | `verbatimLocality` |
  | 標本存放處 | `event_remarks` | `eventRemarks` |
  | (constant) | `location_according_to` | `locationAccordingTo` |

  `location_according_to` is `許建昌, 1975; 黃增泉, 1983, 1986` for every row — it is the citation
  for the chronology itself, so it is stored per-row (a future second source gets its own value)
  rather than hardcoded.
- **Actors resolve to existing collectors** where possible: seeding matches each `recorded_by`
  against `Collector.name` / `name_en` and `CollectorAlias.recorded_by`, filling a nullable
  `collector_id`. Unmatched names are kept verbatim and reported, never dropped — most 19th-century
  botanists in this chronology hold no records in the TBIA export at all, and that absence is
  itself information.
- **New `GET /api/sampling-events`** (filter by free text, year range, collector; ordered
  chronologically) and **`GET /api/sampling-events/{id}`**.
- **`GET /api/collectors/{id}/career` gains `reference_events`** — the chronology entries naming
  this collector, so the career page can show the documented expedition beside the trips derived
  from their records.
- **New `/history` page** — the chronology as a browsable timeline, filterable by era, collector,
  locality and repository, each entry linking to the collector's career page.
- **Frontend i18n** keys for both `en` and `zh`, per the repo convention that only UI chrome is
  bilingual — the chronology's own values (names, localities, 標本存放處) stay Chinese.

## Impact

- **New**: `data/sampling_events.json`, `backend/app/seed_sampling_events.py`,
  `backend/app/api/sampling_events.py`, `frontend/src/pages/History.tsx`, tests.
- **Modified**: `models.py` (two tables), `main.py` (router), `api/collectors.py` (career gains
  `reference_events`), `frontend/src/pages/Collector.tsx`, `App.tsx`, `AppHeader.tsx`,
  `i18n/index.ts`, `api/types.ts`, `Makefile`, `CLAUDE.md`.
- **Untouched**: the DuckDB occurrence store. This is enrichment in SQLite, exactly like
  collectors and annotations — a fresh `make build-db` never invalidates it.
- Additive schema only; `metadata.create_all` picks the tables up at startup, no migration.

## Non-Goals

- **No runtime vision extraction.** `extract.py` stays the specimen-label stub it is.
- **No asserted provenance.** The platform will not claim that a given specimen row *belongs to* a
  chronology event. The link shown is collector identity plus date overlap, presented as historical
  context. Silently attaching 1860s records to a documented survey would manufacture provenance the
  source does not support, and it would flow into exports as if it were curated fact.
- **Not an annotation target.** Reference events are read-only reference data edited by hand in
  git, not user-submitted enrichment — they need no review workflow, roles, or export path.
- **No second chronology.** The schema leaves room (`location_according_to` is per-row), but only
  the 許建昌/黃增泉 table is transcribed here.
