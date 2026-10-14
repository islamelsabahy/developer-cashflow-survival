"""Generate tests/vectors.json from the Python reference (run with --check to detect drift)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from survival import simulate, tornado, heatmap, max_term, plan_xray, metrics, make_rng, z_score

PATH = os.path.join(os.path.dirname(__file__), "..", "tests", "vectors.json")


def build():
    rng = make_rng(12345)
    rnds = [rng() for _ in range(20)]
    rng = make_rng(99)
    zs = [z_score(rng) for _ in range(10)]
    scenarios = [
        {"name": "defaults", "params": {}, "paths": 150, "seed": 1},
        {"name": "tight", "params": {"opening_cash": 60, "credit_line": 20}, "paths": 150, "seed": 2},
        {"name": "flush", "params": {"opening_cash": 600}, "paths": 100, "seed": 3},
        {"name": "short-term", "params": {"term": 6, "down_pct": 0.5, "months": 24}, "paths": 120, "seed": 4},
        {"name": "no-presale", "params": {"presold": 0, "velocity": 2}, "paths": 100, "seed": 5},
        {"name": "sold-out", "params": {"units": 40, "presold": 30, "velocity": 6}, "paths": 100, "seed": 6},
        {"name": "zero-vol", "params": {"velocity_sd": 0, "infl_sd": 0, "collect_sd": 0}, "paths": 20, "seed": 7},
        # Egyptian-style options (added in 0.2)
        {"name": "per-m2", "params": {"price_by_m2": 1, "area": 140, "price_m2": 43000}, "paths": 100, "seed": 8},
        {"name": "quarterly-delivery", "params": {"freq": 3, "term": 96, "down_pct": 0.10, "delivery_pct": 0.10}, "paths": 100, "seed": 9},
        {"name": "yearly-balloon", "params": {"term": 60, "down_pct": 0.10, "balloon_pct": 0.20}, "paths": 100, "seed": 10},
        {"name": "cash-buyers", "params": {"cash_share": 0.25, "cash_discount": 0.30}, "paths": 100, "seed": 12},
        {"name": "escalating", "params": {"price_growth": 0.15, "infl_mean": 0.015}, "paths": 100, "seed": 13},
        {"name": "maintenance-counted", "params": {"maint_pct": 0.08, "maint_counted": 1, "delivery_pct": 0.10}, "paths": 100, "seed": 14},
        {"name": "everything", "params": {"price_by_m2": 1, "area": 120, "price_m2": 52000, "freq": 6, "term": 72,
                                          "down_pct": 0.10, "delivery_pct": 0.05, "balloon_pct": 0.10, "cash_share": 0.15,
                                          "cash_discount": 0.25, "price_growth": 0.10, "maint_pct": 0.07, "maint_counted": 1},
         "paths": 100, "seed": 15},
    ]
    sims = [dict(s, out=simulate(s["params"], s["paths"], s["seed"])) for s in scenarios]
    torn = {"params": {}, "paths": 120, "seed": 11, "out": tornado({}, 120, 11)}
    heat = {"params": {}, "down_pcts": [0.1, 0.3], "terms": [12, 60], "paths": 100, "seed": 5,
            "out": heatmap({}, [0.1, 0.3], [12, 60], 100, 5)}
    mt = {"params": {}, "target": 0.3, "terms": [12, 36, 60], "paths": 100, "seed": 5,
          "out": max_term({}, 0.3, [12, 36, 60], 100, 5)}
    plans = [{"name": "10/90 x60", "down_pct": 0.1, "term": 60},
             {"name": "25/75 x24 grace6", "down_pct": 0.25, "term": 24, "grace": 6},
             {"name": "cash", "down_pct": 1.0, "term": 1},
             {"name": "10% quarterly x96", "down_pct": 0.1, "term": 96, "freq": 3},
             {"name": "20% semi x72 + 10% delivery@84", "down_pct": 0.2, "term": 72, "freq": 6,
              "delivery_pct": 0.1, "delivery_month": 84},
             {"name": "10% yearly x60 + 15% delivery", "down_pct": 0.1, "term": 60, "freq": 12, "delivery_pct": 0.15}]
    xr = {"price": 6.0, "rate": 0.27, "plans": plans, "out": plan_xray(6.0, 0.27, plans)}
    heat2 = {"params": {"delivery_pct": 0.5}, "down_pcts": [0.1, 0.6], "terms": [6, 12, 60], "paths": 60,
             "seed": 5, "out": heatmap({"delivery_pct": 0.5}, [0.1, 0.6], [6, 12, 60], 60, 5)}
    mt2 = {"params": {"freq": 12}, "target": 1.0, "terms": [6, 12, 24], "paths": 60, "seed": 5,
           "out": max_term({"freq": 12}, 1.0, [6, 12, 24], 60, 5)}
    torn2 = {"params": {"price_by_m2": 1, "delivery_pct": 0.1}, "paths": 80, "seed": 3,
             "out": tornado({"price_by_m2": 1, "delivery_pct": 0.1}, 80, 3)}
    mets = [{"params": prm, "out": metrics(prm)} for prm in (
        {}, {"price_by_m2": 1, "area": 140, "price_m2": 43000, "freq": 3, "delivery_pct": 0.1,
             "balloon_pct": 0.1, "maint_pct": 0.08}, {"units": 80, "budget": 310})]
    return {"rng": rnds, "z": zs, "sims": sims, "tornado": torn, "heatmap": heat,
            "max_term": mt, "xray": xr, "heatmap_conflicts": heat2, "max_term_conflicts": mt2,
            "tornado_m2": torn2, "metrics": mets}


def main():
    text = json.dumps(build(), indent=1, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        with open(PATH, encoding="utf-8") as f:
            if f.read() != text:
                print("tests/vectors.json is stale; run scripts/build_vectors.py")
                sys.exit(1)
        print("vectors up to date")
        return
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote", PATH)


if __name__ == "__main__":
    main()
