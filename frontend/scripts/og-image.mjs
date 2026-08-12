/**
 * Render the Open Graph card for every page in src/seo/pages.json.
 *
 * A dev-time tool, not part of `npm run build`: it drives headless Chromium,
 * which the production image does not have (and should not grow). Run it when a
 * title or description in pages.json changes, and commit the PNGs it writes to
 * public/og/ — the build just copies them.
 *
 *   node scripts/og-image.mjs          # all pages
 *   node scripts/og-image.mjs /history # one page
 *
 * Cards are rendered at exactly 1200x630 — the size every unfurler wants, and the
 * one prerender.mjs declares in og:image:width/height, so the file and the
 * declaration cannot disagree. Unfurlers display the card at 1200px at most, so
 * rendering larger only costs bytes.
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { slugFor } from "./og-slug.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const { pages } = JSON.parse(readFileSync(resolve(here, "..", "src", "seo", "pages.json"), "utf8"));
const outDir = resolve(here, "..", "public", "og");

const CHROME =
  process.env.CHROME_BIN ||
  ["chromium", "chromium-browser", "google-chrome"].find((c) => {
    try {
      execFileSync(c, ["--version"], { stdio: "pipe" });
      return true;
    } catch {
      return false;
    }
  });
if (!CHROME) {
  console.error("og-image: no chromium found — set CHROME_BIN");
  process.exit(1);
}

const esc = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Design tokens, kept in step with src/design/tokens.ts by hand — the card is a
// static asset rendered outside the app, so it cannot import them.
const T = { bg: "#f6f5f2", fg: "#1c1b18", muted: "#5c5a54", subtle: "#8a877f", border: "#d9d5cc" };

function cardHtml(page) {
  // `card.title` exists for headlines that do not set well at card size — the
  // home page's full name wraps to a second line for one character.
  const title = page.card?.title ?? page.title.zh;
  // Two lines of description is all that stays legible at card size.
  const desc = page.description.zh;
  const isHome = page.path === "/";
  return `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    width: 1200px; height: 630px; background: ${T.bg}; color: ${T.fg};
    font-family: "PingFang TC", "Noto Sans CJK TC", "Droid Sans Fallback", Helvetica, Arial, sans-serif;
    display: flex; flex-direction: column; justify-content: space-between;
    padding: 72px 80px; border-top: 12px solid ${T.fg};
  }
  .eyebrow { font-size: 26px; letter-spacing: .18em; color: ${T.subtle}; }
  h1 { font-size: ${isHome ? 74 : 84}px; line-height: 1.18; font-weight: 700; letter-spacing: -.01em; }
  p { font-size: 30px; line-height: 1.62; color: ${T.muted}; max-width: 980px;
      display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  footer { display: flex; align-items: center; gap: 18px; font-size: 25px; color: ${T.subtle};
           border-top: 2px solid ${T.border}; padding-top: 26px; }
  .dot { width: 11px; height: 11px; border-radius: 50%; background: ${T.fg}; opacity: .6; }
  </style></head><body>
    <div>
      <div class="eyebrow">TBIA 自然史標本</div>
      <h1 style="margin-top:22px">${esc(title)}</h1>
    </div>
    <p>${esc(desc)}</p>
    <footer><span class="dot"></span><span>探索與標註平台</span></footer>
  </body></html>`;
}

const only = process.argv[2];
const targets = only ? pages.filter((p) => p.path === only) : pages;
if (!targets.length) {
  console.error(`og-image: no page matches ${only}`);
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });
const tmp = join(tmpdir(), `og-card-${process.pid}.html`);

for (const page of targets) {
  writeFileSync(tmp, cardHtml(page));
  const out = join(outDir, `${slugFor(page.path)}.png`);
  execFileSync(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--hide-scrollbars",
      "--window-size=1200,630",
      `--screenshot=${out}`,
      `file://${tmp}`,
    ],
    { stdio: "pipe" },
  );
  console.log(`og-image: ${slugFor(page.path)}.png  ${(statSync(out).size / 1024).toFixed(0)} kB`);
}
rmSync(tmp, { force: true });
