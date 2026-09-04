#!/usr/bin/env node
/**
 * A contributor's work: the public page, the route in from the board, and the
 * annotation overlay on a record.
 *
 * Why a browser: the same reason as the other two files here. `tsc` and
 * `vite build` both stayed green through a bug that broke every facet
 * checkbox, and everything asserted below — that a board row is now a link,
 * that a profile's numbers equal the row's, that an annotation reaches the
 * record's own fields while a draft does not — is layout and data flow, which a
 * type checker cannot see.
 *
 * The assertions are relational (a row's count must equal the page it opens),
 * so an ETL refresh or a re-seed cannot invalidate them, and the whole file
 * skips cleanly when the board is empty — a fresh local database has no
 * annotations, and a test that fails for that reason teaches nothing.
 *
 *   node frontend/tests/contributions.mjs   # needs `make api` + `make web` running
 */
import {
  Page, check, launchChrome, report, requireServer, sleep, test,
} from "./cdp.mjs";

class ContribPage extends Page {
  /** The board's rows: [{ href, name, accepted, submitted, records }]. */
  boardRows() {
    return this.eval(`[...document.querySelectorAll('a[href^="/contributors/"]')]
      .map((a) => {
        const cells = [...a.children].map((c) => c.innerText.trim());
        return cells.length >= 5 ? {
          href: a.getAttribute("href"), name: cells[1],
          accepted: Number(cells[2].replace(/,/g, "")),
          submitted: Number(cells[3].replace(/,/g, "")),
          records: Number(cells[4].replace(/,/g, "")),
        } : null;
      }).filter(Boolean)`);
  }
  /** The profile's stat strip: each stat is a number over its label. */
  stats() {
    return this.eval(`[...document.querySelectorAll("div")]
      .filter((d) => d.children.length === 2 && /^[\\d,]+$/.test(d.children[0].innerText.trim()))
      .map((d) => Number(d.children[0].innerText.trim().replace(/,/g, "")))`);
  }
  /** The record groups on screen: the heading link, and the rows under it.
   *  A row is a plain div — only the heading is a link — so they are read as
   *  the heading's siblings rather than by selector. */
  groups() {
    return this.eval(`[...document.querySelectorAll('a[href^="/record/"]')].map((a) => ({
      href: a.getAttribute("href"),
      heading: a.innerText.replace(/\\n/g, " | "),
      rows: [...a.parentElement.children]
        .filter((el) => el !== a)
        .map((el) => el.innerText.replace(/\\n/g, " | ")),
    }))`);
  }
  text() { return this.eval("document.body.innerText"); }
  /** Sign in the way the dev-login panel does, or null when it is off (which
   *  it is by default, and always in a deployed environment). */
  async devLogin(email) {
    return this.eval(`(async () => {
      const cfg = await fetch("/api/auth/dev-login/config").then((r) => r.json()).catch(() => null);
      if (!cfg || !cfg.enabled) return null;
      const r = await fetch("/api/auth/dev-login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: ${JSON.stringify(email)} }),
      });
      if (!r.ok) return null;
      localStorage.setItem("tbia_token", (await r.json()).access_token);
      return "ok";
    })()`);
  }
  /** The status tiles, as [{ n, label }] — a number over a status pill. */
  tiles() {
    return this.eval(`[...document.querySelectorAll("div")]
      .filter((d) => d.children.length === 2 && /^[\\d,]+$/.test(d.children[0].innerText.trim()))
      .map((d) => ({ n: Number(d.children[0].innerText.trim().replace(/,/g, "")),
                     label: d.children[1].innerText.trim() }))`);
  }
  /** The list header's "listed / total", present only when the list is a page
   *  of something larger. */
  listedOfTotal() {
    return this.eval(`(() => {
      const m = document.body.innerText.match(/(\\d[\\d,]*) \\/ (\\d[\\d,]*)/);
      return m ? { listed: Number(m[1].replace(/,/g, "")), total: Number(m[2].replace(/,/g, "")) } : null;
    })()`);
  }
  /** Click the first thing whose visible text contains `s`. */
  async clickText(s) {
    await this.eval(`(() => {
      const el = [...document.querySelectorAll("a, button")]
        .find((x) => x.innerText.trim().includes(${JSON.stringify(s)}));
      if (!el) throw new Error("no element containing " + ${JSON.stringify(s)});
      el.click();
    })()`);
    await sleep(700);
  }
}

async function main() {
  await requireServer("contributions");
  const stopChrome = await launchChrome();
  const page = await ContribPage.open("about:blank");
  try {
    await page.goto("/contributors");
    const rows = await page.boardRows();
    if (rows.length === 0) {
      console.log("contributions: the board is empty — nothing has been annotated " +
        "in this database yet, so there is nothing to open. Skipping.");
      await page.close(); stopChrome(); return;
    }

    // The board used to be a table of numbers with nowhere to go.
    await test("a board row opens that contributor's work", async () => {
      const first = rows[0];
      check("the row is a link", /^\/contributors\/\d+$/.test(first.href), first.href);
      await page.clickText(first.name);
      check("it navigated", (await page.url()) === first.href, await page.url());

      // The relational assertion: the row's three numbers are the page's three
      // numbers. This is what the shared `count_columns` on the server buys.
      const stats = await page.stats();
      check("accepted matches the row", stats.includes(first.accepted),
        `row ${first.accepted}, page ${JSON.stringify(stats)}`);
      check("submitted matches the row", stats.includes(first.submitted),
        `row ${first.submitted}, page ${JSON.stringify(stats)}`);
      check("records matches the row", stats.includes(first.records),
        `row ${first.records}, page ${JSON.stringify(stats)}`);
    });

    // A contribution has to name the specimen it improved, and open it.
    await test("each contribution sits under its specimen", async () => {
      const groups = await page.groups();
      check("the list has record groups", groups.length > 0, `${groups.length} found`);
      // The specimen heads the group — a field name and a dataset do not tell
      // you which specimen you improved, which is what the flat list lacked.
      check("a group shows the edits under it",
        groups.some((g) => g.rows.some((r) => r.includes("→"))),
        JSON.stringify(groups[0]));
    });

    // The record is where the contribution has to become visible: until this
    // change a filled gap only showed as a row in the history, while the field
    // it filled still read "missing".
    await test("an annotation reaches the record's own fields", async () => {
      // Deliberately not "the first row": a draft is private working state and
      // a rejected value is one a reviewer refused, so neither is shown as the
      // specimen's value — a record carrying only those would rightly show no
      // overlay at all.
      const groups = await page.groups();
      const usable = groups.find((g) =>
        g.rows.some((r) => !/退回|rejected|草稿|draft/i.test(r)));
      const href = usable?.href || "";
      check("a record with a live contribution", !!href,
        groups.map((g) => g.heading).join(" ;; ").slice(0, 200));
      if (!href) return;
      await page.goto(href);
      await sleep(900);
      const body = await page.text();
      // `detail.wasValue` — zh "原值", en "was". Its presence is the overlay
      // rendering; without it the page shows only the provider's own value.
      check("the record shows what the value was", /原值|\bwas\b/.test(body),
        body.slice(0, 160).replace(/\n/g, " | "));
    });
    // /contributors is now the public half of what the dashboard was: the
    // platform's counts, the ranking, and everyone's recent work. None of it
    // needs a session — every row is already on its own record page — so this
    // is asserted signed out, which is how most visitors will see it.
    await test("the public page carries the platform's activity", async () => {
      await page.goto("/contributors");
      await sleep(1400);

      const groups = await page.groups();
      const feed = groups.filter((g) => /個欄位|field/.test(g.heading));
      check("recent contributions are grouped by specimen", feed.length > 0,
        `${feed.length} groups`);

      // A mixed feed names who did what; a single contributor's page does not.
      const named = await page.eval(
        `document.querySelectorAll('a[href^="/contributors/"]').length`);
      check("rows carry a contributor byline", named > 0, `${named} links`);

      // The heading is a group's only link — a row-level link would have to
      // nest inside it, which is invalid HTML.
      const nested = await page.eval(`document.querySelectorAll("a a").length`);
      check("no nested links", nested === 0, `${nested} found`);

      // Drafts are private working state and must never reach a public page.
      // Checked against the rows, not the page copy — the blurb names drafts
      // precisely in order to say they are somewhere else.
      const rows = feed.flatMap((g) => g.rows);
      check("no drafts in the public feed",
        rows.length > 0 && !rows.some((r) => /草稿|\bdraft\b/i.test(r)),
        rows.find((r) => /草稿|draft/i.test(r)) || `${rows.length} rows, none a draft`);
    });

    // The tiles are a claim about all of the work. On the dashboard they were
    // `items.filter(...)` over one fetched page, so past row 500 they
    // under-reported in silence — exactly where nobody would notice.
    await test("the status tiles count every row, not the page", async () => {
      const tiles = await page.tiles();
      check("the public page shows platform counts", tiles.length > 0,
        JSON.stringify(tiles));
      const sum = tiles.reduce((a, b) => a + b.n, 0);
      const page_ = await page.listedOfTotal();
      if (!page_) {
        check("everything fits one page — counts not yet discriminating", true,
          `tiles sum ${sum}`);
        return;
      }
      check("the list is a page of something larger", page_.total > page_.listed,
        `${page_.listed} / ${page_.total}`);
      check("tiles sum to the real total", sum === page_.total,
        `tiles ${sum}, total ${page_.total}, listed ${page_.listed}`);
    });

    // The personal half. /dashboard is only an old link now, and what is behind
    // it is one person's work plus their own settings — nobody else's.
    await test("the personal page is the other half, and /dashboard leads to it", async () => {
      await page.goto("/");
      const signedIn = await page.devLogin("curator@tbia.test");
      if (!signedIn) {
        check("dev login is off — skipping the personal page", true,
          "set NDB_DEV_LOGIN=true to cover it");
        return;
      }
      await page.goto("/dashboard");
      await sleep(1200);
      check("/dashboard redirects to /me", (await page.url()) === "/me", await page.url());

      const text = await page.text();
      // Drafts are here and only here: private working state, shown to its owner.
      check("the personal page is grouped too",
        (await page.groups()).length > 0);
      check("it carries the standing settings", /公開顯示我的姓名|Show my name publicly/.test(text),
        text.slice(0, 200).replace(/\n/g, " | "));
    });

  } finally {
    await page.close();
    stopChrome();
  }
  report();
}

main().catch((e) => { console.error(e); process.exit(1); });
