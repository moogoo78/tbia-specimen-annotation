// The terms a contributor may release an annotation under.
//
// The same three the backend accepts (`models.LICENSES`), by the same SPDX ids,
// because the id is what crosses the wire and lands in the provider export — a
// display string like "CC BY" would name four incompatible licences. Labels are
// proper nouns and stay untranslated in both UI languages; only the field's own
// label is an i18n key.
export const LICENSES = ["CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0"] as const;
export type License = (typeof LICENSES)[number];

// Matches the backend default (and iNaturalist's): the narrowest of the three,
// so a contributor who never opens the picker grants the least rather than the
// most. Only the fallback for a user whose own default has not loaded — the
// value that actually seeds the form is `user.default_license`.
export const DEFAULT_LICENSE: License = "CC-BY-NC-4.0";

export const LICENSE_LABELS: Record<License, string> = {
  "CC0-1.0": "CC0 1.0",
  "CC-BY-4.0": "CC BY 4.0",
  "CC-BY-NC-4.0": "CC BY-NC 4.0",
};

export const LICENSE_URIS: Record<License, string> = {
  "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
  "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
};

export function licenseLabel(id: string): string {
  return LICENSE_LABELS[id as License] ?? id;
}

/** Narrow a value from the API to a License, falling back to the platform default. */
export function asLicense(id: string | null | undefined): License {
  return (LICENSES as readonly string[]).includes(id ?? "") ? (id as License) : DEFAULT_LICENSE;
}
