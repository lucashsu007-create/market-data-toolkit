/* Run the shipped in-browser classifier under Node so Python can diff it.
 *
 * This does NOT re-implement anything. It lifts the `@mdt-live` block straight
 * out of index.html and evaluates it, which is the only way the parity test is
 * worth anything: if it ran a copy, the copy is what would be verified and the
 * shipped page would be free to drift.
 *
 * Usage: node parity_harness.js <index.html> <inputs.json>
 * Input:  [{"text": "...", "published": "2026-01-01" | null}, ...]
 * Output: [{"route": {...}, "impact": {...}, "decide": {...}, "pipeline": {...}}, ...]
 */

"use strict";

const fs = require("fs");
const vm = require("vm");

const START = "/* @mdt-live-start */";
const END = "/* @mdt-live-end */";

function extractLiveBlock(html) {
  const from = html.indexOf(START);
  const to = html.indexOf(END);
  if (from === -1 || to === -1 || to < from) {
    throw new Error("index.html has no @mdt-live block");
  }
  return html.slice(from + START.length, to);
}

function extractPayload(html) {
  const open = '<script id="site-data" type="application/json">';
  const from = html.indexOf(open);
  if (from === -1) throw new Error("index.html has no site-data payload");
  const start = from + open.length;
  const to = html.indexOf("</script>", start);
  if (to === -1) throw new Error("site-data block is not closed");
  return JSON.parse(html.slice(start, to));
}

function main() {
  const [htmlPath, inputsPath] = process.argv.slice(2);
  if (!htmlPath || !inputsPath) {
    throw new Error("usage: parity_harness.js <index.html> <inputs.json>");
  }
  const html = fs.readFileSync(htmlPath, "utf8");
  const source = extractLiveBlock(html);
  const payload = extractPayload(html);

  // A bare `window` and nothing else. If the live block ever reaches for
  // `document`, this throws — which is the purity guarantee being enforced
  // rather than merely documented.
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "index.html#mdt-live" });

  const live = sandbox.window.MDTLive.create(payload);
  const inputs = JSON.parse(fs.readFileSync(inputsPath, "utf8"));

  const results = inputs.map(function (item) {
    const text = item.text;
    const published = item.published === undefined ? null : item.published;
    const routed = live.route(text, published);
    return {
      route: routed,
      // Resolve the first feed the router found, or the explicit target the
      // fixture asked for — including ids that are not in the catalog.
      impact: live.resolveImpact(
        item.impact_target !== undefined
          ? item.impact_target
          : (routed.feeds.length ? routed.feeds[0] : null)
      ),
      decide: live.decide(routed, text),
      pipeline: live.pipeline(text, published)
    };
  });

  process.stdout.write(JSON.stringify(results));
}

main();
