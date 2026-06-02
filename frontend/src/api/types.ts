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
  std_lat: number | null;
  std_lon: number | null;
  std_date: string | null;
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
  fields: ExtractedField[];
}

export interface User { id: number; email: string; display_name: string; role: string; }

export interface Collector {
  id: number;
  name: string;       // 中文 (may be "")
  name_en: string;    // romanized (may be "")
  label: string;      // "name name_en" for display
  n_records: number;
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
  missing_coordinates: boolean;
  missing_date: boolean;
  missing_identification: boolean;
  has_media: boolean;
  year_from?: number;
  year_to?: number;
  bbox?: string;
}

export const emptyFilters = (): Filters => ({
  bio_group: [], kingdom_c: [], county: [], taxon_rank: [],
  basis_of_record: [], type_status: [], dataset_name: [], tbia_dataset_id: [],
  collector_id: [],
  missing_coordinates: false, missing_date: false,
  missing_identification: false, has_media: false,
});
