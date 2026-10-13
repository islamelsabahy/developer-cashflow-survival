"""Generate tests/vectors.json from the Python reference (run with --check to detect drift)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from survival import simulate, tornado, heatmap, max_term, plan_xray, make_rng, z_score

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
    ]
    sims = [dict(s, out=simulate(s["params"], s["paths"], s["seed"])) for s in scenarios]
    torn = {"params": {}, "paths": 120, "seed": 11, "out": tornado({}, 120, 11)}
    heat = {"params": {}, "down_pcts": [0.1, 0.3], "terms": [12, 60], "paths": 100, "seed": 5,
            "out": heatmap({}, [0.1, 0.3], [12, 60], 100, 5)}
    mt = {"params": {}, "target": 0.3, "terms": [12, 36, 60], "paths": 100, "seed": 5,
          "out": max_term({}, 0.3, [12, 36, 60], 100, 5)}
    plans = [{"name": "10/90 x60", "down_pct": 0.1, "term": 60},
             {"name": "25/75 x24 grace6", "down_pct": 0.25, "term": 24, "grace": 6},
             {"name": "cash", "down_pct": 1.0, "term": 1}]
    xr = {"price": 6.0, "rate": 0.27, "plans": plans, "out": plan_xray(6.0, 0.27, plans)}
    return {"rng": rnds, "z": zs, "sims": sims, "tornado": torn, "heatmap": heat,
            "max_term": mt, "xray": xr}


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
