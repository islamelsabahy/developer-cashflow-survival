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
    overhead: 3.0, credit_line: 90.0, credit_rate: 0.02, collect_mean: 0.93, collect_sd: 0.05,
    area: 150.0, price_m2: 40000.0, price_by_m2: 0, price_growth: 0.0, freq: 1, delivery_pct: 0.0,
    balloon_pct: 0.0, cash_share: 0.0, cash_discount: 0.0, maint_pct: 0.0, maint_counted: 0
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
    if (!(p.area > 0)) bad("area must be > 0");
    if (!(p.price_m2 >= 0)) bad("price_m2 must be >= 0");
    ["price_by_m2", "maint_counted"].forEach(function (n) {
      if (!(p[n] === 0 || p[n] === 1)) bad(n + " must be 0 or 1");
    });
    if (!(p.price_growth >= 0 && p.price_growth <= 3)) bad("price_growth must be 0..3 (annual)");
    p.freq = Math.trunc(p.freq);
    if ([1, 3, 6, 12].indexOf(p.freq) < 0) bad("freq must be 1, 3, 6 or 12 months");
    if (!(Math.trunc(p.term) >= p.freq)) bad("term must cover at least one installment period");
    ["delivery_pct", "balloon_pct", "cash_share", "maint_pct"].forEach(function (n) {
      if (!(p[n] >= 0 && p[n] <= 1)) bad(n + " must be 0..1");
    });
    if (!(p.cash_discount >= 0 && p.cash_discount < 1)) bad("cash_discount must be 0..1 (exclusive of 1)");
    if (p.down_pct + p.delivery_pct + p.balloon_pct > 1 + 1e-12) bad("down payment + delivery + yearly payments exceed 100%");
    if (p.balloon_pct > 0 && p.freq === 12) bad("yearly payments conflict with yearly installments: choose one");
    if (p.balloon_pct > 0 && Math.trunc(p.term) < 12) bad("yearly payments need a term of at least 12 months");
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

  function withParams2(p, kw) {
    var q = {};
    Object.keys(p).forEach(function (k) { q[k] = p[k]; });
    Object.keys(kw).forEach(function (k) { q[k] = kw[k]; });
    return q;
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

  function effectivePrice(p) {
    if (p.price_by_m2) return p.area * p.price_m2 / 1000000;
    return p.price;
  }

  function instShare(dp, dl, bl) {
    var share = 1 - dp - dl - bl;
    return share < 1e-12 ? 0 : share;
  }

  function makePlan(p, cashSplit) {
    var dp = p.down_pct, dl = p.delivery_pct, bl = p.balloon_pct, f = p.freq;
    var mp = p.maint_counted ? p.maint_pct : 0;
    return { dp: dp, dl: dl, bl: bl, share: instShare(dp, dl, bl), N: Math.floor(p.term / f),
      B: Math.floor(p.term / 12), f: f, D: p.months, cs: cashSplit ? p.cash_share : 0,
      cd: p.cash_discount, mp: mp };
  }

  function book(inflow, t, n, P, pl) {
    var got = 0, j, m;
    if (pl.cs > 0) {
      got += n * pl.cs * P * (1 - pl.cd);
      n = n * (1 - pl.cs);
    }
    got += n * P * pl.dp;
    if (pl.share > 0) {
      var amt = n * P * pl.share / pl.N;
      for (j = 1; j <= pl.N; j++) {
        m = t + j * pl.f;
        if (m > pl.D) break;
        inflow[m] += amt;
      }
    }
    if (pl.bl > 0) {
      var amtb = n * P * pl.bl / pl.B;
      for (j = 1; j <= pl.B; j++) {
        m = t + 12 * j;
        if (m > pl.D) break;
        inflow[m] += amtb;
      }
    }
    if (pl.dl > 0) inflow[pl.D] += n * P * pl.dl;
    if (pl.mp > 0) inflow[pl.D] += n * P * pl.mp;
    return got;
  }

  function runPath(p, rnd, w) {
    var D = p.months, j;
    var price = effectivePrice(p);
    var planNew = makePlan(p, true), planPre = makePlan(p, false);
    var pg = p.price_growth / 12, pidx = 1;
    var inflow = new Array(D + 2);
    for (j = 0; j < D + 2; j++) inflow[j] = 0;
    var cash = p.opening_cash, breach = 0;
    var vf = 1 + p.velocity_sd * zScore(rnd);
    if (vf < 0) vf = 0;
    var left = p.units - p.presold;
    if (p.presold) cash += book(inflow, 0, p.presold, price, planPre);
    var index = 1, path = [cash];
    for (var t = 1; t <= D; t++) {
      var zi = zScore(rnd), zs = zScore(rnd), zc = zScore(rnd);
      var pi = clamp(p.infl_mean + p.infl_sd * zi, -0.5, 0.5);
      index = index * (1 + pi);
      pidx = pidx * (1 + pg);
      var mean = p.velocity * vf, n = 0;
      if (left > 0 && mean > 0) {
        var x = mean + Math.sqrt(mean) * zs;
        n = x >= 0 ? Math.floor(x + 0.5) : 0;
        if (n > left) n = left;
      }
      left -= n;
      if (n) cash += book(inflow, t, n, price * pidx, planNew);
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
      var key = (name === "price" && p.price_by_m2) ? "price_m2" : name;
      var v = p[key], lo_v = v * (1 - swing), hi_v = v * (1 + swing);
      if (name === "collect_mean") hi_v = Math.min(hi_v, 1);
      if (name === "down_pct") hi_v = Math.min(hi_v, 1 - p.delivery_pct - p.balloon_pct);
      var a = {}, b = {};
      a[key] = lo_v; b[key] = hi_v;
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

  function tryProb(p, paths, seed) {
    try { return simulate(p, paths, seed, false).default_prob; } catch (e) { return null; }
  }

  function heatmap(params, downPcts, terms, paths, seed) {
    var p = paramsFrom(params);
    paths = paths === undefined ? 400 : paths; seed = seed === undefined ? 1 : seed;
    var grid = downPcts.map(function (dp) {
      return terms.map(function (k) {
        return tryProb(withParams2(p, { down_pct: dp, term: k }), paths, seed);
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
      var pr = tryProb(withParams2(p, { term: k }), paths, seed);
      curve.push([k, pr]);
      if (pr !== null && pr <= target) best = k;
    });
    return { target: target, best_term: best, curve: curve };
  }

  function planXray(price, annualRate, plans) {
    if (!(annualRate >= 0) || !(price > 0)) throw new Error("price must be > 0 and rate >= 0");
    var r = annualRate / 12;
    return { price: price, annual_rate: annualRate, rows: plans.map(function (pl) {
      var dp = Number(pl.down_pct), k = Math.trunc(pl.term), g = Math.trunc(pl.grace || 0);
      var f = Math.trunc(pl.freq || 1), dl = Number(pl.delivery_pct || 0);
      if (!(dp >= 0 && dp <= 1) || !(k >= 1) || !(g >= 0)) throw new Error("bad plan: " + pl.name);
      if ([1, 3, 6, 12].indexOf(f) < 0 || k < f) throw new Error("bad frequency or term: " + pl.name);
      if (!(dl >= 0 && dl <= 1) || dp + dl > 1 + 1e-12) throw new Error("down payment + delivery exceed 100%: " + pl.name);
      var n = Math.floor(k / f), last = g + n * f;
      var dm = Math.trunc(pl.delivery_month || 0) || last;
      if (dm < 1) throw new Error("bad delivery month: " + pl.name);
      var share = instShare(dp, dl, 0), pv = price * dp, each = price * share / n, dlv = price * dl, df = 1;
      for (var m = 1; m <= Math.max(last, dm); m++) {
        df = df / (1 + r);
        if (m > g && (m - g) % f === 0 && m <= last) pv += each * df;
        if (dl > 0 && m === dm) pv += dlv * df;
      }
      return { name: pl.name || "", down_pct: dp, term: k, grace: g, freq: f, delivery_pct: dl,
        delivery_month: dl > 0 ? dm : 0, pv: pv, pv_share: pv / price, haircut: 1 - pv / price };
    }) };
  }

  function metrics(params) {
    var p = paramsFrom(params), price = effectivePrice(p), area = p.area;
    var totalArea = area * p.units, gdv = price * p.units;
    var priceM2 = p.price_by_m2 ? p.price_m2 : price * 1000000 / area;
    var costM2 = p.budget * 1000000 / totalArea;
    var overheadM2 = p.overhead * p.months * 1000000 / totalArea;
    var dp = p.down_pct, dl = p.delivery_pct, bl = p.balloon_pct;
    return { unit_price: price, price_m2: priceM2, area: area, total_area: totalArea, gdv: gdv,
      cost_m2: costM2, overhead_m2: overheadM2, margin_m2: priceM2 - costM2,
      breakeven_m2: costM2 + overheadM2, gross_margin: gdv > 0 ? (gdv - p.budget) / gdv : 0,
      split: { down: dp, installments: instShare(dp, dl, bl), yearly: bl, delivery: dl,
        installment_count: Math.floor(p.term / p.freq), yearly_count: Math.floor(p.term / 12),
        maintenance: p.maint_pct } };
  }

  return { DEFAULTS: DEFAULTS, makeRng: makeRng, zScore: zScore, simulate: simulate,
    tornado: tornado, heatmap: heatmap, maxTerm: maxTerm, planXray: planXray, metrics: metrics, effectivePrice: effectivePrice,
    paramsFrom: paramsFrom };
});
