import { filtersToParams, paramsToFilters } from "../api/client";
import { emptyFilters, type Filters } from "../api/types";
import type { CollectorRef } from "../components/CollectorSelect";

/**
 * Explore's filter state, in the URL.
 *
 * It used to live in `useState` seeded from router `state`, which meant a
 * filtered view could not be reloaded, shared, or returned to with the back
 * button after opening a record. The URL is now the single source: everything
 * below round-trips through the query string, using the same parameter names
 * `filtersToParams` sends to the API — so a page URL's query can be pasted onto
 * `/api/occurrences` and return exactly the rows on screen.
 *
 * `has_media` is the trap this has to get right. `emptyFilters()` starts it
 * **true**, while the API convention (and `paramsToFilters`) reads an absent
 * boolean as false. So a URL carrying no parameters at all means "the defaults",
 * not "everything off" — `parseExplore` distinguishes the two, and Explore
 * normalises a bare `/explore` into an explicit URL on arrival, after which
 * every state is written out in full.
 */

export type View = "table" | "grid" | "map" | "split";

export const DEFAULT_SORT = "completeness_score";
export const DEFAULT_VIEW: View = "table";

/** Everything Explore keeps in the URL. */
export interface ExploreState {
  filters: Filters;
  /** Source selection at child granularity: "institutions:BRMAS/<datasetId>". */
  sources: string[];
  /** Selected collector ids; labels are resolved for display, not stored here. */
  collectorIds: number[];
  sort: string;
  offset: number;
  view: View;
}

export function emptyExplore(): ExploreState {
  return {
    filters: emptyFilters(),
    sources: [],
    collectorIds: [],
    sort: DEFAULT_SORT,
    offset: 0,
    view: DEFAULT_VIEW,
  };
}

const VIEWS: View[] = ["table", "grid", "map", "split"];

export function parseExplore(sp: URLSearchParams): ExploreState {
  // No parameters at all -> the landing state, whose has_media is true. Reading
  // it through paramsToFilters instead would silently turn that default off.
  if ([...sp.keys()].length === 0) return emptyExplore();

  const offset = Number(sp.get("offset"));
  const view = sp.get("view") as View | null;
  return {
    filters: paramsToFilters(sp),
    sources: sp.getAll("source"),
    collectorIds: sp.getAll("collector_id").map(Number).filter(Number.isFinite),
    sort: sp.get("sort") || DEFAULT_SORT,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
    view: view && VIEWS.includes(view) ? view : DEFAULT_VIEW,
  };
}

export function exploreParams(s: ExploreState): URLSearchParams {
  // The dataset ids and collector ids in `filters` are derived at query time
  // from `sources`/`collectorIds`, so they are never serialised from here —
  // that would write each selection twice and let the two copies disagree.
  const p = filtersToParams({ ...s.filters, tbia_dataset_id: [], collector_id: [] });
  for (const src of s.sources) p.append("source", src);
  for (const id of s.collectorIds) p.append("collector_id", String(id));
  if (s.sort !== DEFAULT_SORT) p.set("sort", s.sort);
  if (s.offset > 0) p.set("offset", String(s.offset));
  if (s.view !== DEFAULT_VIEW) p.set("view", s.view);
  return p;
}

/** What a link into Explore may hand over. Mirrors the router-`state` shape it
 *  replaces, so the call sites read the same. */
export interface ExploreLink {
  q?: string;
  collector?: CollectorRef;
  collectors?: CollectorRef[];
  years?: { from?: number; to?: number };
  /** A documented trip is a date range, not a year — see /story. */
  dates?: { from?: string; to?: string };
  /** The species index hands an exact name, not free text — see /species. */
  scientific_name?: string[];
  sources?: string[];
  bio_group?: string[];
  flags?: Partial<Pick<Filters,
    "missing_identification" | "missing_coordinates" | "missing_date" | "has_media">>;
}

/**
 * The `/explore?…` URL for a link handing over filters.
 *
 * Built on `emptyFilters()` so an unmentioned flag keeps its landing default —
 * which is how the router-`state` handoff behaved, since it applied onto state
 * that already held those defaults. A link that wants every record must
 * therefore say `flags: { has_media: false }` explicitly, exactly as before;
 * without it the destination reports fewer records than the row it was opened
 * from.
 */
export function exploreUrl(link: ExploreLink): string {
  const s = emptyExplore();
  const collectors = [...(link.collector ? [link.collector] : []), ...(link.collectors ?? [])];
  s.collectorIds = [...new Set(collectors.map((c) => c.id))];
  s.sources = link.sources ?? [];
  if (link.q) s.filters.q = link.q;
  if (link.bio_group?.length) s.filters.bio_group = [...link.bio_group];
  if (link.scientific_name?.length) s.filters.scientific_name = [...link.scientific_name];
  if (link.years) {
    s.filters.year_from = link.years.from;
    s.filters.year_to = link.years.to;
  }
  if (link.dates) {
    s.filters.date_from = link.dates.from;
    s.filters.date_to = link.dates.to;
  }
  if (link.flags) Object.assign(s.filters, link.flags);
  const qs = exploreParams(s).toString();
  return qs ? `/explore?${qs}` : "/explore";
}
