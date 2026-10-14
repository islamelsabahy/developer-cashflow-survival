import json, os, subprocess, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from survival import simulate, tornado, heatmap, max_term, plan_xray, metrics, make_rng, z_score
from survival.engine import params_from, _weights, _book, _plan, effective_price

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


class EgyptianOptionTests(unittest.TestCase):
    def test_per_m2_matches_unit_price_when_equal(self):
        a = simulate({"price": 6.0}, 120, 3)
        b = simulate({"price_by_m2": 1, "area": 150, "price_m2": 40000}, 120, 3)
        self.assertEqual(a, b)

    def test_defaults_do_not_change_when_new_fields_are_explicit(self):
        explicit = {"freq": 1, "delivery_pct": 0, "balloon_pct": 0, "cash_share": 0, "cash_discount": 0,
                    "maint_pct": 0, "maint_counted": 0, "price_growth": 0, "price_by_m2": 0}
        self.assertEqual(simulate({}, 100, 5), simulate(explicit, 100, 5))

    def test_effective_price(self):
        p = params_from({"price_by_m2": 1, "area": 120, "price_m2": 55000})
        self.assertAlmostEqual(effective_price(p), 6.6)
        self.assertEqual(effective_price(params_from({"price": 4.2})), 4.2)

    def _book_total(self, **kw):
        p = params_from(dict({"months": 120, "term": 96}, **kw))
        D = int(p.months)
        inflow = [0.0] * (D + 2)
        got = _book(inflow, 0, 10, 5.0, _plan(p, True))
        return got + sum(inflow)

    def test_whole_price_is_scheduled(self):
        for kw in ({}, {"freq": 3}, {"freq": 6, "delivery_pct": 0.1},
                   {"freq": 3, "balloon_pct": 0.2, "delivery_pct": 0.1, "down_pct": 0.1},
                   {"freq": 12, "delivery_pct": 0.2}):
            self.assertAlmostEqual(self._book_total(**kw), 50.0, places=9, msg=str(kw))

    def test_cash_buyers_pay_discounted_price_up_front(self):
        p = params_from({"cash_share": 1.0, "cash_discount": 0.3})
        inflow = [0.0] * 40
        got = _book(inflow, 1, 10, 5.0, _plan(p, True))
        self.assertAlmostEqual(got, 35.0)
        self.assertEqual(sum(inflow), 0.0)

    def test_presold_ignores_cash_split(self):
        p = params_from({"cash_share": 1.0, "cash_discount": 0.3, "months": 120, "term": 96})
        inflow = [0.0] * 122
        got = _book(inflow, 0, 10, 5.0, _plan(p, False))
        self.assertAlmostEqual(got + sum(inflow), 50.0)

    def test_maintenance_deposit_only_when_counted(self):
        base = {"maint_pct": 0.1, "months": 36, "term": 24}
        for counted, extra in ((0, 0.0), (1, 5.0)):
            p = params_from(dict(base, maint_counted=counted))
            inflow = [0.0] * 40
            got = _book(inflow, 0, 10, 5.0, _plan(p, True))
            self.assertAlmostEqual(got + sum(inflow), 50.0 + extra)

    def test_price_growth_never_hurts(self):
        flat = simulate({}, 200, 4, fan=False)["default_prob"]
        up = simulate({"price_growth": 0.2}, 200, 4, fan=False)["default_prob"]
        self.assertLessEqual(up, flat)

    def test_conflicts_are_rejected(self):
        for bad in ({"freq": 12, "balloon_pct": 0.1},
                    {"down_pct": 0.6, "delivery_pct": 0.3, "balloon_pct": 0.2},
                    {"term": 2, "freq": 3},
                    {"term": 10, "balloon_pct": 0.1},
                    {"freq": 4}, {"cash_discount": 1.0}, {"area": 0}, {"price_by_m2": 2},
                    {"price_growth": -0.1}, {"maint_counted": 3}):
            with self.assertRaises(ValueError, msg=str(bad)):
                params_from(bad)

    def test_heatmap_marks_conflicting_cells(self):
        h = heatmap({"delivery_pct": 0.5}, [0.1, 0.6], [12, 60], 40, 1)
        self.assertIsNotNone(h["grid"][0][0])
        self.assertIsNone(h["grid"][1][0])
        m = max_term({"freq": 12}, 1.0, [6, 12], 40, 1)
        self.assertIsNone(m["curve"][0][1])
        self.assertEqual(m["best_term"], 12)

    def test_tornado_price_driver_moves_price_m2_when_priced_per_m2(self):
        t = tornado({"price_by_m2": 1}, 100, 1)
        row = [r for r in t["rows"] if r["driver"] == "price"][0]
        self.assertAlmostEqual(row["low_value"], 40000 * 0.8)
        self.assertGreaterEqual(row["p_low"], row["p_high"])

    def test_xray_frequency_and_delivery(self):
        r = plan_xray(6.0, 0.27, [
            {"name": "monthly", "down_pct": 0.1, "term": 96},
            {"name": "quarterly", "down_pct": 0.1, "term": 96, "freq": 3},
            {"name": "yearly", "down_pct": 0.1, "term": 96, "freq": 12},
            {"name": "late delivery", "down_pct": 0.1, "term": 96, "delivery_pct": 0.3, "delivery_month": 120}])
        m, q, y, d = (x["haircut"] for x in r["rows"])
        self.assertLess(m, q)
        self.assertLess(q, y)
        self.assertLess(m, d)
        with self.assertRaises(ValueError):
            plan_xray(6.0, 0.27, [{"name": "bad", "down_pct": 0.8, "term": 12, "delivery_pct": 0.3}])

    def test_metrics(self):
        m = metrics({"price_by_m2": 1, "area": 100, "price_m2": 50000, "units": 100, "budget": 300})
        self.assertAlmostEqual(m["unit_price"], 5.0)
        self.assertAlmostEqual(m["total_area"], 10000)
        self.assertAlmostEqual(m["gdv"], 500.0)
        self.assertAlmostEqual(m["cost_m2"], 30000.0)
        self.assertAlmostEqual(m["margin_m2"], 20000.0)
        self.assertAlmostEqual(m["gross_margin"], 0.4)
        m = metrics({"price": 6.0, "area": 150})
        self.assertAlmostEqual(m["price_m2"], 40000.0)
        self.assertAlmostEqual(m["split"]["installments"], 0.8)


class VectorTests(unittest.TestCase):
    def test_vectors_not_stale(self):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_vectors.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
