/* Drive the shipped renderers over hostile text and hand the HTML to Python.
 *
 * Unlike parity_harness.js, the app shell is not pure — it is a renderer, so it
 * needs a document to boot. The stub below is the smallest one that gets the
 * IIFE to the point where `window.__MDT_TEST__` exists. It deliberately does
 * NOT parse HTML: the tests assert on the strings the renderers produce, which
 * is what would be assigned to innerHTML on the real page.
 *
 * Usage: node xss_harness.js <index.html> <inputs.json>
 */

"use strict";

const fs = require("fs");
const vm = require("vm");

function extractPayload(html) {
  const open = '<script id="site-data" type="application/json">';
  const from = html.indexOf(open);
  const start = from + open.length;
  const to = html.indexOf("</script>", start);
  return { text: html.slice(start, to), json: JSON.parse(html.slice(start, to)) };
}

function extractAppScript(html) {
  // The last <script> block: MDIGGraph + MDTLive + the app shell.
  const marker = '<script>/* MDIGGraph';
  const from = html.indexOf(marker);
  if (from === -1) throw new Error("could not find the app script block");
  const start = html.indexOf(">", from) + 1;
  const to = html.lastIndexOf("</script>");
  return html.slice(start, to);
}

function makeElement() {
  const el = {
    innerHTML: "", textContent: "", hidden: false, disabled: false,
    clientWidth: 0, style: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { el.children.push(c); return c; },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    getBoundingClientRect() { return { width: 0, height: 0, top: 0, left: 0 }; }
  };
  return el;
}

function main() {
  const [htmlPath, inputsPath] = process.argv.slice(2);
  const html = fs.readFileSync(htmlPath, "utf8");
  const payload = extractPayload(html);

  const siteData = makeElement();
  siteData.textContent = payload.text;
  const byId = { "site-data": siteData, "mdig-view": makeElement(), "mdig-nav": makeElement() };

  const sandbox = {
    window: {},
    document: {
      getElementById(id) { return byId[id] || makeElement(); },
      createElement() { return makeElement(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {}
    },
    location: { hash: "" },
    d3: {},
    console: console
  };
  sandbox.window.addEventListener = function () {};
  sandbox.window.matchMedia = function () { return { matches: false }; };
  sandbox.window.document = sandbox.document;
  sandbox.window.location = sandbox.location;
  vm.createContext(sandbox);
  vm.runInContext(extractAppScript(html), sandbox, { filename: "index.html#app" });

  const T = sandbox.window.__MDT_TEST__;
  if (!T) throw new Error("window.__MDT_TEST__ was never assigned");
  const live = sandbox.window.MDTLive.create(payload.json);

  const inputs = JSON.parse(fs.readFileSync(inputsPath, "utf8"));
  const results = inputs.map(function (item) {
    // Drive the page's own state machine, so stage 1 renders the given text
    // rather than the shipped notice it was seeded with. `original: true` puts
    // it back, which is how the graded/ungraded switch gets exercised.
    T.setLiveText(item.original ? null : item.text);
    const scn = T.activeScenario();
    const text = item.original ? scn.router_input : item.text;
    return {
      name: item.name,
      esc: T.esc(text),
      kv: T.kv("label", text),
      // The patterns a live classification actually reports, plus a hostile one
      // to prove an uncompilable pattern cannot smuggle markup through.
      highlight: T.highlight(text, (scn.router_output.evidence.type || []).concat(["("])),
      stageRaw: T.stageRaw(scn),
      stageRouter: T.stageRouter(scn),
      stageImpact: T.stageImpact(scn),
      stageDecision: T.stageDecision(scn),
      // The one deliberate raw-HTML sink. Collected so it cannot be pointed at
      // untrusted input without this suite noticing.
      kvHTML: T.kvHTML("label", T.esc(text))
    };
  });

  process.stdout.write(JSON.stringify(results));
}

main();
