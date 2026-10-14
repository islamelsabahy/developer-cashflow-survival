"use strict";
const assert = require("assert");
const S = require("../docs/survival.js");
const V = require("./vectors.json");

function close(a, b, path) {
  if (typeof a === "number" && typeof b === "number") {
    assert.ok(Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b)), `${path}: ${a} vs ${b}`);
  } else if (Array.isArray(a)) {
    assert.ok(Array.isArray(b) && a.length === b.length, `${path}: length`);
    a.forEach((x, i) => close(x, b[i], `${path}[${i}]`));
  } else if (a && typeof a === "object") {
    assert.deepStrictEqual(Object.keys(a).sort(), Object.keys(b).sort(), `${path}: keys`);
    Object.keys(a).forEach(k => close(a[k], b[k], `${path}.${k}`));
  } else assert.strictEqual(a, b, path);
}

let n = 0;
const rng = S.makeRng(12345);
close(V.rng.map(() => rng()), V.rng, "rng"); n++;
const r2 = S.makeRng(99);
close(V.z.map(() => S.zScore(r2)), V.z, "z"); n++;
V.sims.forEach(s => { close(S.simulate(s.params, s.paths, s.seed), s.out, s.name); n++; });
const t = V.tornado; close(S.tornado(t.params, t.paths, t.seed), t.out, "tornado"); n++;
const h = V.heatmap; close(S.heatmap(h.params, h.down_pcts, h.terms, h.paths, h.seed), h.out, "heatmap"); n++;
const m = V.max_term; close(S.maxTerm(m.params, m.target, m.terms, m.paths, m.seed), m.out, "max_term"); n++;
const x = V.xray; close(S.planXray(x.price, x.rate, x.plans), x.out, "xray"); n++;
const h2 = V.heatmap_conflicts; close(S.heatmap(h2.params, h2.down_pcts, h2.terms, h2.paths, h2.seed), h2.out, "heatmap_conflicts"); n++;
const m2 = V.max_term_conflicts; close(S.maxTerm(m2.params, m2.target, m2.terms, m2.paths, m2.seed), m2.out, "max_term_conflicts"); n++;
const t2 = V.tornado_m2; close(S.tornado(t2.params, t2.paths, t2.seed), t2.out, "tornado_m2"); n++;
V.metrics.forEach((mm, i) => { close(S.metrics(mm.params), mm.out, "metrics" + i); n++; });
console.log(`ok: ${n} vector groups match the Python reference`);
