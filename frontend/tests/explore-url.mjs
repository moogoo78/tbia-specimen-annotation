#!/usr/bin/env node
/**
 * Explore's URL, tested by clicking the real page.
 *
 * Why a browser: when the filter state moved into the query string, every
 * handler that called two setters wrote a URL that discarded the click — the
 * checkbox ticked and nothing else happened. `tsc` was clean, the build was
 * clean, and loading `/explore?bio_group=…` passed, because that only ever
 * exercised parsing. Nothing exercised a click, so a whole direction of the
 * feature — the one people use — was untested. This closes that.
 *
 * Why no dependencies: Node's built-in WebSocket and fetch are enough to drive
 * Chrome over CDP, and the box this deploys to should not grow a browser
 * automation stack to run a handful of assertions.
 *
 * Assertions are relational, never magic numbers: a facet row prints its own
 * count, so the test clicks it and requires the result total to equal *that*,
 * which stays true across an ETL refresh.
 *
 *   make test-web                      # needs `make api` + `make web` running
 *   WEB_URL=http://localhost:4173 node frontend/tests/explore-url.mjs
 */
import {
  Page, WEB, check, launchChrome, report, requireServer, sleep, test,
} from "./cdp.mjs";

// ------------------------------------------------------- Explore's own reads
/** The CDP plumbing lives in cdp.mjs; what is Explore-specific stays here. */
class ExplorePage extends Page {
  /** The pager's "1–100 ／ 12,345" total, as a number.
   *  Reads the pager span itself: scanning `body.innerText` for the same shape
   *  matched a facet row further up the page and reported its count instead. */
  async total() {
    const raw = await this.eval(`(() => {
      const re = /^\\d+[–-]\\d+\\s*\\S*\\s*([\\d,]+)$/;
      for (const el of document.querySelectorAll("span")) {
        const m = el.textContent.trim().match(re);
        if (m) return m[1];
      }
      return "";
    })()`);
    return raw ? Number(raw.replace(/,/g, "")) : null;
  }
  /** Click the sidebar row whose text contains `text`; returns the count it printed. */
  async clickFacet(text) {
    const n = await this.eval(`(() => {
      const row = [...document.querySelectorAll("label")].find((l) => l.innerText.includes(${JSON.stringify(text)}));
      if (!row) throw new Error("no facet row matching " + ${JSON.stringify(text)});
      const printed = (row.innerText.match(/([\\d,]+)\\s*$/) || [])[1] || "";
      row.click();
      return printed.replace(/,/g, "");
    })()`);
    await this.settle();
    return n ? Number(n) : null;
  }
  async clickButton(re) {
    await this.eval(`(() => {
      const b = [...document.querySelectorAll("button")].find((x) => ${re}.test(x.innerText));
      if (!b) throw new Error("no button matching " + ${re});
      b.click();
    })()`);
    await this.settle();
  }
  /** Next page: the button immediately after the disabled "previous". */
  async clickNextPage() {
    await this.eval(`(() => {
      const prev = [...document.querySelectorAll("button")]
        .find((b) => b.disabled && b.nextElementSibling?.tagName === "BUTTON");
      if (!prev) throw new Error("pager not found");
      prev.nextElementSibling.click();
    })()`);
    await this.settle();
  }
}

// --------------------------------------------------------------------- main
async function main() {
  await requireServer("explore-url");
  const stopChrome = await launchChrome();
  const page = await ExplorePage.open(`${WEB}/explore`);
  await sleep(2500); // first paint + the initial search
  try {
    // The landing default. `emptyFilters()` starts has_media true while the API
    // reads an absent boolean as false, so a bare URL must not be parsed
    // literally — this is the trap the whole scheme is built around.
    await test("bare /explore keeps the has_media default", async () => {
      const url = await page.url();
      const shown = await page.total();
      const api = await fetch(`${WEB}/api/occurrences?has_media=true&limit=1`)
        .then((r) => r.json()).then((d) => d.total);
      check("URL has no query", url === "/explore", url);
      check("total equals the API's has_media=true total", shown === api, `page ${shown} vs api ${api}`);
    });

    // The regression: two setters in one handler, the second discarding the first.
    await test("clicking a flag facet applies it", async () => {
      const printed = await page.clickFacet("缺少鑑定");
      const url = await page.url();
      const shown = await page.total();
      check("URL gains missing_identification", url.includes("missing_identification=true"), url);
      check("total becomes the count the row printed", shown === printed, `page ${shown} vs row ${printed}`);
    });

    await test("a second facet accumulates rather than replacing", async () => {
      const printed = await page.clickFacet("被子植物");
      const url = await page.url();
      const shown = await page.total();
      check("both params present",
        url.includes("bio_group=") && url.includes("missing_identification=true"), url);
      check("total becomes the count the row printed", shown === printed, `page ${shown} vs row ${printed}`);
    });

    await test("unchecking removes only that filter", async () => {
      await page.clickFacet("缺少鑑定");
      const url = await page.url();
      check("missing_identification gone", !url.includes("missing_identification"), url);
      check("bio_group kept", url.includes("bio_group="), url);
    });

    await test("paging writes offset, and a filter edit resets it", async () => {
      await page.clickNextPage();
      let url = await page.url();
      check("offset in the URL", url.includes("offset=100"), url);
      await page.clickFacet("缺少座標");
      url = await page.url();
      check("offset dropped by the filter edit", !url.includes("offset="), url);
    });

    await test("clear returns to the landing state", async () => {
      await page.clickButton("/清除|Clear/");
      const url = await page.url();
      const shown = await page.total();
      const api = await fetch(`${WEB}/api/occurrences?has_media=true&limit=1`)
        .then((r) => r.json()).then((d) => d.total);
      check("only has_media left", /^\/explore\?has_media=true$/.test(url), url);
      check("total back to the default", shown === api, `page ${shown} vs api ${api}`);
    });

    // The other direction: a link in, parsed from the URL alone.
    await test("an inbound link's filters are read from the URL", async () => {
      await page.goto("/explore?scientific_name=Trema%20orientalis");
      await sleep(700);
      const shown = await page.total();
      const api = await fetch(`${WEB}/api/occurrences?scientific_name=Trema%20orientalis&limit=1`)
        .then((r) => r.json()).then((d) => d.total);
      check("total matches the API for that name", shown === api, `page ${shown} vs api ${api}`);
    });

    await test("a collector id resolves to a name", async () => {
      const c = await fetch(`${WEB}/api/collectors?limit=1`).then((r) => r.json());
      await page.goto(`/explore?collector_id=${c[0].id}`);
      await sleep(900);
      const named = await page.eval(
        `document.body.innerText.includes(${JSON.stringify(c[0].label)})`);
      check("chip shows the resolved label, not the bare id", named === true, c[0].label);
    });
  } finally {
    await page.close();
    stopChrome();
  }
  report();
}

main().catch((e) => { console.error(e); process.exit(1); });
