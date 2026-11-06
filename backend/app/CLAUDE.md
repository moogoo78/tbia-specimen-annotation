# backend/app/CLAUDE.md

Loaded when working under `backend/app/`. Moved from the root CLAUDE.md, which still holds the
cross-cutting rules (licensing, contributor naming, serving public traffic, gotchas).

## AI transcription

- **A record's images are views of one specimen, not one specimen each** — the sheet, a
  label close-up, a determination slip — and the label text is often legible in only one
  of them. So all of a record's media (deduped, capped at `TRANSCRIBE_MAX_IMAGES`, default
  4 — images dominate the token bill) go into **one** request as several `image` blocks,
  and the prompt carries `extract.MERGE_RULE`: read them together, return **one** set of
  fields, prefer a later determination slip over an older label. `extract.images()` is the
  single definition of "which images", shared by the prompt builder, the pipeline and
  `import_results.py`, so the three cannot disagree about what a transcription read.
  Responses carry `image_urls` (a list) — there is no single `image_url` anywhere.
- **The export's image URL is not the only size the source publishes.** TBIA ships
  one URL per image, and for HAST (126k records) it is a 1024px derivative — enough
  to see a herbarium sheet, not to read its label. The larger renditions sit on the
  same bucket under another filename suffix (`-x` 2048px, `-o` 4096px) and nothing in
  the export says so, which is what `data/media_variants.json` records: one rule per
  source, hand-curated and tracked in git like `registry.json`, re-read on mtime.
  `app/media.py` is its only reader, so a size name means the same thing to the
  pipeline, the API and the UI. **A size is a request, never a promise** — `at_size()`
  returns the original URL for an unruled source, an unknown size, or a filename the
  rule doesn't describe, which is what lets `pipeline._image_urls` ask for a bigger
  image unconditionally instead of branching per source. The rewrite happens there, at
  the single definition of "which images", so `image_urls` records what was really
  read. `OCR_IMAGE_SIZE` (default `x`) picks it: **2048px is the largest rendition the
  vision API does not downscale** (it caps at 2576px / ~3.75MP on the current models),
  so `-o` is bandwidth paid for pixels the model never sees, and `-l` is ~4× cheaper in
  image tokens than `-x` but frequently illegible. Only the calls that carry images are
  affected — the two-stage field pass is text-only. The record page gets the same ladder
  as `media_sizes` on the detail response and offers it as an **open-at** picker
  (remembered in `localStorage`): it changes what a thumbnail opens, never the thumbnail
  itself, so choosing 4096px costs no page weight. The copy-paste prompt still lists the
  export's own URLs.
- **We send the image bytes; we do not hand the API a URL to fetch.** An `image`
  block can name a URL instead, and that costs us no bandwidth — but it is only as
  reliable as the least cooperative media host. NMNS's (`collections.culture.tw`,
  157k records) defeats it twice: the export's `ShowGalImage.aspx` URL 302s to an
  extensionless path, and the JPEG comes back as `Content-Type: image/jpg`, which is
  not one of the four media types the API accepts. Either alone answers with the same
  opaque *"Unable to connect to the remote server"* 400, after the call is billed.
  `pipeline._image_blocks` therefore fetches each image, follows the redirect, and
  states the media type itself. Its `_SSL` context is the third quirk of the same host:
  the normal context minus `VERIFY_X509_STRICT` (chain, expiry and hostname still
  checked), because that CA chain is missing a Subject Key Identifier and Python 3.13
  rejects it by default. A fetch that fails **raises** — `process_one` records the real
  reason on the request, which is the whole improvement over a 400 that named nothing.
- **Two routes reach the same AI transcription, and they differ in who waits and who
  pays.** `POST /occurrences/{id}/transcribe-request` (any contributor) persists a
  `transcribe_requests` row and pings Discord so a human knows to run `make transcribe`;
  `POST /occurrences/{id}/transcribe-now` writes the same row and then calls
  `pipeline.process_one` inline — no Discord ping, since it has already been drained.
  Both end in the same place — the transcription stored on the request that asked for it
  (`transcribe_requests.result_json`) — so a record looks identical afterwards whichever
  ran it. A pipeline failure on the run-now route is **not** a 500 —
  `process_one` records it and the response carries `status="failed"` + `error`, exactly
  as the worker would. `process_one` runs the (synchronous) Anthropic call through
  `asyncio.to_thread`, which is what stops one admin's 30-second transcription from
  stalling every other request the API is serving.
- **An AI transcription is a proposal, not a contribution — nothing the model reads is
  attributed to anyone until a person submits it.** `pipeline.process_one` stores the
  whole `ExtractResponse` on the request and writes no annotations (there is no
  `build_annotations` any more; `import_results.py` lands its files the same way). The
  record detail serves it back as `transcribe.fields`, and the record page **auto-fills
  the annotation form** with it: only fields still empty, only once per proposal, and
  never one this contributor already submitted from the same AI value — so it can never
  overwrite typing or re-offer work already done. The panel keeps listing the proposal
  beside the form, because a field the auto-fill skipped still has to be reachable by
  hand. The copy-paste route (option 2) already worked this way and is unchanged; it now
  feeds the same `proposal` state.
  - **A submission records what the AI said next to what the person sent.**
    `annotations.ai_value` + `ai_confidence` + `ai_model`, beside the `source` the form
    already computed (`ai` kept verbatim / `mixed` edited / `manual` typed). Sent whether
    or not they differ, because "a person read it and agreed" and "no AI was involved"
    are different facts, and `ai_value != proposed_value` is the only record of what
    human judgement actually corrected. Null on a manual row. That pair is the reason the
    whole change exists: it is the measurement of how well the transcription reads a
    label, and the old flow lost it in the edit.
  - Unused proposals are kept too — an untouched transcription is still evidence of what
    the model reads, and is what a correction rate is measured against.
  - Rows written by the old flow (`source="ai"`, `status="submitted"`, no `ai_value`) are
    left exactly as they are: real history, still reviewable. Nothing new creates them.
- **Which route a click takes is one system-wide setting, not a per-caller choice.**
  `app/policy.py` holds it in `app_settings` (annotation store, so it is durable and
  backed up): `queue` (the default) or `now`. An **admin** moves it from `/me`'s
  admin section
  (`PUT /api/transcribe/config`); `GET /api/transcribe/config` reports it to everyone
  alongside the model chain, and the record page's AI panel renders whichever route is in
  force. Under `now` it is *every contributor's* click that runs and bills inline, which
  is the cost decision the setting exists to make deliberate — hence admin-only to set,
  and `queue` as the default. **`transcribe-now` enforces the same value** (admin always;
  anyone else only while the route is `now`), because the endpoint is reachable without
  the UI and "the switch is on queue" has to mean nobody is spending vision calls inline,
  not merely that nobody is being offered the button.

`policy.py` is the counterpart to `config.py`: env settings are the deployment's and need
a restart, `app_settings` rows are the admin's and take effect on the next request. Reads
are per request and uncached — a policy that needs a TTL to expire is the thing it
replaces — and an unrecognised value degrades to the default rather than erroring.
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
column and links it into Explore via `exploreUrl()` (collectors + `year_from/year_to`,
`has_media` cleared so the result matches the count); zero renders as an em dash rather than
a link into nothing. It
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
picker. A row links into Explore through `exploreUrl()` (see `frontend/CLAUDE.md`) and must
clear `has_media`, which `emptyFilters()` defaults to `true`; without that the landing page
would report fewer records than the row it was opened from.

## Contributions: public vs personal

**Two questions, two pages, and the split is who the answer is about.** There used
to be one `/dashboard` holding both — your name opt-in and your default licence
above a list of *everyone's* annotations and a table of every institution — so
neither question had a page that answered it. `/dashboard` is now only a redirect.

- **`/contributors` (公開貢獻, public, unauthenticated)** — the platform's
  contribution record: per-status totals, the ranking board, and the recent
  activity feed. Nothing here needs a session, because every row of it is already
  visible on its own record page; putting it behind a login only hid it.
- **`/me` (個人貢獻, needs a session)** — one person's own work, their standing
  choices (`show_in_ranking` + `public_display_name`, `default_license`), and,
  for those who hold a role, the 管理 block (the system-wide AI transcription
  route, the per-dataset provider export).
- **`/contributors/{id}` (public)** — one contributor's work, as others see it.
  It is `/me` minus the drafts, the settings and the admin block.

**Drafts are the line between the two.** They are private working state: they
appear on `/me` and nowhere else — not on the feed, not on a contributor's public
page, not in the ranking, and not as an overlay on a record. `api/contributions.py`
enforces this per route (`status=draft` is a 400 on the public ones), and
`OVERLAY_SKIP` in `RecordDetail.tsx` enforces it on the record.

Three shared pieces stop the surfaces from drifting:

- `contributions_store.count_columns()` — one definition of `n_submitted /
  n_accepted / n_records`, selected by both the board (`api/volunteers`) and a
  contributor's profile, so a board row and the page it opens cannot print
  different numbers.
- `contributions_store.status_counts()` — per-status totals **in SQL**, over
  conditions that deliberately exclude the caller's own `status` filter, so
  narrowing a list to one status leaves the breakdown whole. The tiles were
  `items.filter(...)` over one fetched page, which was silently wrong past row
  500 and said nothing about it.
- `contributions_store.attach_records()` — the specimen each annotation
  improved. One bounded `occurrence` lookup for the page's ids, **not** the
  federated `JOIN occurrence` in `api/export.py`: paging and ordering stay in
  SQLite where the rows live and `contributor_id` is indexed, it needs no
  `annotations_attached()` guard, and an id a re-ingested store no longer holds
  comes back null instead of dropping the row the way an inner join would.

**A contribution is displayed grouped by specimen** (`components/Contributions.tsx`,
`groupByRecord` + `ContributionList`), because someone who fixed a date, a locality
and a coordinate on one sheet did *one* piece of work and a flat list prints it as
three unrelated lines naming no specimen at all. The record heading is a group's
only link — a row-level link would have to nest inside it, which is invalid HTML,
and is why the byline could not be a link before.

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
