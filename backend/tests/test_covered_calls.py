"""K4 — cadenas CBOE y métricas de covered call.

El provider se prueba con JSON fijo, nunca contra CBOE real: un test que
depende de la red falla por razones que no son el código.
"""

import unittest
from datetime import date, datetime, timezone

from app.providers.base import OptionQuote, Provenance, ProviderError
from app.providers.cboe_chains import CboeChainsProvider, parse_osi_symbol
from app.scanner.covered_calls import (
    ChainFilter,
    compute_covered_call,
    compute_liquidity_score,
    evaluate_chain,
    pick_best,
)


class OsiParsingTests(unittest.TestCase):
    def test_parses_a_normal_symbol(self):
        self.assertEqual(parse_osi_symbol("F260814C00005000"), ("F", date(2026, 8, 14), "C", 5.0))

    def test_parses_a_ticker_with_a_dot(self):
        """BRK.B, BF.B y compañía. Una clase [A-Z0-9]{1,6} para la raíz los
        descartaba en silencio; el sufijo es de largo fijo, así que se parsea
        por posición."""
        self.assertEqual(
            parse_osi_symbol("BRK.B260814P00450000"), ("BRK.B", date(2026, 8, 14), "P", 450.0)
        )

    def test_strike_is_in_thousandths(self):
        _root, _exp, _right, strike = parse_osi_symbol("MARA260821C00010500")
        self.assertEqual(strike, 10.5)

    def test_rejects_garbage(self):
        self.assertIsNone(parse_osi_symbol("NOPE"))
        self.assertIsNone(parse_osi_symbol("F260814X00005000"))   # right inválido
        self.assertIsNone(parse_osi_symbol("260814C00005000"))    # sin raíz


def make_quote(**overrides) -> OptionQuote:
    defaults = dict(
        underlying="F", expiration=date(2026, 9, 18), strike=15.0, right="C",
        bid=0.20, ask=0.22, last=0.21, volume=100, open_interest=1500,
        implied_volatility=0.30,
        provenance=Provenance(
            source="cboe_delayed_quotes",
            as_of=datetime(2026, 8, 13, 14, 0, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 13, 14, 1, tzinfo=timezone.utc),
        ),
        occ_symbol="F260918C00015000", delta=0.30, greeks_source="CBOE_REPORTED",
    )
    defaults.update(overrides)
    return OptionQuote(**defaults)


class CoveredCallMetricsTests(unittest.TestCase):
    HOY = date(2026, 8, 13)

    def test_uses_stock_ask_and_call_bid_not_mid(self):
        """La convención del proyecto: se compra al ask y se vende al bid. Usar
        mid infla el ranking de forma sistemáticamente optimista, que es la peor
        dirección posible para un error."""
        m = compute_covered_call(make_quote(), underlying_price=14.0, stock_ask=14.10, today=self.HOY)
        self.assertEqual(m.stock_ask, 14.10)
        self.assertEqual(m.call_bid, 0.20)
        self.assertAlmostEqual(m.premium_total, 20.0)
        self.assertAlmostEqual(m.premium_yield, 20.0 / 1410.0, places=6)

    def test_return_if_assigned_includes_the_move_to_the_strike(self):
        m = compute_covered_call(make_quote(), underlying_price=14.0, stock_ask=14.0, today=self.HOY)
        # (15.00 - 14.00) * 100 + 20 = 120 sobre 1400
        self.assertAlmostEqual(m.return_if_assigned, 120.0 / 1400.0, places=6)

    def test_return_if_assigned_is_negative_when_the_call_is_below_cost(self):
        """Vender una call bajo el costo de la acción es aceptar una pérdida a
        cambio de prima. El número tiene que mostrarlo, no esconderlo en un abs()."""
        m = compute_covered_call(
            make_quote(strike=12.0), underlying_price=14.0, stock_ask=14.0, today=self.HOY
        )
        self.assertLess(m.return_if_assigned, 0)

    def test_no_bid_is_not_an_opportunity(self):
        self.assertIsNone(compute_covered_call(make_quote(bid=None), 14.0, 14.0, self.HOY))
        self.assertIsNone(compute_covered_call(make_quote(bid=0.0), 14.0, 14.0, self.HOY))

    def test_puts_are_ignored(self):
        self.assertIsNone(compute_covered_call(make_quote(right="P"), 14.0, 14.0, self.HOY))

    def test_expired_contract_is_ignored(self):
        self.assertIsNone(
            compute_covered_call(make_quote(expiration=date(2026, 8, 1)), 14.0, 14.0, self.HOY)
        )

    def test_breakeven_and_downside_protection_agree(self):
        m = compute_covered_call(make_quote(), underlying_price=14.0, stock_ask=14.0, today=self.HOY)
        self.assertAlmostEqual(m.breakeven, 13.80)
        self.assertAlmostEqual(m.downside_protection, 0.20 / 14.0, places=6)

    def test_annualization_scales_by_dte(self):
        corta = compute_covered_call(
            make_quote(expiration=date(2026, 8, 20)), 14.0, 14.0, self.HOY
        )
        larga = compute_covered_call(
            make_quote(expiration=date(2026, 10, 16)), 14.0, 14.0, self.HOY
        )
        # Misma prima, menos días: el anualizado tiene que ser mayor.
        self.assertGreater(corta.annualized_premium_yield, larga.annualized_premium_yield)


class LiquidityScoreTests(unittest.TestCase):
    def test_tight_spread_and_deep_book_scores_high(self):
        score, _ = compute_liquidity_score(0.02, 1000, 5000)
        self.assertEqual(score, 100.0)

    def test_wide_spread_drags_the_score(self):
        apretado, _ = compute_liquidity_score(0.02, 100, 1000)
        ancho, _ = compute_liquidity_score(0.30, 100, 1000)
        self.assertGreater(apretado, ancho)

    def test_missing_component_renormalizes_instead_of_counting_as_zero(self):
        """Ausencia de dato no es evidencia de iliquidez — misma regla que el
        score fundamental. Sin volumen, el resto se renormaliza."""
        con_volumen, _ = compute_liquidity_score(0.02, 1000, 5000)
        sin_volumen, componentes = compute_liquidity_score(0.02, None, 5000)
        self.assertEqual(sin_volumen, con_volumen)
        volumen = next(c for c in componentes if c["name"] == "volumen")
        self.assertIsNone(volumen["normalized"])

    def test_no_data_at_all_yields_none_not_zero(self):
        score, _ = compute_liquidity_score(None, None, None)
        self.assertIsNone(score)


class ChainEvaluationTests(unittest.TestCase):
    HOY = date(2026, 8, 13)

    def _chain(self):
        return [
            make_quote(strike=15.0, delta=0.30, occ_symbol="A"),                       # pasa
            make_quote(strike=13.0, delta=0.70, occ_symbol="B"),                       # ITM
            make_quote(strike=16.0, delta=0.05, occ_symbol="C"),                       # delta baja
            make_quote(strike=15.5, delta=0.25, bid=0.10, ask=0.40, occ_symbol="D"),   # spread ancho
            make_quote(strike=15.0, delta=0.30, open_interest=1, occ_symbol="E"),      # OI bajo
            make_quote(strike=15.0, right="P", occ_symbol="G"),                        # put
            make_quote(strike=15.0, expiration=date(2027, 6, 18), occ_symbol="H"),     # DTE largo
        ]

    def test_each_filter_is_counted_so_zero_candidates_is_explainable(self):
        """'0 candidatos' no puede ser indistinguible de 'la cadena no llegó' —
        el mismo problema que un preview vacío en el import de IBKR."""
        candidatos, descartes = evaluate_chain(self._chain(), 14.0, self.HOY)

        self.assertEqual([c.occ_symbol for c in candidatos], ["A"])
        self.assertEqual(descartes["itm"], 1)
        self.assertEqual(descartes["delta_fuera_de_banda"], 1)
        self.assertEqual(descartes["spread_ancho"], 1)
        self.assertEqual(descartes["open_interest_bajo"], 1)
        self.assertEqual(descartes["no_call"], 1)
        self.assertEqual(descartes["fuera_de_dte"], 1)

    def test_filter_is_configurable(self):
        filtro = ChainFilter(min_delta=0.01, max_delta=0.99, min_open_interest=0, max_spread_pct=1.0)
        candidatos, _ = evaluate_chain(self._chain(), 14.0, self.HOY, filtro=filtro)
        self.assertGreater(len(candidatos), 1)


class PickBestTests(unittest.TestCase):
    HOY = date(2026, 8, 13)

    def test_three_readings_of_the_same_chain(self):
        prima_alta = compute_covered_call(
            make_quote(strike=14.5, bid=0.50, ask=0.70, open_interest=20, volume=5, occ_symbol="PRIMA"),
            14.0, 14.0, self.HOY,
        )
        liquido = compute_covered_call(
            make_quote(strike=14.5, bid=0.40, ask=0.41, open_interest=9000, volume=3000, occ_symbol="LIQ"),
            14.0, 14.0, self.HOY,
        )
        lejano = compute_covered_call(
            make_quote(strike=18.0, bid=0.10, ask=0.12, occ_symbol="LEJOS"),
            14.0, 14.0, self.HOY,
        )
        mejores = pick_best([prima_alta, liquido, lejano])

        self.assertEqual(mejores["premium"].occ_symbol, "PRIMA")   # mayor anualizado crudo
        self.assertEqual(mejores["balanced"].occ_symbol, "LIQ")    # castigado por liquidez
        self.assertEqual(mejores["upside"].occ_symbol, "LEJOS")    # mayor recorrido al strike

    def test_empty_chain_returns_nones_not_an_exception(self):
        self.assertEqual(pick_best([]), {"balanced": None, "premium": None, "upside": None})


# ─── Provider con HTTP fijo ───────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x"

    def json(self):
        if self._payload is None:
            raise ValueError("no es JSON")
        return self._payload


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, timeout=None, headers=None):
        self.calls.append(url)
        return self._response


CHAIN_PAYLOAD = {
    "timestamp": "2026-08-13 14:32:39",
    "data": {
        "symbol": "F",
        "current_price": 13.98,
        "bid": 13.97,
        "ask": 13.99,
        "iv30": 0.31,
        "options": [
            {"option": "F260918C00015000", "bid": 0.20, "ask": 0.22, "iv": 0.30,
             "open_interest": 1500, "volume": 100, "delta": 0.30, "last_trade_price": 0.21},
            {"option": "F260918P00013000", "bid": 0.15, "ask": 0.17, "iv": 0.33,
             "open_interest": 900, "volume": 40, "delta": -0.25, "last_trade_price": 0.16},
            {"option": "BASURA", "bid": 1.0},
        ],
    },
}


class CboeChainsProviderTests(unittest.TestCase):
    def test_parses_chain_and_underlying_from_the_same_payload(self):
        provider = CboeChainsProvider(session=FakeSession(FakeResponse(CHAIN_PAYLOAD)))
        quotes, underlying = provider.get_chain("F")

        self.assertEqual(len(quotes), 2)  # la fila basura se descarta sin reventar
        self.assertEqual(underlying.price, 13.98)
        self.assertEqual(underlying.ask, 13.99)

    def test_greeks_are_reported_not_recalculated(self):
        """CBOE los entrega; marcarlos BS_CALCULATED sería mentir sobre la procedencia."""
        provider = CboeChainsProvider(session=FakeSession(FakeResponse(CHAIN_PAYLOAD)))
        quotes, _ = provider.get_chain("F")
        self.assertEqual(quotes[0].greeks_source, "CBOE_REPORTED")
        self.assertEqual(quotes[0].delta, 0.30)

    def test_timestamp_travels_as_provenance(self):
        provider = CboeChainsProvider(session=FakeSession(FakeResponse(CHAIN_PAYLOAD)))
        quotes, underlying = provider.get_chain("F")
        self.assertEqual(quotes[0].provenance.as_of, datetime(2026, 8, 13, 14, 32, 39, tzinfo=timezone.utc))
        self.assertEqual(quotes[0].provenance.source, "cboe_delayed_quotes")
        self.assertEqual(underlying.as_of, quotes[0].provenance.as_of)

    def test_404_is_a_confirmed_negative_not_a_retryable_failure(self):
        provider = CboeChainsProvider(session=FakeSession(FakeResponse(None, status_code=404)))
        with self.assertRaises(ProviderError) as ctx:
            provider.get_chain("NOPE")
        self.assertFalse(ctx.exception.retryable)

    def test_empty_chain_raises_instead_of_returning_nothing(self):
        payload = {"timestamp": "2026-08-13 14:32:39", "data": {"current_price": 10.0, "options": []}}
        provider = CboeChainsProvider(session=FakeSession(FakeResponse(payload)))
        with self.assertRaises(ProviderError):
            provider.get_chain("F")


if __name__ == "__main__":
    unittest.main()
