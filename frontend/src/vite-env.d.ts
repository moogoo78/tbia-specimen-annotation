/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** GA4 measurement ID ("G-XXXXXXXXXX"); empty/undefined disables analytics. */
  readonly VITE_GA_MEASUREMENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
