#!/usr/bin/env node
/**
 * The per-institution annotation report: the route in from /institutions, the
 * summary's numbers against the list beneath it, a status tile filtering that
 * list, and the review pane — the specimen image beside each old → new value.
 *
 * Relational, like the other files here: a tile's count must equal what the
 * list holds after clicking it, and a record's diff rows must equal its own
 * published (non-draft) history, so a re-seed cannot invalidate it. Skips
 * cleanly when no institution has an annotation yet.
 *
 * The reviewer step **changes data** (it accepts one submitted annotation), so
 * it runs only with REPORT_REVIEW=1 — point it at a throwaway annotations
 * store, never the one you back up.
 *
 *   node frontend/tests/institution-report.mjs   # needs `make api` + `make web`
 */
import {
  Page, check, launchChrome, report, requireServer, sleep, test,
} from "./cdp.mjs";

class ReportPage extends Page {
  reportLinks() {
    return this.eval(`[...document.querySelectorAll('a[href$="/report"]')].map((a) => a.getAttribute("href"))`);
  }
  tiles() {
    return this.eval(`Object.fromEntries([...document.querySelectorAll("[data-tile]")].map((b) =>
      [b.getAttribute("data-tile"), Number(b.children[1].innerText.replace(/,/g, ""))]))`);
  }
  records() {
    return this.eval(`[...document.querySelectorAll("[data-record]")].map((r) => ({
      id: r.getAttribute("data-record"), text: r.innerText }))`);
  }
  diffs() {
    return this.eval(`[...document.querySelectorAll("[data-diff]")].map((d) => ({
      id: Number(d.getAttribute("data-diff")), status: d.getAttribute("data-status") }))`);
  }
  clickTile(label) {
    return this.eval(`document.querySelector('[data-tile=${JSON.stringify(label)}]').click()`);
  }
  /** The pane's large image: present and actually decoded. */
  paneImage() {
    return this.eval(`(() => {
      const img = [...document.querySelectorAll("a[target=_blank] > img")].find((i) => i.style.objectFit === "contain");
      return img ? { src: img.src, loaded: img.complete && img.naturalWidth > 0 } : null;
    })()`);
  }
  param(k) { return this.eval(`new URLSearchParams(location.search).get(${JSON.stringify(k)})`); }
  api(path) { return this.eval(`fetch(${JSON.stringify(path)}).then((r) => r.json())`); }
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
}

async function main() {
  await requireServer("institution-report");
  const stopChrome = await launchChrome();
  const page = await ReportPage.open("about:blank");
  try {
    await page.goto("/institutions");
    await sleep(1500);
    const links = await page.reportLinks();
    if (links.length === 0) {
      check("no institution has annotations yet — skipping", true);
      return;
    }
    const href = links[0];
    const key = decodeURIComponent(href.split("/")[2]);
    const summary = await page.api(`/api/reports/institutions/${encodeURIComponent(key)}`);

    await test("an institution card links to its report", async () => {
      await page.goto(href);
      await sleep(1500);
      check("the report opened", (await page.url()).startsWith(`/institutions/${key}/report`), await page.url());
      const tiles = await page.tiles();
      const all = Object.values(tiles)[0];
      check("the All tile is the summary's total", all === summary.by_status.total,
        `${all} vs ${summary.by_status.total}`);
      const recs = await page.records();
      check("the list holds every annotated record",
        recs.length === Math.min(50, summary.n_records), `${recs.length} vs ${summary.n_records}`);
      check("the first record is selected on arrival", (await page.param("r")) === recs[0]?.id);
    });

    await test("a status tile filters the list to that status", async () => {
      const label = Object.keys(await page.tiles()).find((l) => /已送出|Submitted/.test(l));
      if (!summary.by_status.submitted || !label) { check("nothing submitted — skipped", true); return; }
      await page.clickTile(label);
      await sleep(1200);
      check("the filter is in the URL", (await page.param("status")) === "submitted");
      const recs = await page.records();
      const withSubmitted = summary.n_records_pending;
      check("only records with a submitted row are listed",
        recs.length === Math.min(50, withSubmitted), `${recs.length} vs ${withSubmitted}`);
      await page.clickTile(label); // toggles back off
      await sleep(1200);
      check("clicking it again clears it", (await page.param("status")) === null);
    });

    await test("the pane shows the specimen beside its published values", async () => {
      const id = await page.param("r");
      const detail = await page.api(`/api/occurrences/${encodeURIComponent(id)}`);
      const published = detail.annotations.filter((a) => a.status !== "draft");
      const diffs = await page.diffs();
      check("one diff row per published annotation", diffs.length === published.length,
        `${diffs.length} vs ${published.length}`);
      check("no draft is shown", !diffs.some((d) => d.status === "draft"));
      if (detail.media.length) {
        await sleep(2500);
        const img = await page.paneImage();
        check("the specimen image is beside them", !!img, JSON.stringify(img));
      }
    });

    await test("j / k move between records", async () => {
      const recs = await page.records();
      if (recs.length < 2) { check("one record — skipped", true); return; }
      const before = await page.param("r");
      await page.eval(`window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }))`);
      await sleep(600);
      const after = await page.param("r");
      check("j selects the next record", after !== before && after === recs[1].id, `${before} → ${after}`);
      await page.eval(`window.dispatchEvent(new KeyboardEvent("keydown", { key: "k" }))`);
      await sleep(600);
      check("k goes back", (await page.param("r")) === before);
    });

    await test("a reviewer can accept a row in place", async () => {
      if (process.env.REPORT_REVIEW !== "1") {
        check("changes data — set REPORT_REVIEW=1 against a throwaway store to run", true);
        return;
      }
      if (!(await page.devLogin("reviewer@tbia.test"))) { check("dev login is off — skipped", true); return; }
      await page.goto(`${href}?status=submitted`);
      await sleep(2000);
      const target = (await page.diffs()).find((d) => d.status === "submitted");
      if (!target) { check("nothing submitted — skipped", true); return; }
      const before = (await page.api(`/api/reports/institutions/${encodeURIComponent(key)}`)).by_status.accepted;
      await page.eval(`[...document.querySelector('[data-diff="${target.id}"]').querySelectorAll("button")]
        .find((b) => /採納|Accept/.test(b.innerText)).click()`);
      await sleep(2000);
      const row = (await page.diffs()).find((d) => d.id === target.id);
      check("the row now reads accepted", row?.status === "accepted", JSON.stringify(row));
      const tile = Object.entries(await page.tiles()).find(([l]) => /已採納|Accepted/.test(l))?.[1];
      check("the summary moved with it", tile === before + 1, `${before} → ${tile}`);
    });

    await test("the record page still renders its gallery", async () => {
      const recs = await page.records();
      const withMedia = recs.find(() => true);
      if (!withMedia) return;
      await page.goto(`/record/${withMedia.id}`);
      await sleep(2000);
      const n = await page.eval(`document.querySelectorAll('img[loading="lazy"]').length`);
      const detail = await page.api(`/api/occurrences/${encodeURIComponent(withMedia.id)}`);
      check("thumbnails render", n >= Math.min(6, detail.media.length), `${n} imgs, ${detail.media.length} media`);
    });
  } finally {
    await page.close();
    stopChrome();
  }
  report();
}

main().catch((e) => { console.error(e); process.exit(1); });
