#!/usr/bin/env node
/**
 * The record page's Identification panel, driven in the real page: open the
 * form, fill the DwC terms, submit it (there are no drafts), and have a reviewer accept
 * it — checking at each step what the public record and /me show.
 *
 * It **changes data** (it creates identifications), so it runs only with
 * IDENT_WRITE=1. Point it at a throwaway annotations store, never the one you
 * back up. Every row it writes carries MARKER in its remarks.
 *
 *   IDENT_WRITE=1 node frontend/tests/identification.mjs   # needs `make api` + `make web`
 */
import {
  Page, WEB, check, launchChrome, report, requireServer, sleep, test,
} from "./cdp.mjs";

export const MARKER = "cdp-identification-test";

// The identification panel on a record, or the whole page where there is none (/me).
const ROOT = `(document.querySelector("[data-ident-panel]") || document)`;

class RecordPage extends Page {
  text() { return this.eval("document.body.textContent"); }
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
  /** Click a button by its visible text (first match). */
  async button(text) {
    await this.eval(`(() => {
      const b = [...${ROOT}.querySelectorAll("button")].find((el) => el.innerText.trim() === ${JSON.stringify(text)});
      if (!b) throw new Error("no button " + ${JSON.stringify(text)});
      b.click();
    })()`);
    await sleep(500);
  }
  /** Set the control under a form row labelled with this DwC term, the way
   *  typing does: React only sees a value through its own setter + an event. */
  async fill(term, value, nth = 0) {
    await this.eval(`(() => {
      const label = [...${ROOT}.querySelectorAll("span")].find((s) => s.innerText.trim() === ${JSON.stringify(term)});
      if (!label) throw new Error("no row " + ${JSON.stringify(term)});
      const ctl = label.parentElement.parentElement.querySelectorAll("input, select, textarea")[${nth}];
      const proto = Object.getPrototypeOf(ctl);
      Object.getOwnPropertyDescriptor(proto, "value").set.call(ctl, ${JSON.stringify(value)});
      ctl.dispatchEvent(new Event(ctl.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    })()`);
  }
  value(term, nth = 0) {
    return this.eval(`(() => {
      const label = [...${ROOT}.querySelectorAll("span")].find((s) => s.innerText.trim() === ${JSON.stringify(term)});
      return label?.parentElement.parentElement.querySelectorAll("input, select, textarea")[${nth}]?.value;
    })()`);
  }
}

async function main() {
  await requireServer("identification");
  if (process.env.IDENT_WRITE !== "1") {
    console.log("identification: changes data — set IDENT_WRITE=1 against a throwaway store to run");
    process.exit(0);
  }
  const stopChrome = await launchChrome();
  const page = await RecordPage.open(`${WEB}/browse`);
  await sleep(1500);
  await page.eval(`localStorage.setItem("tbia_lang", "en")`);
  let occ;
  try {
    await test("a contributor submits an identification", async () => {
      if (!(await page.devLogin("curator@tbia.test"))) { check("dev login is off — skipped", true); return; }
      const res = await page.api("/api/occurrences?limit=1&missing_identification=true");
      occ = res.items[0].id;
      await page.goto(`/record/${occ}`);
      await sleep(1500);
      await page.eval(`document.querySelector('[data-work-tab="ident"]').click()`);
      await sleep(400);
      check("panel is on the record", (await page.text()).includes("Identifications"));
      check("identifiedBy prefilled from the signed-in user", (await page.value("identifiedBy")) === "Ada Curator");
      await page.fill("scientificName", "Meteorium buchananii");
      await page.fill("identificationQualifier", "cf.");
      await page.fill("dateIdentified", "2026", 0);
      await page.fill("dateIdentified", "11", 1);
      await page.fill("dateIdentified", "", 2);
      await page.fill("identificationReferences", "Moss Flora of Taiwan");
      await page.fill("identificationRemarks", MARKER);
      // Hand-typed name: a source is required before it can be submitted.
      await page.fill("nameAccordingTo", "Moss Flora of Taiwan (2011)");
      check("no draft button", !(await page.eval(`[...${ROOT}.querySelectorAll("button")].some((b) => b.textContent.trim() === "Save draft")`)));
      await page.button("Submit identification");
      await sleep(1000);
      check("submit receipt shown", (await page.text()).includes("Identification submitted"));
      const pub = await fetch(`${WEB}/api/occurrences/${occ}`).then((r) => r.json());
      const row = pub.identifications.find((i) => i.identification_remarks === MARKER);
      check("submitted row is public", row?.status === "submitted", row?.status);
      check("date stored as partial ISO", row?.date_identified === "2026-11", row?.date_identified);
    });

    await test("a reviewer accepts it on the record", async () => {
      if (!occ) return;
      await page.devLogin("reviewer@tbia.test");
      await page.goto(`/record/${occ}`);
      await sleep(1500);
      await page.eval(`document.querySelector('[data-work-tab="ident"]').click()`);
      await sleep(400);
      check("card reads as a det. slip", (await page.text()).includes("det. Ada Curator, 2026-11"));
      // A reviewer without the identifier flag reviews but cannot add one.
      check("no form without the identifier flag",
        await page.eval(`!!document.querySelector("[data-ident-locked]") && !document.querySelector("[data-ident-panel] [role=combobox]")`));
      await page.eval(`(() => {
        const card = [...${ROOT}.querySelectorAll("div")].reverse()
          .find((d) => d.textContent.includes("Meteorium cf. buchananii") && d.textContent.includes("Accept"));
        [...card.querySelectorAll("button")].find((b) => b.innerText.trim() === "Accept").click();
      })()`);
      await sleep(1200);
      const pub = await fetch(`${WEB}/api/occurrences/${occ}`).then((r) => r.json());
      const row = pub.identifications.find((i) => i.identification_remarks === MARKER);
      check("accepted", row?.status === "accepted", row?.status);
    });
    await test("an admin manages identifiers on /admin/users", async () => {
      await page.devLogin("admin@tbia.test");
      await page.goto("/me");
      await sleep(1200);
      check("/me links to the users page", await page.eval(`!!document.querySelector('[data-identifier-admin][href="/admin/users"]')`));
      await page.goto("/admin/users");
      await sleep(1500);
      const rowOf = (name) => `[...document.querySelectorAll("[data-user-row]")].find((r) => r.textContent.includes(${JSON.stringify(name)}))`;
      check("curator ticked", await page.eval(`${rowOf("Ada Curator")}?.querySelector("[data-identifier-toggle]").checked`) === true);
      const counts = await page.eval(`${rowOf("Ada Curator")}?.children[4].textContent`);
      check("curator's identification counted", /\b[1-9]/.test(counts || ""), counts);
      // Grant to the reviewer, see the record page open the form, then take it back.
      await page.eval(`${rowOf("Rex Reviewer")}.querySelector("[data-identifier-toggle]").click()`);
      await sleep(800);
      check("reviewer granted", await page.eval(`${rowOf("Rex Reviewer")}.querySelector("[data-identifier-toggle]").checked`) === true);
      await page.eval(`${rowOf("Ada Curator")}.click()`);
      await sleep(1000);
      const detail = await page.eval(`document.querySelector("[data-user-detail]")?.textContent || ""`);
      check("detail opens with the user's facts", detail.includes("Ada Curator") && detail.includes("Recent identifications"));
      check("selection is in the URL", (await page.eval("location.search")).includes("u="));
      await page.eval(`${rowOf("Rex Reviewer")}.querySelector("[data-identifier-toggle]").click()`);
      await sleep(800);
      check("reviewer withdrawn", await page.eval(`${rowOf("Rex Reviewer")}.querySelector("[data-identifier-toggle]").checked`) === false);
    });
    await page.screenshot(process.env.IDENT_SHOT || "/dev/null");
  } finally {
    await page.close();
    stopChrome();
  }
  report();
}

main();
