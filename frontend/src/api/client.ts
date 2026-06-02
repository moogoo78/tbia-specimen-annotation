import type { Filters } from "./types";

const TOKEN_KEY = "tbia_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

  const res = await fetch(`/api${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* ignore */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function filtersToParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  for (const key of ["bio_group", "kingdom_c", "county", "taxon_rank",
    "basis_of_record", "type_status", "dataset_name", "tbia_dataset_id"] as const) {
    for (const v of f[key]) p.append(key, v);
  }
  for (const id of f.collector_id) p.append("collector_id", String(id));
  for (const key of ["missing_coordinates", "missing_date",
    "missing_identification", "has_media"] as const) {
    if (f[key]) p.set(key, "true");
  }
  if (f.year_from != null) p.set("year_from", String(f.year_from));
  if (f.year_to != null) p.set("year_to", String(f.year_to));
  if (f.record_number_from != null) p.set("record_number_from", String(f.record_number_from));
  if (f.record_number_to != null) p.set("record_number_to", String(f.record_number_to));
  if (f.bbox) p.set("bbox", f.bbox);
  return p;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: import("./types").User }>("/auth/login", {
      method: "POST", body: JSON.stringify({ email, password }),
    }),
  me: () => request<import("./types").User>("/auth/me"),

  search: (f: Filters, sort: string, order: string, limit: number, offset: number) => {
    const p = filtersToParams(f);
    p.set("sort", sort); p.set("order", order);
    p.set("limit", String(limit)); p.set("offset", String(offset));
    return request<import("./types").SearchResult>(`/occurrences?${p}`);
  },
  facets: (f: Filters) =>
    request<import("./types").FacetResult>(`/occurrences/facets?${filtersToParams(f)}`),
  detail: (id: string) => request<import("./types").OccurrenceDetail>(`/occurrences/${id}`),
  datasets: (limit = 200) => request<import("./types").Dataset[]>(`/datasets?limit=${limit}`),
  registry: () => request<import("./types").Registry>(`/registry`),

  collectors: (q = "", limit = 25) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (q) p.set("q", q);
    return request<import("./types").Collector[]>(`/collectors?${p}`);
  },
  resolveCollector: (recordedBy: string) =>
    request<import("./types").Collector | null>(
      `/collectors/resolve?recorded_by=${encodeURIComponent(recordedBy)}`),

  extract: (id: string) =>
    request<import("./types").ExtractResponse>(`/occurrences/${id}/extract`, { method: "POST" }),
  createAnnotation: (id: string, body: Record<string, unknown>) =>
    request<import("./types").Annotation>(`/occurrences/${id}/annotations`, {
      method: "POST", body: JSON.stringify(body),
    }),
  updateAnnotation: (annId: number, body: Record<string, unknown>) =>
    request<import("./types").Annotation>(`/annotations/${annId}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  listAnnotations: (params: Record<string, string>) =>
    request<{ total: number; items: import("./types").Annotation[] }>(
      `/annotations?${new URLSearchParams(params)}`),
  exportProvider: (datasetName: string) =>
    request<{ dataset_name: string; count: number; deltas: Record<string, unknown>[] }>(
      `/export/provider?dataset_name=${encodeURIComponent(datasetName)}&format=json`),
};
