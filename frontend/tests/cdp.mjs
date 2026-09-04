/**
 * The browser-driving bits shared by the tests in this directory.
 *
 * Why no dependencies: Node's built-in WebSocket and fetch are enough to drive
 * Chrome over CDP, and the box this deploys to should not grow a browser
 * automation stack to run a handful of assertions.
 *
 * Env: WEB_URL (default http://localhost:5173), CDP_PORT, CHROME_BIN.
 */
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const WEB = (process.env.WEB_URL || "http://localhost:5173").replace(/\/+$/, "");
export const PORT = Number(process.env.CDP_PORT || 9333);
const CHROME = process.env.CHROME_BIN || "chromium";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- CDP client
export class Page {
  #ws; #id = 0; #pending = new Map();
  /** `new this()`, not `new Page()`, so a subclass's own methods survive open(). */
  static async open(url) {
    const tab = await (await fetch(`http://localhost:${PORT}/json/new?${encodeURIComponent(url)}`,
      { method: "PUT" })).json();
    const p = new this();
    p.tabId = tab.id;
    p.#ws = new WebSocket(tab.webSocketDebuggerUrl);
    p.#ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id && p.#pending.has(m.id)) { p.#pending.get(m.id)(m); p.#pending.delete(m.id); }
    };
    await new Promise((r) => (p.#ws.onopen = r));
    return p;
  }
  #send(method, params = {}) {
    return new Promise((res) => {
      const id = ++this.#id;
      this.#pending.set(id, res);
      this.#ws.send(JSON.stringify({ id, method, params }));
    });
  }
  /** Evaluate in the page and return the value (throws on a page-side error). */
  async eval(expression) {
    const r = await this.#send("Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true });
    const err = r.result?.exceptionDetails;
    if (err) throw new Error(`page error: ${err.exception?.description || err.text}`);
    return r.result?.result?.value;
  }
  /** Resize the viewport without relaunching — how one run covers many widths. */
  async viewport(width, height = 800) {
    await this.#send("Emulation.setDeviceMetricsOverride",
      { width, height, deviceScaleFactor: 1, mobile: false });
    await sleep(150);
  }
  async goto(path) {
    await this.eval(`location.href = ${JSON.stringify(WEB + path)}`);
    await this.settle();
  }
  /** Wait for the result count to stop changing — the queries are debounced. */
  async settle(ms = 900) { await sleep(ms); }
  url() { return this.eval("decodeURIComponent(location.pathname + location.search)"); }
  async close() {
    try { await fetch(`http://localhost:${PORT}/json/close/${this.tabId}`); } catch { /* going away */ }
    this.#ws.close();
  }
}

/** Headless Chrome on a throwaway profile; call the returned stop() when done. */
export async function launchChrome(extraArgs = []) {
  const profile = mkdtempSync(join(tmpdir(), "cdp-test-"));
  const chrome = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, ...extraArgs, "about:blank",
  ], { stdio: "ignore" });
  for (let i = 0; i < 40; i++) {
    if (await fetch(`http://localhost:${PORT}/json/version`).then((r) => r.ok).catch(() => false)) break;
    await sleep(250);
  }
  return () => { chrome.kill(); rmSync(profile, { recursive: true, force: true }); };
}

/** Refuse to run against nothing, with the two commands that fix it. */
export async function requireServer(name) {
  const res = await fetch(WEB).catch(() => null);
  if (res?.ok) return;
  console.error(`${name}: nothing serving ${WEB}. Start it first:\n` +
    `  make api    # :8000, the data\n  make web    # :5173, the app`);
  process.exit(1);
}

// ------------------------------------------------------------------ harness
let failures = 0;
const results = [];
export function check(name, ok, detail) {
  results.push({ name, ok, detail });
  if (!ok) failures++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? `  — ${detail}` : ""}`);
}
export async function test(name, fn) {
  console.log(`\n${name}`);
  try { await fn(); } catch (e) { check(name, false, e.message); }
}
export function report() {
  const total = results.length;
  console.log(`\n${total - failures}/${total} checks passed`);
  process.exit(failures ? 1 : 0);
}
