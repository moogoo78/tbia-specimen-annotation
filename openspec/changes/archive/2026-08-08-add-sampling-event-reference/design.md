## Context

See proposal.md — Why. The facts that shape the approach:

- **A trip concept already exists and is derived.** `app/api/collectors.py:266` (`trips_sql`)
  sessionizes distinct collecting days with a `lag()` + running-sum break on a `gap` parameter
  (default 7 days, echoed back in the response). The career endpoint returns
  `{collector, gap, summary, years, trips}`. This change adds a layer beside it; it does not
  replace or reinterpret it.
- **Enrichment belongs in SQLite.** DuckDB is read-only at serve time and rebuilt wholesale by
  `make build-db`. `Collector` / `CollectorAlias` already demonstrate the pattern: key enrichment
  on something intrinsic (the raw `recorded_by` string), never on a DuckDB row id, so a re-ingest
  cannot invalidate it. Sampling events go the same way — and in fact need no join to DuckDB at
  all, only to `collectors`.
- **Curated JSON tracked in git is an established pattern here.** `data/registry.json` is
  hand-curated, decides what gets ingested, and is edited from a report rather than from memory.
  `data/sampling_events.json` is the same shape of thing, with a much smaller blast radius.
- **The source is three page scans**, 37 rows, six columns: 年代 / 植物分類學者 / 國籍 / 主要記事 /
  標本存放處. It is fixed — a 1975/1983/1986 publication does not get a new edition.
- The scans are messy in exactly the ways that decide the schema: multi-person rows (the 1905–1908
  party of fifteen), two collectors of different nationalities in one row (1898–1902), elided
  century ranges (`1960-62`), and a 主要記事 column mixing localities with narrative and
  publication history.

## Goals / Non-Goals

**Goals:**

- Store the chronology losslessly — every source column recoverable, nothing guessed away.
- Give a collector's page an upper, documented layer beside its derived trips.
- Make the chronology browsable in its own right, by era / person / place / repository.
- Keep the whole thing hand-correctable, since OCR of a 1975 scan will not be perfect.

**Non-Goals:**

- Asserting that specimens belong to chronology events (see proposal.md — Non-Goals).
- A general "reference sources" framework. One chronology, one shape, room left for a second.
- Reworking `trips_sql` or the gap heuristic.

## Decisions

### Two tables, not one

`sampling_event` holds the row; `sampling_event_actor` holds the people.

A `recorded_by` text column would have been simpler, and wrong: the 1905–1908 entry names fifteen
people, and the whole point of the feature is reaching a collector's page from an event. A join
table gives each participant its own resolved `collector_id`, its own nationality (1898–1902 needs
this — 松村任三 is 日, V. Faurie is 英), and a `position` preserving the source order.

```
sampling_event                          sampling_event_actor
  id                                      id
  event_date            eventDate         event_id   -> sampling_event.id
  verbatim_event_date   verbatimEventDate recorded_by            recordedBy   (verbatim)
  year_start / year_end (derived)         collector_id -> collectors.id  (nullable)
  verbatim_locality     verbatimLocality  nationality            (國籍, verbatim)
  event_remarks         eventRemarks      position               (source order)
  location_according_to locationAccordingTo
  narrative             (主要記事, verbatim)
  source_page / seq     (provenance back to the scan)
```

`year_start` / `year_end` are derived at seed time, not query time — range overlap on plain
integers is what the timeline and the career overlay both need, and parsing `1960-62` in SQL on
every request would be absurd.

`narrative` is deliberately separate from `verbatim_locality`. 主要記事 carries both places and
prose ("發表「台灣植物目錄」記錄 246 種"); the localities are pulled out for filtering while the full
text stays intact, so a transcription judgement call is always reversible against the source.

### `event_remarks` carries 標本存放處

Per the specified mapping. Worth being explicit that this is a choice: DwC's `eventRemarks` is a
free-text note, and 標本存放處 is closer to an institution reference. The alternative — putting the
repository in `institutionCode` — would be wrong here, because the column holds things like `英國`
and `歐、美、日`, which are countries, not institutions. `eventRemarks` as free text is the honest
home for it, and the narrative gets its own non-DwC column rather than competing for the same term.

### Transcribe once, commit the JSON

Chosen over a runtime vision endpoint. The source is fixed and small, so a live extraction path
would buy nothing but an upload flow, a review UI, and a per-request cost for a job that runs once.
Committing the JSON also makes the transcription reviewable in a diff — which matters, because the
scans include kanji names (川上瀧彌、佐佐木舜一) that OCR will sometimes get wrong and a human will
need to fix against the image.

`extract.py` stays untouched; it is the specimen-label stub and has a different shape (per-field
value + confidence for one label).

### Actors resolve on a best-effort match, and misses are kept

Match order: exact `CollectorAlias.recorded_by`, then exact `Collector.name` / `name_en`, then a
normalized comparison (whitespace and punctuation folded, so `R. Fortune` / `R.Fortune` meet).
Nothing fuzzier — a wrong link between a historical figure and a modern collector record is worse
than no link, and the seeder reports its misses so curation is directed rather than guessed.

Most of the 19th-century names will not resolve, and that is the expected outcome, not a failure:
R. Fortune's 1854 collections are not in a TBIA export. Those events still browse on `/history`
with their names as plain text.

### The career endpoint gains a key rather than a new endpoint

`GET /api/collectors/{id}/career` already assembles everything that page needs in one call
(`summary`, `years`, `trips`). Adding `reference_events` keeps that property; a separate endpoint
would mean a second round-trip for a page that already knows the collector id. Existing keys keep
their shape, so `Collector.tsx` renders unchanged until it opts in.

The lookup is a plain SQLite join (`sampling_event_actor.collector_id = ?`) — no DuckDB involvement,
so it costs nothing next to the existing occurrence aggregations.

### `/history` is its own page

The chronology reads as a document, not a facet of Explore. It is 37 rows spanning 1854–1988,
which is a timeline, not a search result set — and Explore's machinery (facets, completeness sort,
2M-row pagination) has nothing to offer it. A standalone page also gives the feature a home to link
to from a career page entry.

## Risks / Trade-offs

- **Transcription accuracy.** Scanned 1975 print with dense CJK; names like 伊藤太佑衛門 are easy to
  get subtly wrong. *Mitigation:* `source_page` + `seq` point every row back to its scan, the JSON
  is diff-reviewable, and correcting is an edit plus a re-seed.
- **Locality extraction is a judgement call.** Pulling 淡水、基隆 out of a prose sentence is
  lossy by nature. *Mitigation:* `narrative` keeps the full text, so `verbatim_locality` is a
  convenience index over the source rather than a replacement for it.
- ~~**Low resolution rate on actors.**~~ *Resolved during implementation, better than feared:*
  **32 of 57 actors resolve**, and spot-checking confirms the matches are real — 早田文藏 →
  Bunzo Hayata (634 records), 川上瀧彌 → Takiya Kawakami (2,569), R. Swinhoe → R Swinhoe (53).
  The 24 unmatched names are mostly the 19th-century British collectors whose material never
  reached a TBIA dataset, plus non-people like 群體計劃. The career-page anchor is not sparse.
- **Two names for one idea.** "Trip" now means both a derived session and a documented expedition.
  *Mitigation:* the UI labels them distinctly (derived trips vs. 調查記事 / survey record), and the
  API keys differ (`trips` vs `reference_events`).

## Migration Plan

Additive only. `metadata.create_all` at startup creates both tables (no Alembic in this repo yet),
and an unseeded deployment serves an empty chronology and an empty `reference_events` list rather
than erroring. Sequence: model + seeder + JSON land together, `make seed-sampling-events` runs, then
the API and UI. No occurrence store rebuild, no re-`make prepare`, no change to any existing
response shape.

## Resolved Questions

- **`/history` in the main nav?** Yes — added beside Collectors. It stands alone as a document, and
  the career-page section links across to it.
- **國籍 as a filter?** No. It is shown inline next to each participant, where it disambiguates a
  mixed party (松村任三 日 / V. Faurie 英), but with three or four distinct values across 37 rows it
  would be a filter that never narrows anything usefully. Free text already matches it.
- **Where does the year parsing live?** Moved into `seed_sampling_events.parse_years` during
  implementation, rather than staying in the one-off transcription script. The spec states the
  elided-century expansion as system behaviour, so the seeder now derives the range when a row
  omits it and rejects a hand-typed pair that disagrees with its own 年代 cell.
