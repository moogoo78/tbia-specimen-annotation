## 1. Search filter

- [x] 1.1 Add `scientific_name: list[str] = field(default_factory=list)` to `Filters` in `app/search.py`
- [x] 1.2 Add the matching `_in_clause("scientific_name", f.scientific_name, ...)` call in `build_where` — exact match, alongside the other `IN` filters, so list / count / facet endpoints all pick it up from the one place
- [x] 1.3 Accept the parameter on the occurrence endpoints in `app/api/occurrences.py` that already take the other array filters (`Query(default=[])`), leaving every existing caller unaffected when it is omitted
- [x] 1.4 Do **not** add `scientific_name` to `FACET_COLUMNS` — see design.md, *Non-Goals*: 44,874 values is not a facet list

## 2. Species rollup endpoint

- [x] 2.1 Create `app/api/species.py` with `router = APIRouter(prefix="/api", tags=["species"])` and add `"species"` to the router-name tuple in `main.py`'s `_mount_routers` (the loop is an explicit list, not auto-discovery)
- [x] 2.2 Write the rollup query: `GROUP BY scientific_name` over `occurrence` where `scientific_name IS NOT NULL AND scientific_name <> ''`, returning per name — `n_records`, `taxon_rank`, `family`, `genus`, `kingdom_c`, `common_name_c`, `n_counties`, `year_min`, `year_max`, `n_georeferenced`, `n_media`, `n_type`
- [x] 2.3 Take the descriptive columns (rank, family, genus, kingdom, common name) from the name's **most-numerous** group rather than `any_value`, and set an `n_kingdoms` (or equivalent) field so the UI can mark the cross-kingdom homonyms — see design.md, *Group on `scientific_name` alone*
- [x] 2.4 Cache the rollup with a TTL behind an `asyncio.Lock`, mirroring `_board_rows` / `_BOARD_TTL` in `app/api/collectors.py`, so concurrent first-callers wait on one scan
- [x] 2.5 `GET /api/species` — apply, in this order, over the cached list: rank scope, substring search on scientific + common name (case-insensitive), sort, then `limit`/`offset`; return `{items, total}` where `total` counts names matching scope + search, not the page
- [x] 2.6 Support `sort` on record count and scientific name in both directions; default to record count descending
- [x] 2.7 Support `scope` with a species-or-below default (`species`, `subspecies`, `variety`, `form`, `special form`, `hybrid formula`) and an all-ranks option
- [x] 2.8 Make paging deterministic — add scientific name as a tiebreaker on the count sort, so the 9,104 single-record names cannot reshuffle between pages

## 3. Frontend

- [x] 3.1 Add the row type and the `species` client call to `frontend/src/api/types.ts` + `api/client.ts`; add `scientific_name` to the `Filters` type and to `emptyFilters()` as `[]`
- [x] 3.2 Build `pages/Species.tsx` — searchable, sortable, paged table following `pages/Collectors.tsx`: name, common name, rank, family, records, counties, year span, georeferenced/media indicators
- [x] 3.3 Add the rank-scope toggle, defaulting to species-or-below, resetting to page 0 on change (the `reset(setX)` helper in `Collectors.tsx`)
- [x] 3.4 Mark rows whose name occurs under more than one kingdom, with a title/tooltip saying the row counts every record carrying the string
- [x] 3.5 Link each row to `/explore` via router `state`: `{ scientific_name: [name], flags: { has_media: false } }` — clearing `has_media` is required, `emptyFilters()` defaults it to `true` and the count would otherwise disagree
- [x] 3.6 Extend the `location.state` effect in `pages/Explore.tsx` to read `scientific_name` and seed the filter; add its removable chip to the active-filter row like the other array filters
- [x] 3.7 Route `/species` in `App.tsx` and add the `Species` tab in `components/AppHeader.tsx`, placed after Explore
- [x] 3.8 Add `nav.species` and a `species.*` block to `i18n/index.ts` in **both** `en` and `zh`; taxonomic values and `common_name_c` stay as the store holds them
- [x] 3.9 State on the page that names are listed as the store holds them — not reconciled against a checklist, synonyms not merged — so the page cannot be read as a taxonomic authority

## 4. Tests

- [x] 4.1 Add a genus-rank *named* row to `ROWS` in `backend/tests/conftest.py` (the current fixture's two coarse rows have a null `scientific_name`, so nothing exercises the scope toggle), and update the store-total assertions in `test_search.py` that the extra row shifts
- [x] 4.2 `test_species.py`: the index returns one row per distinct non-empty `scientific_name`, and the null-name rows produce no row
- [x] 4.3 Per-name counts equal a direct count of records carrying that exact name
- [x] 4.4 Default scope lists species-or-below only; the all-ranks scope additionally returns the genus-rank name
- [x] 4.5 Substring search is case-insensitive over scientific and common name, and `total` reflects the search rather than the page
- [x] 4.6 Sorting by count and by name, both directions, with paging that neither repeats nor skips a name
- [x] 4.7 `test_search.py`: the `scientific_name` filter matches exactly — filtering on a genus name does not return the binomials beginning with it — and the count endpoint agrees with the species row's count
- [x] 4.8 Confirm a second request is served from cache (no second scan) — e.g. by asserting the rollup helper is called once across two requests

## 5. Docs

- [x] 5.1 Add a short section to `CLAUDE.md` covering the species index: derived-and-cached, never persisted; grouped on the name string alone; and the standing rule that **a name is not a taxon** — no checklist reconciliation happens here
- [x] 5.2 Note in that section that `scientific_name` is an exact filter and deliberately not a facet
- [x] 5.3 Run `make test` and `cd frontend && npx tsc -b` (browser automation is unavailable in this environment — ask the user to confirm the page visually)
