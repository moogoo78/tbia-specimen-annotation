/**
 * Bake per-route <head> metadata into the built SPA.
 *
 * Why this exists: the app is client-rendered, so every route served the same
 * <title> and no description. Google eventually renders the JS and would see a
 * title set from React — but social and chat unfurlers (Slack, LINE, Twitter,
 * Facebook) do not execute JavaScript at all, so a shared link can only unfurl
 * from tags that are already in the served HTML. This writes those files.
 *
 * It copies dist/index.html once per indexable route (src/seo/pages.json) with
 * the head filled in, keeping the same JS bundle — the SPA still takes over on
 * load, so behaviour is unchanged. Caddy's `try_files {path} {path}/index.html
 * /index.html` is what serves them; anything unlisted still falls through to the
 * SPA shell.
 *
 * Also emits sitemap.xml and appends robots.txt's absolute `Sitemap:` line.
 *
 * Absolute URLs (canonical, og:url, sitemap) need the deployed origin, which a
 * static build cannot know: set VITE_SITE_URL. Unset -> those tags are skipped
 * and no sitemap is written, because a canonical pointing at the wrong origin is
 * worse than none at all.
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { slugFor } from "./og-slug.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "..", "dist");
const { pages } = JSON.parse(readFileSync(resolve(here, "..", "src", "seo", "pages.json"), "utf8"));

const SITE = (process.env.VITE_SITE_URL || "").replace(/\/+$/, "");
const LANG = "zh"; // matches <html lang="zh-Hant">; the runtime hook follows the user's choice

const shellPath = join(dist, "index.html");
if (!existsSync(shellPath)) {
  console.error("prerender: dist/index.html missing — run `vite build` first");
  process.exit(1);
}
// Injected tags are fenced so a re-run replaces them instead of appending a
// second copy. `vite build` rewrites index.html first, so a full build never
// hits this — running this script on its own does.
const FENCE_OPEN = "<!-- seo:start -->";
const FENCE_CLOSE = "<!-- seo:end -->";
const shell = readFileSync(shellPath, "utf8").replace(
  new RegExp(`[ \\t]*${FENCE_OPEN}[\\s\\S]*?${FENCE_CLOSE}\\n?`),
  "",
);

/** Escape for use inside a double-quoted HTML attribute. */
const attr = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Escape for HTML text content (the <title> body). */
const text = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function headFor(page, { canonical }) {
  const title = page.title[LANG];
  const desc = page.description[LANG];
  const url = SITE ? SITE + (page.path === "/" ? "/" : page.path) : null;
  const type = page.path.startsWith("/story/") || page.path === "/history" ? "article" : "website";

  // The card lives at an absolute URL or not at all — every unfurler rejects a
  // relative og:image — so with no origin configured we fall back to the small
  // text-only card rather than advertising an image nobody can fetch.
  const image = SITE ? `${SITE}/og/${slugFor(page.path)}.png` : null;

  const tags = [
    `<meta name="description" content="${attr(desc)}" />`,
    `<meta property="og:type" content="${type}" />`,
    `<meta property="og:site_name" content="TBIA自然史標本探索與標註平台" />`,
    `<meta property="og:locale" content="zh_TW" />`,
    `<meta property="og:title" content="${attr(title)}" />`,
    `<meta property="og:description" content="${attr(desc)}" />`,
    `<meta name="twitter:card" content="${image ? "summary_large_image" : "summary"}" />`,
    `<meta name="twitter:title" content="${attr(title)}" />`,
    `<meta name="twitter:description" content="${attr(desc)}" />`,
  ];
  if (image) {
    tags.push(
      `<meta property="og:image" content="${attr(image)}" />`,
      `<meta property="og:image:width" content="1200" />`,
      `<meta property="og:image:height" content="630" />`,
      `<meta property="og:image:alt" content="${attr(title)}" />`,
      `<meta name="twitter:image" content="${attr(image)}" />`,
    );
  }
  // The root file is also the SPA fallback for every unlisted route (/record/:id,
  // /collectors/:id), so a canonical baked into it would claim those pages are
  // the home page. Emit it only on the per-route copies; useSeo.ts sets it
  // client-side for the rest, which is what Google's rendered pass reads.
  if (url) {
    tags.push(`<meta property="og:url" content="${attr(url)}" />`);
    if (canonical) tags.push(`<link rel="canonical" href="${attr(url)}" />`);
  }
  if (page.schema) {
    const ld = { "@context": "https://schema.org", ...page.schema };
    if (url) ld.url = url;
    tags.push(
      `<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, "\\u003c")}</script>`,
    );
  }
  return tags;
}

function render(page, opts) {
  let html = shell.replace(/<title>[\s\S]*?<\/title>/, `<title>${text(page.title[LANG])}</title>`);
  const block = [FENCE_OPEN, ...headFor(page, opts), FENCE_CLOSE].join("\n    ");
  return html.replace(/[ \t]*<\/head>/, `    ${block}\n  </head>`);
}

let written = 0;
for (const page of pages) {
  if (page.path === "/") {
    writeFileSync(shellPath, render(page, { canonical: false }));
  } else {
    const dir = join(dist, page.path);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "index.html"), render(page, { canonical: true }));
  }
  written++;
}

if (SITE) {
  const today = new Date().toISOString().slice(0, 10);
  const urls = pages
    .map(
      (p) =>
        `  <url>\n    <loc>${SITE}${p.path === "/" ? "/" : p.path}</loc>\n` +
        `    <lastmod>${today}</lastmod>\n  </url>`,
    )
    .join("\n");
  writeFileSync(
    join(dist, "sitemap.xml"),
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
      `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`,
  );
  // Rewritten from the public/ source, not appended to the built copy, so a
  // second run cannot stack a second Sitemap line.
  const robotsSrc = resolve(here, "..", "public", "robots.txt");
  if (existsSync(robotsSrc)) {
    const body = readFileSync(robotsSrc, "utf8").replace(/^Sitemap:.*$/gm, "").trimEnd();
    writeFileSync(join(dist, "robots.txt"), `${body}\n\nSitemap: ${SITE}/sitemap.xml\n`);
  }
  console.log(`prerender: ${written} pages + sitemap.xml (origin ${SITE})`);
} else {
  console.log(
    `prerender: ${written} pages; VITE_SITE_URL unset -> no canonical/og:url, no sitemap.xml`,
  );
}
