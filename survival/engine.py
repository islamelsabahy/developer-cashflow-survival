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

Egyptian-market pricing and payment-plan options (all default to "off", so a call that does
not mention them behaves exactly like version 0.1):
  * price basis: either a fixed unit price, or area (m2) x price per m2 (price_by_m2 = 1);
  * price_growth: annual escalation applied to units sold after month 0 (0 = locked price);
  * freq: months between regular installments (1 monthly, 3 quarterly, 6 semi-annual, 12 annual);
  * delivery_pct: share of price paid at delivery; balloon_pct: share paid as yearly payments;
  * cash_share / cash_discount: buyers paying in full at contract, with a cash discount;
  * maint_pct: maintenance deposit on top of the price, counted as developer cash only when
    maint_counted = 1 (otherwise it sits in escrow and is ignored).
  Mutually exclusive choices are rejected by validate(): yearly balloon payments cannot be
  combined with yearly installments, and down + delivery + balloon cannot exceed 100%.
"""
import math
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
    # pricing and payment-plan options (defaults reproduce version 0.1 exactly)
    "area": 150.0,             # average unit area in m2
    "price_m2": 40000.0,       # price per m2 in currency units (not millions)
    "price_by_m2": 0,          # 1 = price is area * price_m2, 0 = fixed `price`
    "price_growth": 0.0,       # annual price escalation for new sales (0 = locked)
    "freq": 1,                 # months between regular installments: 1, 3, 6 or 12
    "delivery_pct": 0.0,       # share of price paid at delivery
    "balloon_pct": 0.0,        # share of price paid as yearly payments
    "cash_share": 0.0,         # share of new buyers paying full cash at contract
    "cash_discount": 0.0,      # discount given to cash buyers
    "maint_pct": 0.0,          # maintenance deposit, share of price, paid at delivery
    "maint_counted": 0,        # 1 = deposit counts as developer cash, 0 = escrow (ignored)
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
    area: float = DEFAULTS["area"]
    price_m2: float = DEFAULTS["price_m2"]
    price_by_m2: int = DEFAULTS["price_by_m2"]
    price_growth: float = DEFAULTS["price_growth"]
    freq: int = DEFAULTS["freq"]
    delivery_pct: float = DEFAULTS["delivery_pct"]
    balloon_pct: float = DEFAULTS["balloon_pct"]
    cash_share: float = DEFAULTS["cash_share"]
    cash_discount: float = DEFAULTS["cash_discount"]
    maint_pct: float = DEFAULTS["maint_pct"]
    maint_counted: int = DEFAULTS["maint_counted"]

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
        if not (float(self.area) > 0.0):
            raise ValueError("area must be > 0")
        if float(self.price_m2) < 0:
            raise ValueError("price_m2 must be >= 0")
        for name in ("price_by_m2", "maint_counted"):
            if int(getattr(self, name)) not in (0, 1):
                raise ValueError(name + " must be 0 or 1")
        if not (0.0 <= float(self.price_growth) <= 3.0):
            raise ValueError("price_growth must be 0..3 (annual)")
        if int(self.freq) not in (1, 3, 6, 12):
            raise ValueError("freq must be 1, 3, 6 or 12 months")
        if int(self.term) < int(self.freq):
            raise ValueError("term must cover at least one installment period")
        for name in ("delivery_pct", "balloon_pct", "cash_share", "maint_pct"):
            if not (0.0 <= float(getattr(self, name)) <= 1.0):
                raise ValueError(name + " must be 0..1")
        if not (0.0 <= float(self.cash_discount) < 1.0):
            raise ValueError("cash_discount must be 0..1 (exclusive of 1)")
        if float(self.down_pct) + float(self.delivery_pct) + float(self.balloon_pct) > 1.0 + 1e-12:
            raise ValueError("down payment + delivery + yearly payments exceed 100%")
        if float(self.balloon_pct) > 0.0 and int(self.freq) == 12:
            raise ValueError("yearly payments conflict with yearly installments: choose one")
        if float(self.balloon_pct) > 0.0 and int(self.term) < 12:
            raise ValueError("yearly payments need a term of at least 12 months")
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


# ---------------------------------------------------------------- pricing helpers

def effective_price(p):
    """Base unit price in millions: area * price_m2 / 1e6, or the fixed unit price."""
    if int(p.price_by_m2):
        return float(p.area) * float(p.price_m2) / 1000000.0
    return float(p.price)


def _inst_share(dp, dl, bl):
    share = 1.0 - dp - dl - bl
    return 0.0 if share < 1e-12 else share


def _book(inflow, t, n, P, plan):
    """Book n units sold in month t at unit price P; return the cash received at contract.

    `plan` is a tuple (dp, dl, bl, share, N, B, f, D, cs, cd, mp). Money due later goes into
    `inflow[month]`; anything beyond the horizon D is dropped (it is after delivery).
    """
    dp, dl, bl, share, N, B, f, D, cs, cd, mp = plan
    got = 0.0
    if cs > 0.0:
        got += n * cs * P * (1.0 - cd)
        n = n * (1.0 - cs)
    got += n * P * dp
    if share > 0.0:
        amt = n * P * share / N
        for j in range(1, N + 1):
            m = t + j * f
            if m > D:
                break
            inflow[m] += amt
    if bl > 0.0:
        amtb = n * P * bl / B
        for j in range(1, B + 1):
            m = t + 12 * j
            if m > D:
                break
            inflow[m] += amtb
    if dl > 0.0:
        inflow[D] += n * P * dl
    if mp > 0.0:
        inflow[D] += n * P * mp
    return got


def _plan(p, cash_split=True):
    dp = float(p.down_pct)
    dl = float(p.delivery_pct)
    bl = float(p.balloon_pct)
    f = int(p.freq)
    mp = float(p.maint_pct) if int(p.maint_counted) else 0.0
    return (dp, dl, bl, _inst_share(dp, dl, bl), int(p.term) // f, int(p.term) // 12, f,
            int(p.months), float(p.cash_share) if cash_split else 0.0,
            float(p.cash_discount), mp)


# ---------------------------------------------------------------- one path

def run_path(p, rnd, weights):
    D = int(p.months)
    price = effective_price(p)
    inflow = [0.0] * (D + 2)
    cash = float(p.opening_cash)
    breach = 0
    plan_new = _plan(p, True)
    plan_pre = _plan(p, False)
    pg = float(p.price_growth) / 12.0
    pidx = 1.0

    vf = 1.0 + float(p.velocity_sd) * z_score(rnd)
    if vf < 0.0:
        vf = 0.0

    left = int(p.units) - int(p.presold)
    if p.presold:
        cash += _book(inflow, 0, p.presold, price, plan_pre)

    index = 1.0
    path = [cash]
    for t in range(1, D + 1):
        zi = z_score(rnd)
        zs = z_score(rnd)
        zc = z_score(rnd)
        pi = _clamp(float(p.infl_mean) + float(p.infl_sd) * zi, -0.5, 0.5)
        index = index * (1.0 + pi)
        pidx = pidx * (1.0 + pg)

        mean = float(p.velocity) * vf
        n = 0
        if left > 0 and mean > 0.0:
            n = int(_round_half_up(mean + math.sqrt(mean) * zs))
            if n > left:
                n = left
        left -= n
        if n:
            cash += _book(inflow, t, n, price * pidx, plan_new)

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

def _plain_sum(xs):
    """Left-to-right float sum (Python 3.12 changed sum() to compensated summation)."""
    acc = 0.0
    for x in xs:
        acc += x
    return acc


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
        "final_cash_mean": _plain_sum(finals) / paths,
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
        key = "price_m2" if (name == "price" and int(p.price_by_m2)) else name
        v = float(getattr(p, key))
        lo_v, hi_v = v * (1.0 - swing), v * (1.0 + swing)
        if name == "collect_mean":
            hi_v = min(hi_v, 1.0)
        if name == "down_pct":
            hi_v = min(hi_v, 1.0 - float(p.delivery_pct) - float(p.balloon_pct))
        lo = simulate(p.replace(**{key: lo_v}), paths, seed, fan=False)
        hi = simulate(p.replace(**{key: hi_v}), paths, seed, fan=False)
        rows.append({
            "driver": name, "low_value": lo_v, "high_value": hi_v,
            "p_low": lo["default_prob"], "p_high": hi["default_prob"],
            "swing": abs(hi["default_prob"] - lo["default_prob"]),
        })
    rows.sort(key=lambda r: (-r["swing"], r["driver"]))
    return {"base": base["default_prob"], "rows": rows}


def _try_prob(p, paths, seed):
    """Default probability, or None when the combination is not allowed (conflicting options)."""
    try:
        return simulate(p, paths, seed, fan=False)["default_prob"]
    except ValueError:
        return None


def heatmap(params, down_pcts, terms, paths=400, seed=1):
    p = params if isinstance(params, Params) else params_from(params)
    grid = []
    for dp in down_pcts:
        row = []
        for k in terms:
            row.append(_try_prob(p.replace(down_pct=dp, term=int(k)), paths, seed))
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
        pr = _try_prob(p.replace(term=int(k)), paths, seed)
        curve.append([int(k), pr])
        if pr is not None and pr <= target:
            best = int(k)
    return {"target": target, "best_term": best, "curve": curve}


def plan_xray(price, annual_rate, plans):
    """Present value of payment plans. Monthly rate = annual/12 (simple nominal).

    plans: [{"name": str, "down_pct": 0..1, "term": months, "grace": months before the first
    installment (default 0), "freq": months between installments, 1/3/6/12 (default 1),
    "delivery_pct": share paid at delivery (default 0), "delivery_month": month of that payment
    (default: the month the installments end)}]. Returns PV as a share of list price and the
    implied haircut.
    """
    if annual_rate < 0 or price <= 0:
        raise ValueError("price must be > 0 and rate >= 0")
    r = annual_rate / 12.0
    rows = []
    for pl in plans:
        dp = float(pl["down_pct"])
        k = int(pl["term"])
        g = int(pl.get("grace", 0))
        f = int(pl.get("freq", 1))
        dl = float(pl.get("delivery_pct", 0.0))
        if not (0.0 <= dp <= 1.0) or k < 1 or g < 0:
            raise ValueError("bad plan: " + str(pl.get("name")))
        if f not in (1, 3, 6, 12) or k < f:
            raise ValueError("bad frequency or term: " + str(pl.get("name")))
        if not (0.0 <= dl <= 1.0) or dp + dl > 1.0 + 1e-12:
            raise ValueError("down payment + delivery exceed 100%: " + str(pl.get("name")))
        n = k // f
        last = g + n * f
        dm = int(pl.get("delivery_month", 0)) or last
        if dm < 1:
            raise ValueError("bad delivery month: " + str(pl.get("name")))
        share = _inst_share(dp, dl, 0.0)
        pv = price * dp
        each = price * share / n
        dlv = price * dl
        df = 1.0
        for m in range(1, max(last, dm) + 1):
            df = df / (1.0 + r)
            if m > g and (m - g) % f == 0 and m <= last:
                pv += each * df
            if dl > 0.0 and m == dm:
                pv += dlv * df
        rows.append({"name": pl.get("name", ""), "down_pct": dp, "term": k, "grace": g, "freq": f,
                     "delivery_pct": dl, "delivery_month": dm if dl > 0.0 else 0,
                     "pv": pv, "pv_share": pv / price, "haircut": 1.0 - pv / price})
    return {"price": price, "annual_rate": annual_rate, "rows": rows}


def metrics(params):
    """Egyptian-style unit economics: price per m2, total area, sales value, cost per m2.

    Money fields are in millions except the per-m2 fields, which are in currency units.
    Cost per m2 is construction budget / total sellable area (before overhead and interest).
    """
    p = params if isinstance(params, Params) else params_from(params)
    price = effective_price(p)
    area = float(p.area)
    total_area = area * int(p.units)
    gdv = price * int(p.units)
    price_m2 = float(p.price_m2) if int(p.price_by_m2) else price * 1000000.0 / area
    cost_m2 = float(p.budget) * 1000000.0 / total_area
    overhead_m2 = float(p.overhead) * int(p.months) * 1000000.0 / total_area
    dp = float(p.down_pct)
    dl = float(p.delivery_pct)
    bl = float(p.balloon_pct)
    return {
        "unit_price": price, "price_m2": price_m2, "area": area, "total_area": total_area,
        "gdv": gdv, "cost_m2": cost_m2, "overhead_m2": overhead_m2,
        "margin_m2": price_m2 - cost_m2,
        "breakeven_m2": cost_m2 + overhead_m2,
        "gross_margin": (gdv - float(p.budget)) / gdv if gdv > 0.0 else 0.0,
        "split": {"down": dp, "installments": _inst_share(dp, dl, bl), "yearly": bl, "delivery": dl,
                  "installment_count": int(p.term) // int(p.freq), "yearly_count": int(p.term) // 12,
                  "maintenance": float(p.maint_pct)},
    }
