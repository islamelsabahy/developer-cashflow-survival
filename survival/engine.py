"""Monte Carlo survival engine for an off-plan real-estate developer.

Question answered: "With this payment plan, how likely is the developer to run out of
cash (beyond its credit line) before delivery?"

Design notes (the JS port in docs/survival.js must match this file):
  * Only +, -, *, / and sqrt are used on floats, so IEEE-754 doubles give identical results in
    Python and JavaScript. No exp/log/pow in the simulation path.
  * The random generator is mulberry32 (32-bit integer arithmetic) and a "normal" draw is the
    Irwin-Hall approximation: sum of 12 uniforms minus 6 (mean 0, sd 1, bounded at +-6).
  * Draw order is fixed: per path one velocity draw, then per month inflation, sales,
    collection (three draws), whether or not the path already defaulted.
  * Money is in "millions" of any currency; this is a planning model, not accounting.
"""
from dataclasses import dataclass, asdict, fields

M32 = 0xFFFFFFFF

DEFAULTS = {
    "months": 36,              # months until delivery (simulation horizon)
    "units": 200,
    "price": 6.0,              # average price per unit
    "down_pct": 0.20,          # share of price paid at contract
    "term": 48,                # equal installments after the down payment
    "presold": 30,             # units already contracted at month 0
    "velocity": 4.5,           # expected units sold per month
    "velocity_sd": 0.35,       # path-level uncertainty of sales pace (relative)
    "budget": 520.0,           # construction budget (real terms)
    "infl_mean": 0.012,        # monthly construction-cost inflation
    "infl_sd": 0.010,
    "opening_cash": 190.0,
    "overhead": 3.0,           # fixed monthly overhead
    "credit_line": 90.0,       # tolerated negative cash
    "credit_rate": 0.02,       # monthly interest on negative cash
    "collect_mean": 0.93,      # share of due installments actually collected
    "collect_sd": 0.05,
}


@dataclass
class Params:
    months: int = DEFAULTS["months"]
    units: int = DEFAULTS["units"]
    price: float = DEFAULTS["price"]
    down_pct: float = DEFAULTS["down_pct"]
    term: int = DEFAULTS["term"]
    presold: int = DEFAULTS["presold"]
    velocity: float = DEFAULTS["velocity"]
    velocity_sd: float = DEFAULTS["velocity_sd"]
    budget: float = DEFAULTS["budget"]
    infl_mean: float = DEFAULTS["infl_mean"]
    infl_sd: float = DEFAULTS["infl_sd"]
    opening_cash: float = DEFAULTS["opening_cash"]
    overhead: float = DEFAULTS["overhead"]
    credit_line: float = DEFAULTS["credit_line"]
    credit_rate: float = DEFAULTS["credit_rate"]
    collect_mean: float = DEFAULTS["collect_mean"]
    collect_sd: float = DEFAULTS["collect_sd"]

    def validate(self):
        if not (1 <= int(self.months) <= 120):
            raise ValueError("months must be 1..120")
        if not (1 <= int(self.units) <= 100000):
            raise ValueError("units must be 1..100000")
        if not (0 <= int(self.presold) <= int(self.units)):
            raise ValueError("presold must be between 0 and units")
        if not (0.0 <= float(self.down_pct) <= 1.0):
            raise ValueError("down_pct must be 0..1")
        if not (1 <= int(self.term) <= 240):
            raise ValueError("term must be 1..240")
        for name in ("price", "velocity", "velocity_sd", "budget", "infl_sd", "opening_cash",
                     "overhead", "credit_line", "credit_rate", "collect_sd"):
            if float(getattr(self, name)) < 0:
                raise ValueError(name + " must be >= 0")
        if not (0.0 <= float(self.collect_mean) <= 1.0):
            raise ValueError("collect_mean must be 0..1")
        return self

    def replace(self, **kw):
        d = asdict(self)
        d.update(kw)
        return Params(**d)


def params_from(d):
    base = dict(DEFAULTS)
    base.update(d or {})
    known = {f.name for f in fields(Params)}
    return Params(**{k: v for k, v in base.items() if k in known}).validate()


# ---------------------------------------------------------------- random numbers

def make_rng(seed):
    """mulberry32 -> callable returning floats in [0, 1)."""
    state = [int(seed) & M32]

    def rnd():
        a = (state[0] + 0x6D2B79F5) & M32
        state[0] = a
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & M32
        t = t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & M32)) & M32)
        return ((t ^ (t >> 14)) & M32) / 4294967296.0
    return rnd


def z_score(rnd):
    s = 0.0
    for _ in range(12):
        s += rnd()
    return s - 6.0


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _round_half_up(x):
    return float(int(x + 0.5)) if x >= 0 else 0.0


def _weights(months):
    """S-curve construction spend: smoothstep differences, sums to 1."""
    def s(x):
        return 3.0 * x * x - 2.0 * x * x * x
    out = []
    for t in range(1, months + 1):
        out.append(s(t / months) - s((t - 1) / months))
    return out


# ---------------------------------------------------------------- one path

def run_path(p, rnd, weights):
    D = int(p.months)
    K = int(p.term)
    price = float(p.price)
    dp = float(p.down_pct)
    inflow = [0.0] * (D + 2)
    cash = float(p.opening_cash)
    breach = 0

    vf = 1.0 + float(p.velocity_sd) * z_score(rnd)
    if vf < 0.0:
        vf = 0.0

    left = int(p.units) - int(p.presold)
    if p.presold:
        cash += p.presold * price * dp
        amt = p.presold * price * (1.0 - dp) / K
        for j in range(1, min(K, D) + 1):
            inflow[j] += amt

    index = 1.0
    path = [cash]
    for t in range(1, D + 1):
        zi = z_score(rnd)
        zs = z_score(rnd)
        zc = z_score(rnd)
        pi = _clamp(float(p.infl_mean) + float(p.infl_sd) * zi, -0.5, 0.5)
        index = index * (1.0 + pi)

        mean = float(p.velocity) * vf
        n = 0
        if left > 0 and mean > 0.0:
            n = int(_round_half_up(mean + (mean ** 0.5) * zs))
            if n > left:
                n = left
        left -= n
        if n:
            cash += n * price * dp
            amt = n * price * (1.0 - dp) / K
            for j in range(t + 1, min(t + K, D) + 1):
                inflow[j] += amt

        eff = _clamp(float(p.collect_mean) + float(p.collect_sd) * zc, 0.0, 1.0)
        due = inflow[t]
        got = due * eff
        cash += got
        if t < D:
            inflow[t + 1] += due - got

        if cash < 0.0:
            cash += cash * float(p.credit_rate)
        cash -= float(p.budget) * weights[t - 1] * index + float(p.overhead)

        if breach == 0 and cash < -float(p.credit_line):
            breach = t
        path.append(cash)
    return path, breach


# ---------------------------------------------------------------- aggregation

def _pct(sorted_vals, q):
    return sorted_vals[int(q * (len(sorted_vals) - 1))]


QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)


def simulate(params, paths=2000, seed=1, fan=True):
    p = params if isinstance(params, Params) else params_from(params)
    p.validate()
    paths = int(paths)
    if paths < 1:
        raise ValueError("paths must be >= 1")
    rnd = make_rng(seed)
    w = _weights(int(p.months))
    D = int(p.months)
    cols = [[] for _ in range(D + 1)] if fan else None
    finals = []
    hist = [0] * (D + 1)
    defaults = 0
    for _ in range(paths):
        path, breach = run_path(p, rnd, w)
        finals.append(path[-1])
        if breach:
            defaults += 1
            hist[breach] += 1
        if fan:
            for t, v in enumerate(path):
                cols[t].append(v)
    finals_sorted = sorted(finals)
    out = {
        "paths": paths,
        "seed": int(seed),
        "default_prob": defaults / paths,
        "defaults": defaults,
        "first_breach_hist": hist,
        "final_cash": {str(q): _pct(finals_sorted, q) for q in QUANTILES},
        "final_cash_mean": sum(finals) / paths,
    }
    if fan:
        fan_out = {}
        for q in QUANTILES:
            fan_out[str(q)] = [_pct(sorted(c), q) for c in cols]
        out["fan"] = fan_out
    return out


TORNADO_DRIVERS = ("velocity", "budget", "infl_mean", "collect_mean", "price", "down_pct",
                   "opening_cash", "credit_line")


def tornado(params, paths=1000, seed=1, swing=0.2):
    """Shift each driver by -/+swing (relative) with common random numbers."""
    p = params if isinstance(params, Params) else params_from(params)
    base = simulate(p, paths, seed, fan=False)
    rows = []
    for name in TORNADO_DRIVERS:
        v = float(getattr(p, name))
        lo_v, hi_v = v * (1.0 - swing), v * (1.0 + swing)
        if name in ("collect_mean", "down_pct"):
            hi_v = min(hi_v, 1.0)
        lo = simulate(p.replace(**{name: lo_v}), paths, seed, fan=False)
        hi = simulate(p.replace(**{name: hi_v}), paths, seed, fan=False)
        rows.append({
            "driver": name, "low_value": lo_v, "high_value": hi_v,
            "p_low": lo["default_prob"], "p_high": hi["default_prob"],
            "swing": abs(hi["default_prob"] - lo["default_prob"]),
        })
    rows.sort(key=lambda r: (-r["swing"], r["driver"]))
    return {"base": base["default_prob"], "rows": rows}


def heatmap(params, down_pcts, terms, paths=400, seed=1):
    p = params if isinstance(params, Params) else params_from(params)
    grid = []
    for dp in down_pcts:
        row = []
        for k in terms:
            r = simulate(p.replace(down_pct=dp, term=int(k)), paths, seed, fan=False)
            row.append(r["default_prob"])
        grid.append(row)
    return {"down_pcts": list(down_pcts), "terms": list(terms), "grid": grid}


def max_term(params, target=0.05, terms=None, paths=400, seed=1):
    """Longest installment term (from the candidate list) whose default probability <= target.

    Probability is non-monotone in noise, so we scan every candidate and report the largest
    one that passes, plus the full curve.
    """
    p = params if isinstance(params, Params) else params_from(params)
    terms = list(terms) if terms is not None else list(range(6, 121, 6))
    curve = []
    best = None
    for k in terms:
        pr = simulate(p.replace(term=int(k)), paths, seed, fan=False)["default_prob"]
        curve.append([int(k), pr])
        if pr <= target:
            best = int(k)
    return {"target": target, "best_term": best, "curve": curve}


def plan_xray(price, annual_rate, plans):
    """Present value of payment plans. Monthly rate = annual/12 (simple nominal).

    plans: [{"name": str, "down_pct": 0..1, "term": months, "grace": months before first
    installment (default 0)}]. Returns PV as a share of list price and the implied haircut.
    """
    if annual_rate < 0 or price <= 0:
        raise ValueError("price must be > 0 and rate >= 0")
    r = annual_rate / 12.0
    rows = []
    for pl in plans:
        dp = float(pl["down_pct"])
        k = int(pl["term"])
        g = int(pl.get("grace", 0))
        if not (0.0 <= dp <= 1.0) or k < 1 or g < 0:
            raise ValueError("bad plan: " + str(pl.get("name")))
        pv = price * dp
        each = price * (1.0 - dp) / k
        df = 1.0
        for m in range(1, g + k + 1):
            df = df / (1.0 + r)
            if m > g:
                pv += each * df
        rows.append({"name": pl.get("name", ""), "down_pct": dp, "term": k, "grace": g,
                     "pv": pv, "pv_share": pv / price, "haircut": 1.0 - pv / price})
    return {"price": price, "annual_rate": annual_rate, "rows": rows}
