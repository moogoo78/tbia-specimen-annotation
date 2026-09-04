#!/usr/bin/env node
/**
 * The header's dropdown groups, tested by clicking the real page.
 *
 * Why a browser: `tsc` and `vite build` both stayed green through a bug that
 * broke every facet checkbox (see explore-url.mjs), and a menu is the same
 * shape of thing — open state, an outside-click listener and a route effect,
 * none of which a type checker can see. The width assertion is the other half:
 * the whole point of grouping ten tabs into five was to keep the header on one
 * 38px row, and nothing but a laid-out page can tell you whether it does.
 *
 *   node frontend/tests/nav-menu.mjs      # needs `make api` + `make web` running
 */
import {
  Page, WEB, check, launchChrome, report, requireServer, sleep, test,
} from "./cdp.mjs";

class HeaderPage extends Page {
  /** Height of the header row, in CSS pixels.
   *  offsetHeight, not getBoundingClientRect: `#root` carries `zoom: 1.15`, so
   *  the rect reports 44 for a 38px row and every threshold reads wrong. */
  height() { return this.eval(`document.querySelector("[data-app-header]").offsetHeight`); }
  /** How many menu panels are open right now. */
  openCount() { return this.eval(`document.querySelectorAll('[role="menu"]').length`); }
  /** Text of the links in the open panel. */
  items() {
    return this.eval(`[...document.querySelectorAll('[role="menu"] [role="menuitem"]')]
      .map((el) => el.innerText.trim())`);
  }
  /** Click a header control by its visible text. */
  async click(text) {
    await this.eval(`(() => {
      const hit = [...document.querySelectorAll("[data-app-header] button, [role='menu'] a, [role='menu'] button")]
        .find((el) => el.innerText.trim().includes(${JSON.stringify(text)}));
      if (!hit) throw new Error("nothing in the header matching " + ${JSON.stringify(text)});
      hit.click();
    })()`);
    await sleep(350);
  }
  /** Press Escape the way a keyboard does: on the document, where the handler is. */
  async escape() {
    await this.eval(`document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))`);
    await sleep(250);
  }
  /** A press in the page body, which should dismiss whatever is open. */
  async clickAway() {
    await this.eval(`document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))`);
    await sleep(250);
  }
  async setLang(lang) {
    await this.eval(`localStorage.setItem("tbia_lang", ${JSON.stringify(lang)})`);
    await this.goto("/browse");
    await sleep(600);
  }
}

async function main() {
  await requireServer("nav-menu");
  const stopChrome = await launchChrome();
  const page = await HeaderPage.open(`${WEB}/browse`);
  await sleep(2500); // first paint

  try {
    // The reason the grouping exists. 1024 is the narrow end we claim to hold;
    // the old ten-tab row wrapped below ~1270 in Chinese.
    await test("the header stays one row down to 1024", async () => {
      for (const lang of ["zh", "en"]) {
        await page.setLang(lang);
        for (const width of [1280, 1152, 1024]) {
          await page.viewport(width);
          const h = await page.height();
          check(`${lang} @ ${width}px is one row`, h <= 40, `${h}px`);
        }
      }
      await page.viewport(1280);
    });

    await test("a group opens, navigates, and closes behind you", async () => {
      await page.setLang("zh");
      await page.click("資料");
      const items = await page.items();
      check("資料 lists its four destinations", items.length === 4, items.join(" / "));
      await page.click("物種");
      await sleep(600);
      const url = await page.url();
      check("clicking 物種 lands on /species", url === "/species", url);
      check("the panel closed on navigation", (await page.openCount()) === 0);
    });

    await test("only one panel is open at a time", async () => {
      await page.goto("/browse");
      await sleep(600);
      await page.click("資料");
      check("資料 opened", (await page.openCount()) === 1);
      await page.click("參與");
      const open = await page.openCount();
      check("opening 參與 closed 資料", open === 1, `${open} panels open`);
    });

    await test("Escape and a click away both dismiss", async () => {
      await page.escape();
      check("Escape closed it", (await page.openCount()) === 0);
      await page.click("資料");
      await page.clickAway();
      check("a press outside closed it", (await page.openCount()) === 0);
    });

    // The group has to light up for its children the way the flat tabs did —
    // /history is a story topic, and it lit the story tab before this change.
    await test("a group is marked active for its children", async () => {
      const bold = async () => page.eval(
        `(() => {
          const b = [...document.querySelectorAll("[data-app-header] button")]
            .find((x) => x.innerText.trim().startsWith("資料"));
          return b ? getComputedStyle(b).fontWeight : "";
        })()`);
      await page.goto("/history");
      await sleep(700);
      check("/history marks 資料 active", (await bold()) === "600", await bold());
      await page.goto("/browse");
      await sleep(700);
      check("/browse does not", (await bold()) !== "600");
    });

    // The landing page drops the tabs entirely (pages/Landing.tsx); nothing in
    // the menu machinery may throw there.
    await test("the landing page still renders without tabs", async () => {
      await page.goto("/");
      await sleep(900);
      const triggers = await page.eval(
        `document.querySelectorAll("[data-app-header] [data-menu]").length`);
      check("no group triggers on /", triggers === 0, `${triggers} found`);
      const h = await page.height();
      check("header is still one row", h <= 40, `${h}px`);
    });
  } finally {
    await page.close();
    stopChrome();
  }
  report();
}

main().catch((e) => { console.error(e); process.exit(1); });
