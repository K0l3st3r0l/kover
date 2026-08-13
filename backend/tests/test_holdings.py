"""K5.1 — covered calls sobre posiciones abiertas, con el costo real."""

import unittest
from datetime import date

from app.scanner.covered_calls import compute_covered_call
from app.scanner.holdings import (
    COST_BASIS_ADJUSTED,
    COST_BASIS_GROSS,
    evaluate_for_holding,
    rank_for_cycle,
    resolve_cost_basis,
)
from tests.test_covered_calls import make_quote

HOY = date(2026, 8, 13)


class FakeStock:
    def __init__(self, adjusted=None, average=None):
        self.adjusted_cost_basis = adjusted
        self.average_cost = average


def metrics(**overrides):
    return compute_covered_call(make_quote(**overrides), 14.0, 14.0, HOY)


class CostBasisTests(unittest.TestCase):
    def test_prefers_the_premium_adjusted_basis(self):
        """El costo que muestra la página Stocks como 'costo real' descuenta las
        primas del ciclo. En SMR eran $11,43 bruto contra $9,65 real: usar el
        bruto daba pérdida en strikes que en verdad dejan ganancia."""
        costo, fuente = resolve_cost_basis(FakeStock(adjusted=9.6488, average=11.4262))
        self.assertAlmostEqual(costo, 9.6488)
        self.assertEqual(fuente, COST_BASIS_ADJUSTED)

    def test_falls_back_to_gross_and_says_so(self):
        costo, fuente = resolve_cost_basis(FakeStock(adjusted=None, average=11.4262))
        self.assertAlmostEqual(costo, 11.4262)
        self.assertEqual(fuente, COST_BASIS_GROSS)

    def test_no_basis_at_all_is_none_not_zero(self):
        costo, _ = resolve_cost_basis(FakeStock())
        self.assertIsNone(costo)


class HoldingEvaluationTests(unittest.TestCase):
    def test_contracts_come_from_the_position_not_the_capital(self):
        h = evaluate_for_holding(metrics(), 9.65, COST_BASIS_ADJUSTED, shares=265)
        self.assertEqual(h.contracts, 2)
        self.assertEqual(h.uncovered_shares, 65)

    def test_under_one_hundred_shares_has_nothing_to_sell(self):
        self.assertIsNone(evaluate_for_holding(metrics(), 9.65, COST_BASIS_ADJUSTED, shares=99))

    def test_gain_is_measured_against_the_cost_basis_not_the_market(self):
        # strike 15, costo 9.65, 2 contratos: (15 - 9.65) * 200 = 1070 de capital
        h = evaluate_for_holding(metrics(strike=15.0, bid=0.20), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertAlmostEqual(h.gain_if_assigned, 1070.0, places=2)
        self.assertAlmostEqual(h.premium_total, 40.0, places=2)
        self.assertAlmostEqual(h.total_if_assigned, 1110.0, places=2)

    def test_below_cost_basis_and_net_loss_are_different_things(self):
        """Un strike bajo el costo realiza pérdida de capital, pero la prima
        puede taparla y dejar el ciclo en verde. Confundirlos descartaría
        operaciones que sí convienen: acá la pérdida de capital es -$130 y la
        prima $160, así que el neto es positivo."""
        h = evaluate_for_holding(metrics(strike=9.0, bid=0.80), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertTrue(h.below_cost_basis)
        self.assertFalse(h.net_loss_if_assigned)
        self.assertAlmostEqual(h.total_if_assigned, 30.0, places=2)

    def test_net_loss_when_the_premium_does_not_cover_the_gap(self):
        h = evaluate_for_holding(metrics(strike=9.0, bid=0.10), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertTrue(h.below_cost_basis)
        self.assertTrue(h.net_loss_if_assigned)

    def test_strike_above_cost_basis_is_not_flagged(self):
        h = evaluate_for_holding(metrics(strike=10.0), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertFalse(h.below_cost_basis)
        self.assertFalse(h.net_loss_if_assigned)

    def test_annualized_return_counts_only_the_premium(self):
        """La apreciación hasta el strike es de la acción que ya tienes: la call
        no la crea. Contarla premiaba strikes lejanos con delta ínfima."""
        h = evaluate_for_holding(metrics(strike=15.0, bid=0.20, delta=0.40), 9.65, COST_BASIS_ADJUSTED, 265)
        capital = 9.65 * 200
        esperado = (40.0 / capital) * (365.0 / h.metrics.dte)
        self.assertAlmostEqual(h.annualized_premium_on_cost, esperado, places=6)

    def test_no_delta_means_no_probability_invented(self):
        h = evaluate_for_holding(metrics(delta=None), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertIsNone(h.assignment_probability)
        self.assertIsNotNone(h.annualized_premium_on_cost)  # la prima no depende del delta


class RankingTests(unittest.TestCase):
    def test_appreciation_to_a_far_strike_does_not_win_the_ranking(self):
        """El bug que un test pescó: rankear por valor esperado con la
        apreciación adentro ponía primero una call strike 20 sobre un papel a
        14 con delta 0,05, atribuyéndole $2.070 que la call no crea."""
        lejano = evaluate_for_holding(
            metrics(strike=20.0, bid=0.30, delta=0.05), 9.65, COST_BASIS_ADJUSTED, 265
        )
        cercano = evaluate_for_holding(
            metrics(strike=10.0, bid=0.45, delta=0.45), 9.65, COST_BASIS_ADJUSTED, 265
        )
        orden = rank_for_cycle([lejano, cercano])
        self.assertEqual(orden[0].metrics.strike, 10.0)   # más prima, gana

    def test_recycle_speed_travels_in_the_row_not_in_the_order(self):
        h = evaluate_for_holding(metrics(strike=10.0, delta=0.45), 9.65, COST_BASIS_ADJUSTED, 265)
        self.assertAlmostEqual(h.assignment_probability, 0.45)
        self.assertIsNotNone(h.total_if_assigned)


if __name__ == "__main__":
    unittest.main()
