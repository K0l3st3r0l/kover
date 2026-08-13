"""K5 — CC Opportunity, Final Score y la puerta por perfil."""

import unittest
from datetime import date

from app.scanner.covered_calls import compute_covered_call
from app.scanner.scoring import (
    FINAL_MISSING_BOTH,
    FINAL_MISSING_FUNDAMENTAL,
    FINAL_MISSING_MARKET,
    FINAL_OK,
    GATE_DELTA,
    GATE_LOW_FUNDAMENTAL,
    GATE_LOW_MARKET,
    GATE_NO_FUNDAMENTAL,
    GATE_VETO,
    PROFILES,
    build_normalizer,
    compute_cc_opportunity,
    compute_final_score,
    evaluate_gate,
)
from tests.test_covered_calls import make_quote

HOY = date(2026, 8, 13)


def metrics(**overrides):
    quote = make_quote(**{k: v for k, v in overrides.items() if k not in ("stock_ask", "price")})
    return compute_covered_call(
        quote,
        underlying_price=overrides.get("price", 14.0),
        stock_ask=overrides.get("stock_ask", 14.0),
        today=HOY,
    )


class NormalizerTests(unittest.TestCase):
    def test_winsorizing_stops_one_outlier_from_crushing_the_scale(self):
        """Sin winsorizar, un contrato absurdo comprime a todos los demás contra
        el piso y el ranking deja de distinguir entre ellos."""
        normales = [1.0 + i * 0.01 for i in range(100)]   # 1,00 a 1,99
        normalizar = build_normalizer(normales + [500.0], higher_is_better=True)

        # El outlier se recorta a la cota superior, así que los normales siguen
        # repartidos por el rango y no todos pegados en ~0.
        self.assertGreater(normalizar(1.99), 0.8)
        self.assertLess(normalizar(1.0), 0.2)
        self.assertEqual(normalizar(500.0), 1.0)

    def test_winsorizing_cannot_save_a_tiny_population(self):
        """Límite real, no un bug: con 11 valores el outlier ES el 9% de la
        población, así que p95 interpola dentro de él y no hay nada que recortar.
        La winsorización protege cuando el extremo cabe en la cola del 5%; con
        corridas chicas hay que leer el score con desconfianza."""
        normalizar = build_normalizer([1.0 + i * 0.1 for i in range(10)] + [500.0], True)
        self.assertLess(normalizar(1.9), 0.1)

    def test_lower_is_better_inverts(self):
        normalizar = build_normalizer([0.01, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60], False)
        self.assertGreater(normalizar(0.01), normalizar(0.60))

    def test_uniform_population_lands_everyone_at_the_middle(self):
        normalizar = build_normalizer([5.0] * 10, True)
        self.assertEqual(normalizar(5.0), 0.5)

    def test_missing_value_stays_missing(self):
        normalizar = build_normalizer([1.0, 2.0, 3.0], True)
        self.assertIsNone(normalizar(None))

    def test_empty_population_normalizes_to_nothing(self):
        normalizar = build_normalizer([None, None], True)
        self.assertIsNone(normalizar(1.0))


class CcOpportunityTests(unittest.TestCase):
    def test_components_are_explainable_and_weights_sum_to_one(self):
        resultados = compute_cc_opportunity([metrics()])
        componentes = resultados[0].components
        self.assertEqual(len(componentes), 7)
        self.assertAlmostEqual(sum(c.weight for c in componentes), 1.0, places=6)

    def test_delta_fit_uses_an_absolute_band_not_a_percentile(self):
        """Un delta de 0,30 es 0,30 en cualquier mercado. Rankear el ajuste por
        percentil haría que el que peor calza saque 100 si todos calzan mal."""
        malos = [metrics(delta=0.48, occ_symbol=f"X{i}") for i in range(10)]
        resultados = compute_cc_opportunity(malos)
        delta_fit = next(c for c in resultados[0].components if c.name == "delta_fit")
        self.assertLess(delta_fit.normalized, 0.3)   # sigue siendo un mal ajuste

    def test_delta_in_the_ideal_band_scores_full(self):
        resultados = compute_cc_opportunity([metrics(delta=0.28)])
        delta_fit = next(c for c in resultados[0].components if c.name == "delta_fit")
        self.assertEqual(delta_fit.normalized, 1.0)

    def test_score_is_relative_to_the_run(self):
        """El mismo contrato puntúa distinto según contra quién compita: es el
        punto de normalizar contra la corrida."""
        mediocre = metrics(bid=0.20, occ_symbol="M")
        entre_peores = compute_cc_opportunity(
            [mediocre] + [metrics(bid=0.05, occ_symbol=f"P{i}") for i in range(9)]
        )[0].score
        entre_mejores = compute_cc_opportunity(
            [mediocre] + [metrics(bid=1.50, occ_symbol=f"B{i}") for i in range(9)]
        )[0].score
        self.assertGreater(entre_peores, entre_mejores)

    def test_empty_run_returns_empty(self):
        self.assertEqual(compute_cc_opportunity([]), [])


class FinalScoreTests(unittest.TestCase):
    def test_weights_follow_the_plan(self):
        score, estado = compute_final_score(100.0, 100.0, 100.0)
        self.assertEqual(score, 100.0)
        self.assertEqual(estado, FINAL_OK)
        score, _ = compute_final_score(100.0, 0.0, 0.0)
        self.assertEqual(score, 45.0)

    def test_missing_component_yields_none_and_never_renormalizes(self):
        """Renormalizar dejaría a un papel sin fundamentales puntuado solo por
        prima y volatilidad — exactamente la recomendación que el plan prohíbe.
        Ausencia de dato no puede convertirse en score alto por omisión."""
        self.assertEqual(compute_final_score(90.0, None, 80.0), (None, FINAL_MISSING_FUNDAMENTAL))
        self.assertEqual(compute_final_score(90.0, 80.0, None), (None, FINAL_MISSING_MARKET))
        self.assertEqual(compute_final_score(90.0, None, None), (None, FINAL_MISSING_BOTH))

    def test_a_safe_underlying_can_beat_a_fat_premium(self):
        """Es el punto entero del Final Score: 55% del peso está en seguridad."""
        prima_gorda, _ = compute_final_score(cc_opportunity=95.0, financial_safety=30.0, market_safety=5.0)
        papel_sano, _ = compute_final_score(cc_opportunity=45.0, financial_safety=70.0, market_safety=95.0)
        self.assertGreater(papel_sano, prima_gorda)


class GateTests(unittest.TestCase):
    def test_hard_flag_veto_applies_even_in_aggressive_mode(self):
        """La regla explícita del plan. Financial Safety exactamente 0 es la
        marca que deja un REJECT, no un puntaje bajo."""
        for nombre in ("CONSERVADOR", "BALANCEADO", "AGRESIVO"):
            pasa, razones = evaluate_gate(PROFILES[nombre], 0.0, 90.0, 0.02, 0.25, 8)
            self.assertFalse(pasa, nombre)
            self.assertIn(GATE_VETO, razones)

    def test_all_reasons_are_returned_not_just_the_first(self):
        """Fallar por tres motivos no es lo mismo que fallar por uno al borde."""
        pasa, razones = evaluate_gate(PROFILES["CONSERVADOR"], 40.0, 20.0, 0.30, 0.45, 90)
        self.assertFalse(pasa)
        self.assertIn(GATE_LOW_FUNDAMENTAL, razones)
        self.assertIn(GATE_LOW_MARKET, razones)
        self.assertGreaterEqual(len(razones), 4)

    def test_missing_fundamentals_is_not_a_veto_but_still_blocks(self):
        pasa, razones = evaluate_gate(PROFILES["AGRESIVO"], None, 90.0, 0.02, 0.35, 8)
        self.assertFalse(pasa)
        self.assertIn(GATE_NO_FUNDAMENTAL, razones)
        self.assertNotIn(GATE_VETO, razones)

    def test_aggressive_ignores_market_safety_by_design(self):
        pasa, razones = evaluate_gate(PROFILES["AGRESIVO"], 50.0, 1.0, 0.15, 0.35, 8)
        self.assertTrue(pasa)
        self.assertEqual(razones, [])

    def test_a_clean_conservative_candidate_passes(self):
        pasa, razones = evaluate_gate(PROFILES["CONSERVADOR"], 80.0, 70.0, 0.05, 0.25, 10)
        self.assertTrue(pasa)
        self.assertEqual(razones, [])

    def test_delta_outside_the_profile_band_is_rejected(self):
        pasa, razones = evaluate_gate(PROFILES["CONSERVADOR"], 80.0, 70.0, 0.05, 0.42, 10)
        self.assertFalse(pasa)
        self.assertEqual(razones, [GATE_DELTA])


if __name__ == "__main__":
    unittest.main()
