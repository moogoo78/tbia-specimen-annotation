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

export interface OccurrenceDetail extends OccurrenceRow {
  [key: string]: unknown;
  media: string[];
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
  image_url: string | null;
  model: string;
  service?: string | null;
  extracted_at?: string | null;
  fields: ExtractedField[];
}
export interface ExtractPromptResponse {
  occurrence_id: string;
  image_url: string | null;
  target_fields: string[];
  prompt: string;
}

export interface TranscribeRequest {
  id: number;
  occurrence_id: string;
  contributor_id: number;
  created: string;
  notified: boolean;
}

export interface TranscribeOptions {
  mode?: "single" | "two_stage";
  ocr_model?: string;
  field_model?: string;
}

/** What the server's "auto" preset resolves to (GET /api/transcribe/config). */
export interface TranscribeConfig {
  mode: "single" | "two_stage" | string;
  ocr_model: string | null;
  field_model: string;
}

export interface DevUser { email: string; display_name: string; role: string; }
export interface DevLoginConfig { enabled: boolean; users: DevUser[]; }

export interface User { id: number; orcid?: string | null; email?: string | null; display_name: string; role: string; show_in_ranking?: boolean; }

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
export interface Career {
  collector: { id: number; name: string; name_en: string; label: string };
  gap: number;   // idle days that end a trip — the threshold actually used

  summary: {
    n_records: number; n_dated: number; n_undated: number; n_geo: number;
    n_days: number; n_trips: number; year_min: number | null; year_max: number | null;
  };
  years: { year: number; count: number; mapped: number }[];
  trips: Trip[];
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
  bio_group: [], kingdom_c: [], county: [], taxon_rank: [],
  basis_of_record: [], type_status: [], dataset_name: [], tbia_dataset_id: [],
  collector_id: [],
  missing_coordinates: false, missing_date: false,
  missing_identification: false, has_media: true,
});
