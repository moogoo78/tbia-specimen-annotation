## Context

See `proposal.md` — *Why*. The constraints that shape the approach:

- **The store is read-only at serve time.** `occurrence` is rebuilt wholesale by
  `make build-db` + `make prepare`; anything derived from it that is *stored* has to be
  re-derived on every rebuild or it silently rots. The repo already carries one such
  warning (`prepare.py` must re-run or every query fails).
- **A full grouped scan is cheap.** Rolling up all 44,874 names — count, rank, family,
  genus, kingdom, county count, year span, georeferenced / media / type counts — measures
  **2.2s** over the 2,079,798-row store, and the result is ~45k small rows. (Counts alone
  are 0.23s; the modal descriptive columns are the other ~1.2s and the `count(DISTINCT)`s
  ~0.3s. The 0.82s first measured was a narrower query — the fuller figure only strengthens
  the case against re-scanning per request.)
- **There is a precedent for exactly this shape.** `api/collectors.py` rolls up all ~17k
  collectors in one scan, caches with a TTL under an `asyncio.Lock`, and serves every page,
  sort and search from memory (`_BOARD`, `_BOARD_TTL`).
- **Explore takes incoming filters through router `state`, not the URL.** `/history` hands
  Explore `{collectors, years, flags}` this way (`pages/History.tsx` → `Explore.tsx`'s
  `location.state` effect); there is no query-param filter parser to reuse.
- **Explore's default filter set is not empty**: `emptyFilters()` sets `has_media: true`, so
  any inbound link that wants to reproduce a count must clear it explicitly. `/history`
  already does.

## Goals / Non-Goals

**Goals:**

- One code path produces the index; search, sort, paging and rank scope are all applied to
  the same cached rollup, so no view can disagree with another.
- A species row's record count and the count Explore reports after following its link are
  the same number, by construction rather than by coincidence.
- Nothing new to run after a store rebuild.

**Non-Goals:**

- Beyond the proposal's non-goals (no backbone, no table, no detail page): no facet on
  `scientific_name`. The new filter is exact-match plumbing for the link, not a new Explore
  facet — a 44,874-value facet list would be unusable, and the species page *is* that
  picker.
- No change to the free-text `q` behavior. It stays substring-across-columns.

## Decisions

### Cache the whole rollup in process; do not page in SQL

**Chosen:** compute the full 44,874-row rollup in one DuckDB scan, cache it with a TTL
behind a lock, and apply search / sort / scope / paging to the cached list in Python —
`api/collectors.py`'s `_board_rows` pattern, deliberately copied rather than reinvented.

*Alternatives considered.* **(a) `GROUP BY … ORDER BY … LIMIT` per request.** DuckDB cannot
page a grouped aggregate without computing the whole grouping first, so every keystroke in
the search box would pay the full 2.2s. **(b) A materialized `species` table written by
`ingest/prepare.py`.** It would serve instantly, but it buys ~2.2s once per TTL at the cost
of a new artifact that must be rebuilt with the store — the exact failure mode CLAUDE.md
already warns about for the completeness flags. A rollup this cheap does not earn a table.
**(c) No cache, accept 2.2s.** Too slow for a page load, let alone typed search or
re-sorting.

### Group on `scientific_name` alone

**Chosen:** the group key is the name string and nothing else. Descriptive columns (rank,
family, genus, kingdom, common name) are taken from the name's most-numerous group rather
than an arbitrary `any_value`, and a name occurring under more than one kingdom is flagged
on the row so the UI can mark it.

*Rationale.* The row's link filters Explore on the name alone, so grouping by anything finer
would produce rows whose stated count no link could reproduce — the "count agrees with the
index" scenario would fail for exactly the 21 cross-kingdom homonyms. Grouping on the string
also keeps the page honest about what it is: an index of names in the data, not of taxa.

*Alternative considered:* group by `(scientific_name, kingdom_c)` and show homonyms as
separate rows. Rejected — it makes the page *look* taxonomically resolved while the
underlying filter still cannot separate the two, which is worse than showing one row and
saying so.

### Rank scope is applied after the rollup, not in the query

**Chosen:** the rollup covers every rank; the species-or-below default and the all-ranks
toggle are a filter over the cached list.

*Rationale.* One cache serves both scopes, the toggle is instant, and the two totals are
guaranteed to be drawn from the same numbers. A per-scope query would double the cache and
invite drift.

### `scientific_name` as an exact, multi-valued filter on the existing search

**Chosen:** add `scientific_name: list[str]` to `search.Filters` and one `_in_clause` call
in `build_where`, exactly like `bio_group` and the other `IN` filters.

*Rationale.* `build_where` is shared by the list, count and facet endpoints, so the filter
lands in all three at once and the record count Explore shows is computed by the same clause
that produced the species row's count. Multi-valued costs nothing here and leaves room for
a future "compare these names" selection without another schema change.

*Alternative considered:* have the link hand Explore a free-text `q`. Rejected outright —
`q` is `ILIKE '%…%'` over eleven columns, so `Begonia` would pull in `Begonia formosana`,
`Begoniaceae`, and any locality mentioning it. The counts could not agree.

### The link goes through router `state`, and clears `has_media`

**Chosen:** `<Link to="/explore" state={{ scientific_name: [name], flags: { has_media: false } }}>`,
with the `location.state` effect in `Explore.tsx` extended to read `scientific_name`.

*Rationale.* It is the established mechanism (`/history`, `/story` both use it) and needs no
URL-filter parser. Clearing `has_media` is not optional: `emptyFilters()` defaults it to
`true`, so without it a name with 400 records would land on a page reporting far fewer, and
the spec's count-agreement scenario would fail. `/history` hit this same trap and documents
it in a comment; the species link repeats the fix for the same reason.

*Known limitation:* router state does not survive a refresh or a copy-pasted URL — the
filter is lost and Explore falls back to its defaults. That is the existing behavior of
every inbound Explore link in the app; making species links shareable means giving Explore
URL-param filters, which is a separate change affecting every caller.

## Risks / Trade-offs

- **Stale counts within the TTL window** → The rollup is a cache with the same 10-minute TTL
  as the collector board. Occurrence data only changes on a store rebuild, which restarts
  the process anyway, so the window is effectively unreachable in production.
- **Memory held for ~45k rows** → Small (a few MB of dicts), and bounded by the number of
  distinct names, which grows with the export, not with traffic. If a future export
  multiplies it, the fallback is decision (b) above — a prepared table — with no API change.
- **First request after a restart pays the full scan** → 2.2s once, behind a lock so
  concurrent callers wait on one scan rather than starting several. Same as the collector
  board today.
- **The page invites taxonomic conclusions it does not support** → `Trema orientalis` and
  `Trema orientale` sit as two rows, synonyms are not merged, and a homonym is one row for
  two kingdoms. The spec makes this normative and the UI states it; the alternative
  (reconciling against a checklist) is a substantial separate change with its own review
  burden, not a detail to slip into a browse page.
- **Adding a `Species` tab crowds the navbar** → It becomes the ninth entry. It goes next to
  Explore, the tab it is closest in function to, and nothing is removed; if the bar needs
  thinning that is a design pass on its own.

## Migration Plan

None required. No schema change, no data migration, no seeding step, no config. The change
is additive: a new endpoint, a new page, a new route, a new tab, and one new optional filter
field that existing callers omit. Rollback is reverting the commit — the store is untouched.
