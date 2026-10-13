import json, os, subprocess, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from survival import simulate, tornado, heatmap, max_term, plan_xray, make_rng, z_score
from survival.engine import params_from, _weights

ROOT = os.path.join(os.path.dirname(__file__), "..")


class RngTests(unittest.TestCase):
    def test_deterministic_and_in_range(self):
        a, b = make_rng(5), make_rng(5)
        xs = [a() for _ in range(1000)]
        self.assertEqual(xs, [b() for _ in range(1000)])
        self.assertTrue(all(0 <= x < 1 for x in xs))

    def test_z_moments(self):
        r = make_rng(1)
        zs = [z_score(r) for _ in range(20000)]
        mean = sum(zs) / len(zs)
        var = sum((z - mean) ** 2 for z in zs) / len(zs)
        self.assertLess(abs(mean), 0.03)
        self.assertLess(abs(var - 1), 0.05)


class EngineTests(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(_weights(36)), 1.0, places=12)

    def test_reproducible(self):
        self.assertEqual(simulate({}, 100, 3), simulate({}, 100, 3))

    def test_more_cash_less_default(self):
        lo = simulate({"opening_cash": 100}, 300, 1, fan=False)["default_prob"]
        hi = simulate({"opening_cash": 500}, 300, 1, fan=False)["default_prob"]
        self.assertGreaterEqual(lo, hi)

    def test_deterministic_world_when_no_noise(self):
        r = simulate({"velocity": 0, "presold": 0, "velocity_sd": 0, "infl_sd": 0, "collect_sd": 0}, 10, 1)
        self.assertIn(r["default_prob"], (0.0, 1.0))
        self.assertEqual(r["fan"]["0.05"], r["fan"]["0.95"])

    def test_fan_shapes_and_order(self):
        r = simulate({}, 200, 2)
        D = 36
        for q in r["fan"].values():
            self.assertEqual(len(q), D + 1)
        for t in range(D + 1):
            self.assertLessEqual(r["fan"]["0.05"][t], r["fan"]["0.5"][t])
            self.assertLessEqual(r["fan"]["0.5"][t], r["fan"]["0.95"][t])

    def test_breach_histogram_matches_count(self):
        r = simulate({}, 300, 4, fan=False)
        self.assertEqual(sum(r["first_breach_hist"]), r["defaults"])

    def test_validation(self):
        for bad in ({"months": 0}, {"presold": 999}, {"down_pct": 1.5}, {"term": 0},
                    {"collect_mean": 2}, {"price": -1}):
            with self.assertRaises(ValueError):
                params_from(bad)
        with self.assertRaises(ValueError):
            simulate({}, 0)

    def test_tornado_sorted_and_signs(self):
        t = tornado({}, 150, 1)
        swings = [r["swing"] for r in t["rows"]]
        self.assertEqual(swings, sorted(swings, reverse=True))
        row = {r["driver"]: r for r in t["rows"]}
        self.assertGreaterEqual(row["budget"]["p_high"], row["budget"]["p_low"])
        self.assertGreaterEqual(row["opening_cash"]["p_low"], row["opening_cash"]["p_high"])

    def test_heatmap_and_max_term(self):
        h = heatmap({}, [0.1, 0.4], [12, 60], 80, 1)
        self.assertEqual((len(h["grid"]), len(h["grid"][0])), (2, 2))
        m = max_term({}, 1.0, [12, 24], 50, 1)
        self.assertEqual(m["best_term"], 24)
        m = max_term({"opening_cash": 0, "credit_line": 0}, 0.0, [12], 50, 1)
        self.assertIsNone(m["best_term"])


class XrayTests(unittest.TestCase):
    def test_cash_is_worth_full_price(self):
        r = plan_xray(6.0, 0.27, [{"name": "cash", "down_pct": 1.0, "term": 1}])
        self.assertAlmostEqual(r["rows"][0]["pv_share"], 1.0)

    def test_zero_rate_no_haircut(self):
        r = plan_xray(6.0, 0.0, [{"name": "x", "down_pct": 0.1, "term": 60}])
        self.assertAlmostEqual(r["rows"][0]["haircut"], 0.0, places=12)

    def test_longer_plan_costs_more(self):
        r = plan_xray(6.0, 0.27, [{"name": "a", "down_pct": 0.1, "term": 24},
                                  {"name": "b", "down_pct": 0.1, "term": 84},
                                  {"name": "c", "down_pct": 0.1, "term": 24, "grace": 12}])
        a, b, c = (x["haircut"] for x in r["rows"])
        self.assertLess(a, b)
        self.assertLess(a, c)


class VectorTests(unittest.TestCase):
    def test_vectors_not_stale(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_vectors.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
