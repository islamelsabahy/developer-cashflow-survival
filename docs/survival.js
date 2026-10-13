/* Browser port of survival/engine.py (the Python code is the reference).
 * Only + - * / and sqrt are used on doubles, so results match Python bit for bit.
 * `node tests/test_survival.js` replays tests/vectors.json.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Survival = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DEFAULTS = {
    months: 36, units: 200, price: 6.0, down_pct: 0.20, term: 48, presold: 30, velocity: 4.5,
    velocity_sd: 0.35, budget: 520.0, infl_mean: 0.012, infl_sd: 0.010, opening_cash: 190.0,
    overhead: 3.0, credit_line: 90.0, credit_rate: 0.02, collect_mean: 0.93, collect_sd: 0.05
  };
  var QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95];
  var TORNADO_DRIVERS = ["velocity", "budget", "infl_mean", "collect_mean", "price", "down_pct",
    "opening_cash", "credit_line"];

  function paramsFrom(d) {
    var p = {};
    Object.keys(DEFAULTS).forEach(function (k) { p[k] = DEFAULTS[k]; });
    Object.keys(d || {}).forEach(function (k) { if (k in DEFAULTS) p[k] = Number(d[k]); });
    return validate(p);
  }

  function validate(p) {
    function bad(m) { throw new Error(m); }
    if (!(p.months >= 1 && p.months <= 120)) bad("months must be 1..120");
    if (!(p.units >= 1 && p.units <= 100000)) bad("units must be 1..100000");
    if (!(p.presold >= 0 && p.presold <= p.units)) bad("presold must be between 0 and units");
    if (!(p.down_pct >= 0 && p.down_pct <= 1)) bad("down_pct must be 0..1");
    if (!(p.term >= 1 && p.term <= 240)) bad("term must be 1..240");
    ["price", "velocity", "velocity_sd", "budget", "infl_sd", "opening_cash", "overhead",
      "credit_line", "credit_rate", "collect_sd"].forEach(function (n) {
      if (!(p[n] >= 0)) bad(n + " must be >= 0");
    });
    if (!(p.collect_mean >= 0 && p.collect_mean <= 1)) bad("collect_mean must be 0..1");
    p.months = Math.trunc(p.months); p.units = Math.trunc(p.units);
    p.presold = Math.trunc(p.presold); p.term = Math.trunc(p.term);
    return p;
  }

  function withParams(p, kw) {
    var q = {};
    Object.keys(p).forEach(function (k) { q[k] = p[k]; });
    Object.keys(kw).forEach(function (k) { q[k] = kw[k]; });
    return validate(q);
  }

  function makeRng(seed) {
    var state = (seed >>> 0);
    return function () {
      state = (state + 0x6D2B79F5) >>> 0;
      var t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
      t = (t ^ ((t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0)) >>> 0)) >>> 0;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function zScore(rnd) {
    var s = 0;
    for (var i = 0; i < 12; i++) s += rnd();
    return s - 6;
  }

  function clamp(x, lo, hi) { return x < lo ? lo : x > hi ? hi : x; }

  function weights(months) {
    function s(x) { return 3 * x * x - 2 * x * x * x; }
    var out = [];
    for (var t = 1; t <= months; t++) out.push(s(t / months) - s((t - 1) / months));
    return out;
  }

  function runPath(p, rnd, w) {
    var D = p.months, K = p.term, price = p.price, dp = p.down_pct, j;
    var inflow = new Array(D + 2);
    for (j = 0; j < D + 2; j++) inflow[j] = 0;
    var cash = p.opening_cash, breach = 0;
    var vf = 1 + p.velocity_sd * zScore(rnd);
    if (vf < 0) vf = 0;
    var left = p.units - p.presold;
    if (p.presold) {
      cash += p.presold * price * dp;
      var a0 = p.presold * price * (1 - dp) / K;
      for (j = 1; j <= Math.min(K, D); j++) inflow[j] += a0;
    }
    var index = 1, path = [cash];
    for (var t = 1; t <= D; t++) {
      var zi = zScore(rnd), zs = zScore(rnd), zc = zScore(rnd);
      var pi = clamp(p.infl_mean + p.infl_sd * zi, -0.5, 0.5);
      index = index * (1 + pi);
      var mean = p.velocity * vf, n = 0;
      if (left > 0 && mean > 0) {
        var x = mean + Math.sqrt(mean) * zs;
        n = x >= 0 ? Math.floor(x + 0.5) : 0;
        if (n > left) n = left;
      }
      left -= n;
      if (n) {
        cash += n * price * dp;
        var a = n * price * (1 - dp) / K;
        for (j = t + 1; j <= Math.min(t + K, D); j++) inflow[j] += a;
      }
      var eff = clamp(p.collect_mean + p.collect_sd * zc, 0, 1);
      var due = inflow[t], got = due * eff;
      cash += got;
      if (t < D) inflow[t + 1] += due - got;
      if (cash < 0) cash += cash * p.credit_rate;
      cash -= p.budget * w[t - 1] * index + p.overhead;
      if (breach === 0 && cash < -p.credit_line) breach = t;
      path.push(cash);
    }
    return { path: path, breach: breach };
  }

  function pct(sorted, q) { return sorted[Math.floor(q * (sorted.length - 1))]; }
  function numSort(a, b) { return a - b; }

  function simulate(params, paths, seed, fan) {
    var p = paramsFrom(params);
    paths = paths === undefined ? 2000 : Math.trunc(paths);
    seed = seed === undefined ? 1 : seed;
    fan = fan === undefined ? true : fan;
    if (paths < 1) throw new Error("paths must be >= 1");
    var rnd = makeRng(seed), w = weights(p.months), D = p.months, t;
    var cols = null;
    if (fan) { cols = []; for (t = 0; t <= D; t++) cols.push([]); }
    var finals = [], hist = [], defaults = 0, i;
    for (t = 0; t <= D; t++) hist.push(0);
    for (i = 0; i < paths; i++) {
      var r = runPath(p, rnd, w);
      finals.push(r.path[D]);
      if (r.breach) { defaults++; hist[r.breach]++; }
      if (fan) for (t = 0; t <= D; t++) cols[t].push(r.path[t]);
    }
    var fs = finals.slice().sort(numSort), sum = 0;
    for (i = 0; i < finals.length; i++) sum += finals[i];
    var out = { paths: paths, seed: seed, default_prob: defaults / paths, defaults: defaults,
      first_breach_hist: hist, final_cash: {}, final_cash_mean: sum / paths };
    QUANTILES.forEach(function (q) { out.final_cash[String(q)] = pct(fs, q); });
    if (fan) {
      out.fan = {};
      QUANTILES.forEach(function (q) {
        out.fan[String(q)] = cols.map(function (c) { return pct(c.slice().sort(numSort), q); });
      });
    }
    return out;
  }

  function tornado(params, paths, seed, swing) {
    var p = paramsFrom(params);
    paths = paths === undefined ? 1000 : paths; seed = seed === undefined ? 1 : seed;
    swing = swing === undefined ? 0.2 : swing;
    var base = simulate(p, paths, seed, false), rows = [];
    TORNADO_DRIVERS.forEach(function (name) {
      var v = p[name], lo_v = v * (1 - swing), hi_v = v * (1 + swing);
      if (name === "collect_mean" || name === "down_pct") hi_v = Math.min(hi_v, 1);
      var a = {}, b = {};
      a[name] = lo_v; b[name] = hi_v;
      var lo = simulate(withParams(p, a), paths, seed, false);
      var hi = simulate(withParams(p, b), paths, seed, false);
      rows.push({ driver: name, low_value: lo_v, high_value: hi_v, p_low: lo.default_prob,
        p_high: hi.default_prob, swing: Math.abs(hi.default_prob - lo.default_prob) });
    });
    rows.sort(function (x, y) {
      if (y.swing !== x.swing) return y.swing - x.swing;
      return x.driver < y.driver ? -1 : x.driver > y.driver ? 1 : 0;
    });
    return { base: base.default_prob, rows: rows };
  }

  function heatmap(params, downPcts, terms, paths, seed) {
    var p = paramsFrom(params);
    paths = paths === undefined ? 400 : paths; seed = seed === undefined ? 1 : seed;
    var grid = downPcts.map(function (dp) {
      return terms.map(function (k) {
        return simulate(withParams(p, { down_pct: dp, term: k }), paths, seed, false).default_prob;
      });
    });
    return { down_pcts: downPcts.slice(), terms: terms.slice(), grid: grid };
  }

  function maxTerm(params, target, terms, paths, seed) {
    var p = paramsFrom(params);
    target = target === undefined ? 0.05 : target;
    paths = paths === undefined ? 400 : paths; seed = seed === undefined ? 1 : seed;
    if (!terms) { terms = []; for (var k = 6; k <= 120; k += 6) terms.push(k); }
    var curve = [], best = null;
    terms.forEach(function (k) {
      var pr = simulate(withParams(p, { term: k }), paths, seed, false).default_prob;
      curve.push([k, pr]);
      if (pr <= target) best = k;
    });
    return { target: target, best_term: best, curve: curve };
  }

  function planXray(price, annualRate, plans) {
    if (!(annualRate >= 0) || !(price > 0)) throw new Error("price must be > 0 and rate >= 0");
    var r = annualRate / 12;
    return { price: price, annual_rate: annualRate, rows: plans.map(function (pl) {
      var dp = Number(pl.down_pct), k = Math.trunc(pl.term), g = Math.trunc(pl.grace || 0);
      if (!(dp >= 0 && dp <= 1) || !(k >= 1) || !(g >= 0)) throw new Error("bad plan: " + pl.name);
      var pv = price * dp, each = price * (1 - dp) / k, df = 1;
      for (var m = 1; m <= g + k; m++) { df = df / (1 + r); if (m > g) pv += each * df; }
      return { name: pl.name || "", down_pct: dp, term: k, grace: g, pv: pv, pv_share: pv / price,
        haircut: 1 - pv / price };
    }) };
  }

  return { DEFAULTS: DEFAULTS, makeRng: makeRng, zScore: zScore, simulate: simulate,
    tornado: tornado, heatmap: heatmap, maxTerm: maxTerm, planXray: planXray, paramsFrom: paramsFrom };
});
