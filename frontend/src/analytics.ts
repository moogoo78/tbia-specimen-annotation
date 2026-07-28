import { useEffect, useRef, useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";

// Google Analytics 4 (gtag.js), gated behind an explicit opt-in. The measurement
// ID is injected at *build* time by Vite, so it must be set in the build
// environment (see Dockerfile.prod / docker-compose.prod.yml). Unset -> every
// function here is a no-op and the consent banner never appears, which is what
// we want for local dev and tests.
const MEASUREMENT_ID = import.meta.env.VITE_GA_MEASUREMENT_ID as string | undefined;

export const ANALYTICS_ENABLED = Boolean(MEASUREMENT_ID);

declare global {
  interface Window {
    dataLayer?: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

export type Consent = "granted" | "denied" | "unset";

const STORAGE_KEY = "tbia_analytics_consent";

function read(): Consent {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "granted" || v === "denied" ? v : "unset";
  } catch {
    return "unset"; // private mode / blocked storage -> ask again, never assume yes
  }
}

let consent: Consent = read();
const listeners = new Set<() => void>();

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Record the visitor's choice. "denied" is persisted too, so we stop asking. */
export function setConsent(next: Exclude<Consent, "unset">) {
  consent = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* storage blocked — honour the choice for this session only */
  }
  listeners.forEach((fn) => fn());
}

/** Current choice, re-rendering the caller when it changes. */
export function useConsent(): Consent {
  return useSyncExternalStore(subscribe, () => consent, () => "unset" as Consent);
}

/**
 * Withdraw a previous choice: forget it, drop the cookies GA already set, and
 * put the banner back so the visitor can decide again.
 *
 * gtag.js itself can't be unloaded from a live page — but with consent back to
 * "unset" nothing further is sent, and a reload won't re-inject it unless the
 * visitor accepts again.
 */
export function revokeConsent() {
  clearGaCookies();
  consent = "unset";
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked — in-memory revoke still applies for this session */
  }
  listeners.forEach((fn) => fn());
}

/** Expire every `_ga*` cookie. GA scopes them to the registrable domain, which
 *  we can't read back from `document.cookie`, so expire each candidate domain
 *  (host-only, the host, and every parent) — the ones that don't match are
 *  simply ignored by the browser. */
function clearGaCookies() {
  const names = document.cookie
    .split("; ")
    .map((c) => c.split("=")[0])
    .filter((n) => n.startsWith("_ga"));
  if (!names.length) return;

  const host = location.hostname;
  const parts = host.split(".");
  const domains: (string | undefined)[] = [undefined, host, `.${host}`];
  for (let i = 1; i < parts.length - 1; i++) {
    const parent = parts.slice(i).join(".");
    domains.push(parent, `.${parent}`);
  }

  for (const name of names) {
    for (const domain of domains) {
      document.cookie =
        `${name}=; Max-Age=0; path=/` + (domain ? `; domain=${domain}` : "");
    }
  }
}

let loaded = false;

/** Inject gtag.js. Only ever called after consent is granted, so nothing is
 *  requested from Google — and no cookie is set — until the visitor opts in.
 *  Automatic pageviews are off: this is an SPA, so the initial hit and every
 *  route change are sent from `usePageviews` instead. */
function load() {
  if (loaded || !MEASUREMENT_ID) return;
  loaded = true;

  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
  document.head.appendChild(s);

  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    // gtag relies on `arguments` being pushed verbatim — don't spread it.
    // eslint-disable-next-line prefer-rest-params
    window.dataLayer!.push(arguments);
  };
  window.gtag("js", new Date());
  window.gtag("config", MEASUREMENT_ID, { send_page_view: false });
}

/** Send a pageview on mount and on every client-side route change. Accepting
 *  mid-session re-runs this, so the page the visitor consented on is counted. */
export function usePageviews() {
  const { pathname, search } = useLocation();
  const granted = useConsent() === "granted";
  const sent = useRef<string | null>(null);

  useEffect(() => {
    if (!MEASUREMENT_ID || !granted) return;
    load();

    const path = pathname + search;
    if (sent.current === path) return; // StrictMode double-invoke guard
    sent.current = path;

    window.gtag?.("event", "page_view", {
      page_path: path,
      page_location: window.location.href,
      page_title: document.title,
    });
  }, [pathname, search, granted]);
}

/** Optional custom events, e.g. trackEvent("annotation_saved", { field: "date" }). */
export function trackEvent(name: string, params: Record<string, unknown> = {}) {
  if (!MEASUREMENT_ID || consent !== "granted") return;
  window.gtag?.("event", name, params);
}
