## Why

Every axis of this collection has an index page except the one users actually think in.
`/institutions` lists the sources, `/collectors` lists the people, `/history` and `/story`
list the expeditions — but there is no page that answers "what species are in here?".
Taxonomy is reachable only sideways: Explore is record-first, and its facets stop at
`bio_group` / `kingdom_c` / `taxon_rank`, so a user who wants *Begonia formosana* must
already know to type it into free-text search. The store holds **44,874 distinct
`scientific_name` values** over 2,079,798 records and exposes none of them as a browsable
list.

The gap is also a product argument. This platform exists to surface metadata gaps, and the
identification gap is the one gap a taxonomic index makes legible: 319,916 records stop at
a bare genus, 123,821 at a family, and 103,319 carry no name at all. A species list ranked
by record count shows immediately which names carry the collection and how long the tail
is — 9,104 names are held by a single specimen, while 90 names account for 294,505 records.

## What Changes

- **New `Species` tab in the top navbar**, between Explore and Institutions, routing to
  **`/species`** — a browsable index of every distinct `scientific_name` in the DuckDB
  occurrence store.
- **New `GET /api/species`** — one cached rollup over `occurrence`, grouped on
  `scientific_name`, returning per name: record count, `taxon_rank`, `family`, `genus`,
  `kingdom_c`, `common_name_c`, county count, year span, and coordinate / media / type
  counts. Searchable by substring on the scientific and common name, sortable, paged.
  A full ungrouped scan measures **0.82s**, so the endpoint follows the existing
  collector-board pattern (`api/collectors.py`) — roll up once, cache with a TTL, serve
  every page and sort from memory rather than re-scanning per request.
- **New `scientific_name` filter on the occurrence search** (`app/search.py` `Filters` +
  `build_where`, exact match, multi-valued like the other `IN` filters). Explore currently
  has no way to pin an exact name — free-text `q` is substring across eleven columns, so
  searching `Begonia` also returns `Begoniaceae` rows and any locality containing the
  string. Each species row links into Explore through this new filter.
- **Rank scope is a control, not a hardcoded rule.** The default view lists names at
  species rank or below (33,819 names); a toggle widens it to every rank present,
  including the genus- and family-level identifications, since those *are* the
  identification gap and hiding them would hide the point of the page.
- **Frontend i18n** keys for `en` and `zh` per the repo convention — UI chrome only, with
  taxonomic values and `common_name_c` left in their source form.

### Non-goals

- **No taxonomic backbone.** This lists the names the store contains, verbatim and
  deduplicated as strings. It does not reconcile them against TaiCOL, WCVP or any other
  checklist, does not resolve synonyms, and does not merge orthographic variants. A row on
  this page is *a name in the data*, not an assertion that the name is currently accepted.
- **No new taxon table.** Nothing is written to SQLite or DuckDB; the rollup is derived at
  request time from `occurrence` and cached in memory, so a `make build-db` rebuild cannot
  leave it stale.
- **No per-species detail page** in this change. Rows link into Explore, which already
  renders filtered result sets.

## Capabilities

### New Capabilities

- `species-browse`: a browsable, searchable index of the distinct scientific names in the
  occurrence store, with per-name record counts and coverage, reachable from the navbar and
  linking into filtered Explore views.

### Modified Capabilities

<!-- None. The existing specs (`occurrence-store-build`, `tbia-export-inspect`,
     `sampling-event-reference`) cover the ETL and the curated chronology; none of their
     requirements change. The new `scientific_name` search filter is additive and is
     specified under `species-browse` because it exists to serve the species→Explore link. -->

## Impact

- **Backend**: new `backend/app/api/species.py` (auto-registered by the `main.py` router
  loop); `app/search.py` gains a `scientific_name` field on `Filters` and a clause in
  `build_where`, which is shared by the list, count and facet endpoints.
- **Frontend**: new `pages/Species.tsx`; new route in `App.tsx`; new tab in
  `components/AppHeader.tsx`; `api/client.ts` + `api/types.ts` gain the endpoint and its
  row type; `i18n/index.ts` gains a `species` block and a `nav.species` key in both
  languages.
- **Data**: read-only. No schema change, no migration, no ingest step, and nothing to
  re-run after a store rebuild.
- **Tests**: `backend/tests/` gains coverage for the rollup shape, the search/sort/paging
  contract and the new `scientific_name` filter, against the fixture DuckDB built by
  `conftest.py`.
