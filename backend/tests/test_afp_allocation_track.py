import unittest

from app.utils.afp_allocation_track import (
    first_date_on_or_after,
    hold_return_pct,
    switching_path,
    weights_from_dist,
)


class WeightsTests(unittest.TestCase):
    def test_normalizes_two_funds(self):
        w = weights_from_dist([{"fondo": "B", "pct": 80}, {"fondo": "C", "pct": 20}])
        self.assertAlmostEqual(w["B"], 0.8)
        self.assertAlmostEqual(w["C"], 0.2)
        self.assertEqual(w["A"], 0.0)

    def test_empty(self):
        w = weights_from_dist([])
        self.assertEqual(sum(w.values()), 0)


class HoldReturnTests(unittest.TestCase):
    def test_single_fund(self):
        cuotas = {"A": {"2026-07-06": 100.0, "2026-08-30": 110.0}}
        w = {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0}
        self.assertEqual(hold_return_pct(w, cuotas, "2026-07-06", "2026-08-30"), 10.0)

    def test_blend(self):
        cuotas = {
            "B": {"d0": 100.0, "d1": 110.0},
            "C": {"d0": 100.0, "d1": 100.0},
        }
        w = {"A": 0, "B": 0.8, "C": 0.2, "D": 0, "E": 0}
        self.assertEqual(hold_return_pct(w, cuotas, "d0", "d1"), 8.0)


class SwitchingPathTests(unittest.TestCase):
    def test_rebalance_midway(self):
        dates = ["2026-07-06", "2026-07-07", "2026-07-08"]
        cuotas = {
            "A": {"2026-07-06": 100, "2026-07-07": 100, "2026-07-08": 110},
            "E": {"2026-07-06": 100, "2026-07-07": 100, "2026-07-08": 100},
        }
        all_e = {f: 0.0 for f in "ABCDE"}
        all_a = {f: 0.0 for f in "ABCDE"}
        all_e["E"] = 1.0
        all_a["A"] = 1.0
        events = [("2026-07-06", all_e), ("2026-07-07", all_a)]
        path = switching_path(dates, cuotas, events)
        self.assertEqual(path[0]["value"], 100.0)
        # 6→7 still in E (flat), rebalance to A on 07, 7→8 A +10%
        self.assertEqual(path[1]["value"], 100.0)
        self.assertEqual(path[2]["value"], 110.0)

    def test_first_date_skips_weekend(self):
        dates = ["2026-07-06", "2026-07-07"]
        self.assertEqual(first_date_on_or_after(dates, "2026-07-05"), "2026-07-06")


if __name__ == "__main__":
    unittest.main()
