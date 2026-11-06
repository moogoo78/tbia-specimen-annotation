# frontend/CLAUDE.md

Loaded when working under `frontend/`. Moved from the root CLAUDE.md, which still holds the cross-cutting rules.

## Explore's URL

**Explore's filter state is the query string** (`pages/exploreUrl.ts` + `useSearchParams`),
so a filtered view can be reloaded, shared, and returned to with the back button — which
matters most on the way back from a record, where the search used to have to be redone by
hand. Nothing about the filters lives in component state any more; the setters in
`Explore.tsx` kept their old signatures and write the URL instead.

- **The page's parameters are the API's parameters.** `exploreUrl.ts` builds on
  `client.ts`'s `filtersToParams` and its inverse `paramsToFilters` (kept beside it so the
  two cannot drift), so `/explore?q=x` and `/api/occurrences?q=x` mean the same thing and a
  page's query pasted onto the API returns the rows on screen.
- **"No parameters at all" is not "this parameter is absent."** `emptyFilters()` starts
  `has_media` **true** while the API convention reads an absent boolean as false, so
  `parseExplore` treats a bare `/explore` as the landing defaults and anything else as
  literal. That only holds because **`exploreParams` writes `has_media` out both ways
  round** — `has_media=false` explicitly, which `filtersToParams` (the API's own
  serialiser, where absent already means false) does not do. Without it, unchecking
  the box on the landing view serialised to *nothing*, `parseExplore` read the empty
  query back as the defaults, and it was the one filter that could not be turned off.
  `has_media=false` is what the API reads as false too, so the URL still means the
  same thing pasted onto `/api/occurrences`. Every link in goes through
  **`exploreUrl()`**, which starts from `emptyFilters()` — so an unmentioned flag keeps
  its landing default, and a link that wants every record still has to say
  `flags: { has_media: false }` explicitly.
- Edits **replace** rather than push, so the back button leaves the page instead of
  stepping through every checkbox.
- `source` and `collector_id` are serialised, not the `tbia_dataset_id` they expand into —
  writing both would let the two copies disagree. A URL carries collector **ids** only, so
  the chip labels are resolved through `GET /api/collectors/{id}` on arrival and cached.
- `activeId` (the split view's selected record) is deliberately **not** in the URL.

This replaced a router-`state` handoff that applied filters once per navigation and then
nulled itself out. If you add a link into Explore, use `exploreUrl()` — a second mechanism
is how the two drift.

**One URL write per handler.** `setSearchParams` builds the next URL from the render's
`searchParams` — even given a function it passes the closure value, not a live ref — and
`navigate` is async, so two calls in one handler both start from the pre-click URL and the
second silently discards the first. That shipped once: every facet checkbox ticked and
changed nothing. `setFilters` / `setSources` / `setView` therefore fold in their own
`offset: 0` rather than leaving the caller to add a second call.

`make test-web` (`frontend/tests/explore-url.mjs`) is what catches this class. It clicks the
real page in headless Chrome over CDP — no dependencies, Node's own WebSocket is enough —
because `tsc`, the build, and loading `/explore?bio_group=…` all stayed green while the
clicks were broken: they only ever exercised *parsing*. It needs `make api` + `make web` up,
and asserts relationally (a facet row prints its count; clicking it must make the pager
total equal *that*) so an ETL refresh cannot invalidate it.

## Page metadata (`src/seo/`)

The app is client-rendered, so the served HTML is one shell for all 17 routes. **Link
unfurlers (Slack, LINE, Twitter, Facebook) never run JavaScript**, so a title set from
React is invisible to them — which is the whole reason there is a build step here rather
than just a hook.

`src/seo/pages.json` is the single source: one entry per indexable route, `title` and
`description` in both languages, plus optional schema.org `schema` for JSON-LD. Two
consumers read it —

- **`scripts/prerender.mjs`** (run by `npm run build`) copies `dist/index.html` to
  `dist/<path>/index.html` with the head filled in, and writes `sitemap.xml` +
  robots.txt's absolute `Sitemap:` line. Injected tags are fenced in `<!-- seo:start -->`
  so a re-run replaces them rather than stacking a second copy. Caddy reaches the copies
  via `try_files {path} {path}/index.html /index.html`; unlisted routes still fall
  through to the SPA shell.
- **`src/seo/useSeo.ts`**, called once in `App.tsx`, keeps the title right after
  client-side navigation — what Google's rendered pass reads, and what `analytics.ts`
  reports as `page_title` (before it, every GA pageview carried the same static title).

**The OG cards in `public/og/` are committed PNGs, not a build product.**
`scripts/og-image.mjs` renders one per page from the same `pages.json`, through headless
Chromium — which production does not have and should not grow — so it is a dev-time tool
you re-run and commit after changing a title or description. Exactly 1200×630, the size
`prerender.mjs` declares, so the file and the declaration cannot disagree. `card.title`
overrides the headline for titles that do not set at card size (the home page's full name
wraps for one character); it does not touch the page's real `<title>`. An `og:image` must
be absolute, so with `VITE_SITE_URL` unset the tags fall back to the text-only
`summary` card rather than naming an image nobody can fetch.

It is JSON rather than i18n keys because the prerender has to read it from Node with no
TypeScript build; it stays bilingual all the same, prerender emitting `zh` to match
`<html lang="zh-Hant">`.

**`VITE_SITE_URL` is a build arg**, like `VITE_GA_MEASUREMENT_ID` — Vite inlines it, and
the prerender needs an absolute origin. Unset degrades deliberately: titles and OG tags
still ship, canonical/`og:url`/`sitemap.xml` are skipped rather than guessed at a wrong
origin. **The root `dist/index.html` gets no canonical** for the same reason: it is also
the fallback for every unlisted route, so a canonical there would claim `/record/x` is
the home page. `useSeo` sets the real one client-side.

## Annotations on the record itself

`GET /api/occurrences/{id}` already ships a record's annotation history, and
`RecordDetail.tsx` renders the latest one **as the field's value**, with the
provider's own value struck through beneath it and the status beside it
(`enrichments()` / `Enriched` / `Field`'s `ann` prop). The occurrence store stays
read-only — this is a read-time overlay, nothing is written back — and the red
"gap" rule on a field turns green once something answers it.

- **Latest per field wins.** The detail payload arrives `created desc`, so the
  first row for a field is the newest.
- **`draft` and `rejected` never overlay** (`OVERLAY_SKIP`): one is private
  working state on a page that is unauthenticated and edge-cached, the other is
  a reviewer having said no. Showing either as the specimen's value would
  publish something nobody stands behind.
- A coordinate is two annotations and a field is one value, so
  `coordinateAnnotation()` folds the lat/lon pair into one synthetic row.
- The identification gap gets the header: a record annotated with a
  `annotationScientificName` reads as that name, since that is the gap the
  platform exists to close.
