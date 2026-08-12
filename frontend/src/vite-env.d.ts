/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** GA4 measurement ID ("G-XXXXXXXXXX"); empty/undefined disables analytics. */
  readonly VITE_GA_MEASUREMENT_ID?: string;
  /** Deployed origin ("https://example.org"); used for canonical + og:url.
   *  Unset -> those tags are skipped rather than pointing at a wrong origin. */
  readonly VITE_SITE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
