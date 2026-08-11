import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import pagesJson from "./pages.json";

/**
 * Set the document title (and description/canonical) for the current route.
 *
 * `scripts/prerender.mjs` bakes these same strings into the served HTML from the
 * same `pages.json`, which is what non-JS consumers — link unfurlers, and the
 * first pass of a crawler — read. This is the other half: it keeps the title
 * correct after client-side navigation, which is what Google's rendered pass
 * sees, and what `analytics.ts` reports as `page_title` (before this, every GA
 * pageview carried the one static title from index.html).
 *
 * Pages not listed in pages.json pass their own strings, so dynamic routes
 * (a collector, a record) can title themselves from loaded data.
 */

type Localized = { en: string; zh: string };
type Page = { path: string; title: Localized; description: Localized };

const PAGES: Page[] = (pagesJson as { pages: Page[] }).pages;

function upsertMeta(selector: string, create: () => HTMLMetaElement, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = create();
    document.head.appendChild(el);
  }
  el.content = content;
}

function setCanonical(href: string) {
  let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!el) {
    el = document.createElement("link");
    el.rel = "canonical";
    document.head.appendChild(el);
  }
  el.href = href;
}

const SITE = (import.meta.env.VITE_SITE_URL as string | undefined)?.replace(/\/+$/, "");
const SUFFIX = "TBIA自然史標本探索與標註平台";

/** Apply title/description for `path`, or for explicitly supplied strings. */
export function useSeo(override?: { title?: string; description?: string }) {
  const { i18n } = useTranslation();
  const lang = i18n.language?.startsWith("en") ? "en" : "zh";
  const { pathname: path } = useLocation();
  const page = PAGES.find((p) => p.path === path);

  const title = override?.title ?? page?.title[lang];
  const description = override?.description ?? page?.description[lang];

  useEffect(() => {
    if (title) document.title = path === "/" ? title : `${title} — ${SUFFIX}`;
    if (description) {
      upsertMeta(
        'meta[name="description"]',
        () => {
          const m = document.createElement("meta");
          m.name = "description";
          return m;
        },
        description,
      );
    }
    // The served HTML carries a canonical only on prerendered routes; on every
    // other path it would otherwise be missing or (from the SPA fallback file)
    // absent entirely. Set the real one here.
    if (SITE) setCanonical(SITE + path);
  }, [title, description, path]);
}
