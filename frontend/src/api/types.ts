export interface OccurrenceRow {
  id: string;
  catalog_number: string | null;
  scientific_name: string | null;
  name_author: string | null;
  common_name_c: string | null;
  family: string | null;
  genus: string | null;
  taxon_rank: string | null;
  bio_group: string | null;
  kingdom_c: string | null;
  county: string | null;
  locality: string | null;
  standard_latitude: number | null;
  standard_longitude: number | null;
  standard_date: string | null;
  year: number | null;
  type_status: string | null;
  dataset_name: string | null;
  recorded_by: string | null;
  record_number: string | null;
  has_coordinates: boolean;
  has_date: boolean;
  has_identification: boolean;
  has_media: boolean;
  completeness_score: number;
  thumbnail: string | null;
}

/** One rung of a record's image-size ladder (see backend/app/media.py). The URLs
 *  arrive already rewritten — the browser never builds one, so a size means the
 *  same thing here as it does to the transcription pipeline. */
export interface MediaSize {
  size: string;          // the source's own suffix: "m" | "l" | "x" | "o" for HAST
  long_edge: number;     // real pixels on the long edge, measured
  canonical: boolean;    // the rendition TBIA's export itself ships
  urls: string[];        // parallel to `media`, same order
}

export interface OccurrenceDetail extends OccurrenceRow {
  [key: string]: unknown;
  media: string[];
  /** Larger/smaller renditions of `media`, when the source publishes them.
   *  Empty for every source without a rule — the gallery then just shows `media`. */
  media_sizes: MediaSize[];
  annotations: Annotation[];
  /** Most recent AI transcription request for this record (null = never queued). */
  transcribe: TranscribeState | null;
}

export interface TranscribeState {
  id: number;
  status: "pending" | "done" | "failed" | string;
  requested_by: string | null;
  created: string | null;
  processed_at: string | null;
  error: string | null;
}

export interface SearchResult {
  total: number;
  items: OccurrenceRow[];
  limit: number;
  offset: number;
}

export interface FacetValue { value: string; count: number; }
export interface FacetResult {
  bio_group: FacetValue[];
  kingdom_c: FacetValue[];
  county: FacetValue[];
  taxon_rank: FacetValue[];
  basis_of_record: FacetValue[];
  type_status: FacetValue[];
  dataset_name: FacetValue[];
  completeness: {
    missing_coordinates: number;
    missing_date: number;
    missing_identification: number;
    has_media: number;
    total: number;
  };
}

export interface Dataset {
  dataset_name: string;
  tbia_dataset_id: string | null;
  rights_holder: string | null;
  institution_code: string | null;
  n_records: number;
  n_identified: number;
  n_georeferenced: number;
  n_dated: number;
  n_with_media: number;
  avg_completeness: number;
}

export interface Annotation {
  id: number;
  occurrence_id: string;
  dataset_name: string | null;
  field: string;
  original_value: string | null;
  proposed_value: string | null;
  source: string;
  ai_confidence: number | null;
  note: string | null;
  status: string;
  license: string;
  contributor_id: number;
  contributor_name: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created: string;
  modified: string;
}

export interface ExtractedField { field: string; value: string; confidence: number; }
export interface ExtractResponse {
  occurrence_id: string;
  // Every image the transcription read — a record's media are views of one
  // specimen, so they go into one request and yield one set of fields.
  image_urls: string[];
  model: string;
  service?: string | null;
  extracted_at?: string | null;
  fields: ExtractedField[];
}
export interface ExtractPromptResponse {
  occurrence_id: string;
  image_urls: string[];
  target_fields: string[];
  prompt: string;
}

export interface TranscribeRequest {
  id: number;
  occurrence_id: string;
  contributor_id: number;
  created: string;
  notified: boolean;
  // Queued requests come back pending / 0 — the worker moves them later. The
  // admin-only run-now route has already processed the request by the time it
  // answers, so these carry its outcome.
  status: "pending" | "done" | "failed" | string;
  processed_at: string | null;
  error: string | null;
  n_annotations: number;
}

export interface TranscribeOptions {
  mode?: "single" | "two_stage";
  ocr_model?: string;
  field_model?: string;
}

/** What the server's "auto" preset resolves to (GET /api/transcribe/config). */
export type TranscribeRoute = "queue" | "now";

export interface TranscribeConfig {
  mode: "single" | "two_stage" | string;
  ocr_model: string | null;
  field_model: string;
  // System-wide and admin-set: what *every* user's transcribe click does. Not a
  // per-user preference — the server enforces the same value it reports here.
  route: TranscribeRoute;
}

export interface DevUser { email: string; display_name: string; role: string; }
export interface DevLoginConfig { enabled: boolean; users: DevUser[]; }

export interface User { id: number; orcid?: string | null; email?: string | null; display_name: string; role: string; show_in_ranking?: boolean; default_license?: string; }

// A row of the public volunteer ranking. `name` is null unless the volunteer
// opted in — render `Contributor #<user_id>` in that case.
export interface Volunteer {
  rank: number;
  user_id: number;
  name: string | null;
  anonymous: boolean;
  n_submitted: number;
  n_accepted: number;
  n_records: number;
}
export type VolunteerRange = "all" | "month";

// A collecting trip: a run of days separated by more than the gap.
export interface Trip {
  start: string; end: string;
  n_days: number; n_records: number; n_mapped: number;
  place: string | null;
}
// One participant in a documented sampling event. `collector_id` is null when
// the name matches no collector in our store — common for 19th-century
// botanists, whose material never reached a TBIA dataset.
export interface SamplingEventActor {
  recorded_by: string;          // DwC recordedBy, verbatim from 植物分類學者
  nationality: string;          // 國籍, verbatim
  position: number;             // order the source lists them in
  collector_id: number | null;
  collector_label?: string | null;
}

// A collecting event as documented in published literature — the upper,
// curated counterpart to the `Trip`s derived from record dates above. It
// asserts no link to any specimen; overlap with a trip is context, not
// provenance.
export interface SamplingEvent {
  id: number;
  event_date: string;           // DwC eventDate — "1854" or "1861/1866"
  verbatim_event_date: string;  // DwC verbatimEventDate — the 年代 cell as printed
  year_start: number;
  year_end: number;
  verbatim_locality: string;    // DwC verbatimLocality
  event_remarks: string;        // DwC eventRemarks — the 標本存放處 column
  location_according_to: string;// DwC locationAccordingTo — the chronology's citation
  narrative: string;            // the full 主要記事 text
  source_page?: number;
  seq?: number;
  actors: SamplingEventActor[];
}

// ── curated stories ─────────────────────────────────────────────────────────
// A hand-transcribed narrative (data/story_*.json) served back with the numbers
// the occurrence store can answer for it. Counts are queries by collector +
// date window or by species name — never a stored link to a record.

export interface StorySpecies {
  name: string;            // binomial; "" when the source gives only a Chinese name
  authorship?: string;
  name_zh?: string;
  origin?: string;         // for species the story only illustrates
  n_records: number;
}

export interface StoryTrip {
  seq: number;
  verbatim_date: string;   // the heading as printed, e.g. "2011.10.24–11.06"
  date_start: string;
  date_end: string;
  precision: "day" | "month";
  narrative: string;
  // Resolved against the collector table where possible; a miss stays plain
  // text — several party members are overseas hosts with no records here.
  party?: {
    name: string; name_en?: string;
    collector_id?: number | null; collector_label?: string | null;
  }[];
  notes?: { date?: string; text: string }[];
  n_records: number;
}

export interface StoryRegion {
  key: string;
  name: string;            // 中文, verbatim
  name_en: string;
  summary?: string;
  species_heading?: string;
  trips: StoryTrip[];
  species: StorySpecies[];
}

export interface Story {
  key: string;
  source: { title?: string; citation?: string; url?: string };
  subject: {
    name: string; name_en?: string; abbreviation?: string;
    collector: { id: number; label: string; n_records: number } | null;
  };
  focus: { genus?: string; name_zh?: string; records: number; genus_only: number };
  regions: StoryRegion[];
  totals: {
    regions: number; trips: number; species: number;
    trip_records: number; species_records: number; species_present: number;
  };
}

export interface StoryIndexEntry {
  key: string;
  title: string;
  subject: { name: string; name_en?: string };
  n_regions: number;
  n_trips: number;
  n_species: number;
}

export interface Career {
  collector: { id: number; name: string; name_en: string; label: string };
  gap: number;   // idle days that end a trip — the threshold actually used

  summary: {
    n_records: number; n_dated: number; n_undated: number; n_geo: number;
    n_days: number; n_trips: number; year_min: number | null; year_max: number | null;
  };
  years: { year: number; count: number; mapped: number }[];
  trips: Trip[];
  // Chronology entries naming this collector. Reported beside `trips`, never
  // merged into them — the two answer different questions.
  reference_events: SamplingEvent[];
}

export interface Collector {
  id: number;
  name: string;       // 中文 (may be "")
  name_en: string;    // romanized (may be "")
  label: string;      // "name name_en" for display
  n_records: number;
}

// A row of the browsable collector index, counts rolled up from the occurrence
// store rather than the seeded total.
export interface CollectorBoardRow extends Collector {
  n_geo: number;
  n_unmapped: number;
  mapped_pct: number;
  year_min: number | null;
  year_max: number | null;
  n_aliases: number;
}
export type CollectorSort = "records" | "gap" | "recent" | "random";
export interface CollectorBoard {
  total: number;      // collectors matching the current filters
  items: CollectorBoardRow[];
  limit: number;
  offset: number;
  totals: { collectors: number; records: number; mapped: number };  // unfiltered
}

// The taxonomic index. A row is a *name as the store holds it*, not a resolved
// taxon: synonyms are not merged, spelling variants stay separate, and a name
// used under two kingdoms is one row (n_kingdoms > 1) covering every record
// carrying the string.
export interface SpeciesRow {
  name: string;
  n_records: number;
  n_identified: number;   // records flagged has_identification (rank species-or-below)
  taxon_rank: string;
  family: string | null;
  genus: string | null;
  kingdom_c: string | null;
  common_name_c: string;
  n_counties: number;
  n_kingdoms: number;
  year_min: number | null;
  year_max: number | null;
  n_geo: number;
  n_media: number;
  n_type: number;
}
export type SpeciesScope = "species" | "all";
export type SpeciesSort = "records" | "name";
export interface SpeciesList {
  total: number;      // names matching the current scope + search
  items: SpeciesRow[];
  limit: number;
  offset: number;
  scope: SpeciesScope;
  totals: { names: number; records: number };  // the whole index
}

export interface RegistryDataset { code?: string; name: string; groups: string[]; gbif?: string; }
export interface RegistryEntry { name: string; datasets: Record<string, RegistryDataset>; }
export interface Registry {
  institutions: Record<string, RegistryEntry>;
  aggregators: Record<string, RegistryEntry>;
}
export type SourceKind = "institutions" | "aggregators";

export interface Filters {
  q?: string;
  bio_group: string[];
  kingdom_c: string[];
  county: string[];
  taxon_rank: string[];
  scientific_name: string[];   // exact match — the species index's link into Explore
  basis_of_record: string[];
  type_status: string[];
  dataset_name: string[];
  tbia_dataset_id: string[];
  collector_id: number[];
  record_number_from?: number;
  record_number_to?: number;
  record_number?: string;
  missing_coordinates: boolean;
  missing_date: boolean;
  missing_identification: boolean;
  has_media: boolean;
  year_from?: number;
  year_to?: number;
  date_from?: string;
  date_to?: string;
  bbox?: string;
}

export const emptyFilters = (): Filters => ({
  bio_group: [], kingdom_c: [], county: [], taxon_rank: [], scientific_name: [],
  basis_of_record: [], type_status: [], dataset_name: [], tbia_dataset_id: [],
  collector_id: [],
  missing_coordinates: false, missing_date: false,
  missing_identification: false, has_media: true,
});
