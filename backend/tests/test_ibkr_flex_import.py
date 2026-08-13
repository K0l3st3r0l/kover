"""K7 — sync IBKR Flex: dedupe bidireccional, adaptador y proveedor.

Complementa tests/test_import_ib_sections.py (que cubre el CSV/pegado manual)
sin tocarlo. El caso central es el fix bidireccional del fallback de grupo:
antes solo cubría BD fragmentada + fila entrante agregada; Flex puede
entregar el caso inverso (BD ya agregada + fills fragmentados entrantes) —
ver wiki/projects/kover/bugs/duplicado-btbt-import-manual-csv.md.
"""

import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Stock, User
from app.providers.base import BrokerCashTransaction, BrokerExecution, BrokerPositionLot, ProviderError
from app.providers.ibkr_flex import POLL_BACKOFF_SECONDS, FlexCooldownError, IbkrFlexBrokerProvider
import app.providers.ibkr_flex as ibkr_flex_module
from app.api.import_ib import (
    broker_cash_to_raw_rows,
    broker_execution_to_raw_row,
    broker_executions_to_raw_rows,
    build_parsed_transactions,
    build_position_reconciliation,
)


# ─── Dedupe bidireccional (el caso central) ────────────────────────────────────

class GroupDedupeBidirectionalTests(unittest.TestCase):
    def _fragmented_rows(self, quantities_and_totals):
        rows = []
        for i, (qty, total) in enumerate(quantities_and_totals, start=1):
            rows.append({
                "line": i, "section": "Trades", "asset_category": "Equity and Index Options",
                "symbol": "BTBT  260511C00002500", "datetime_str": "2026-05-11 16:20:00",
                "quantity": -qty, "t_price": round(total / (qty * 100), 4) if qty else 0.0,
                "proceeds": total, "comm_fee": 0.0, "description": "", "code": "",
            })
        return rows

    def test_existing_aggregated_vs_incoming_fragmented_marks_all_as_duplicate(self):
        """Caso real BTBT: BD tiene 1 fila agregada (4 contratos/$40), Flex entrega
        3 fills fragmentados (2+1+1) que suman lo mismo. Antes del fix, ninguna se
        marcaba duplicada porque el fallback exigía group['count'] > 1 del lado BD."""
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 4.0, "total_sum": 40.0, "count": 1}}
        raw_rows = self._fragmented_rows([(2, 20.0), (1, 10.0), (1, 10.0)])

        parsed, errors = build_parsed_transactions(raw_rows, set(), None, existing_groups)

        self.assertEqual(errors, [])
        self.assertEqual(len(parsed), 3)
        for p in parsed:
            self.assertTrue(p.duplicado)
            self.assertEqual(p.duplicado_metodo, "grupo_agregado")

    def test_existing_fragmented_vs_incoming_aggregated_regression(self):
        """El caso original (ya cubierto antes del fix) sigue funcionando."""
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 2.0, "total_sum": 20.0, "count": 2}}
        raw_rows = self._fragmented_rows([(2, 20.0)])

        parsed, _ = build_parsed_transactions(raw_rows, set(), None, existing_groups)
        self.assertTrue(parsed[0].duplicado)
        self.assertEqual(parsed[0].duplicado_metodo, "grupo_agregado")

    def test_sums_that_dont_match_are_not_marked_duplicate(self):
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 3.0, "total_sum": 30.0, "count": 1}}
        raw_rows = self._fragmented_rows([(2, 20.0), (2, 20.0)])  # suma 4/$40, no calza 3/$30

        parsed, _ = build_parsed_transactions(raw_rows, set(), None, existing_groups)
        self.assertTrue(all(not p.duplicado for p in parsed))

    def test_known_limitation_coincidental_sum_match(self):
        """Limitación documentada, no un bug a resolver acá: si un fragmento de una
        orden ya existente + una orden nueva real coinciden en (ticker,fecha,tipo) y
        su suma combinada calza por coincidencia con un grupo ya en BD, ambas quedan
        marcadas duplicadas — incluida la genuinamente nueva. Mitigado por
        build_position_reconciliation, no por el dedupe. Ver plan K7."""
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 3.0, "total_sum": 30.0, "count": 1}}
        raw_rows = self._fragmented_rows([(2, 20.0), (1, 10.0)])  # fragmento (2/$20) + orden nueva (1/$10)

        parsed, _ = build_parsed_transactions(raw_rows, set(), None, existing_groups)
        self.assertTrue(all(p.duplicado for p in parsed))

    def test_incoming_batch_with_extra_new_order_still_marks_the_aggregate(self):
        """El lote entrante trae la fila agregada de una orden YA en BD (fragmentada)
        más una orden genuinamente nueva del mismo ticker/fecha/tipo. Comparar suma
        entrante contra suma de BD deja pasar el duplicado: 4/$40 + 1/$10 = 5/$50 no
        calza con 4/$40 y ninguna fila queda marcada. La comparación fila-a-grupo sí
        lo pesca, sin marcar de más la orden nueva."""
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 4.0, "total_sum": 40.0, "count": 2}}
        raw_rows = self._fragmented_rows([(4, 40.0), (1, 10.0)])

        parsed, _ = build_parsed_transactions(raw_rows, set(), None, existing_groups)

        agregada = next(p for p in parsed if p.cantidad == 4.0)
        nueva = next(p for p in parsed if p.cantidad == 1.0)
        self.assertTrue(agregada.duplicado)
        self.assertEqual(agregada.duplicado_metodo, "grupo_agregado")
        self.assertFalse(nueva.duplicado)

    def test_rows_already_caught_by_hash_still_count_toward_the_group_sum(self):
        """BD tiene la orden agregada (4/$40) más otra fila suelta (3/$30); Flex trae
        los fills fragmentados de la primera (2+2) y la segunda idéntica. La idéntica
        la pesca el hash exacto, pero sigue sumando para el match de grupo — el grupo
        de BD también la incluye. Sacarla de un solo lado descuadraría el match y los
        fragmentos se importarían duplicados."""
        existing_groups = {("BTBT", "2026-05-11", "SELL_CALL"): {"qty_sum": 7.0, "total_sum": 70.0, "count": 2}}
        existing_hashes = {("BTBT", "2026-05-11", "SELL_CALL", 30.0, 3.0)}
        raw_rows = self._fragmented_rows([(2, 20.0), (2, 20.0), (3, 30.0)])

        parsed, _ = build_parsed_transactions(raw_rows, existing_hashes, None, existing_groups)

        self.assertTrue(all(p.duplicado for p in parsed))
        self.assertEqual(
            sorted(p.duplicado_metodo for p in parsed),
            ["grupo_agregado", "grupo_agregado", "hash_exacto"],
        )


# ─── Adaptador: BrokerExecution -> raw_row ─────────────────────────────────────

def make_execution(**overrides):
    defaults = dict(
        external_id="1", account_id="U7013196", symbol="AAPL", asset_category="STK",
        side="BUY", quantity=10.0, price=100.0, proceeds=-1000.0, commission=-1.0,
        executed_at_utc=datetime(2026, 5, 15, 13, 30, tzinfo=timezone.utc),
        source_timezone="America/New_York", original_timestamp="20260515;093000",
        codes=[],
    )
    defaults.update(overrides)
    return BrokerExecution(**defaults)


class BrokerExecutionAdapterTests(unittest.TestCase):
    def test_late_day_execution_keeps_same_civil_date_across_utc_midnight(self):
        # 20:15 ET cruza la medianoche UTC (00:15 o 01:15 UTC del día siguiente
        # según horario de verano). La fecha civil que debe quedar es la de ET.
        local_dt = datetime(2026, 5, 15, 20, 15, tzinfo=ZoneInfo("America/New_York"))
        execution = make_execution(executed_at_utc=local_dt.astimezone(timezone.utc))

        row = broker_execution_to_raw_row(execution, 1)

        self.assertEqual(row["datetime_str"], "2026-05-15 20:15:00")

    def test_opt_info_shortcut_avoids_regex_reparse(self):
        execution = make_execution(
            symbol="no-parseable-por-regex", asset_category="OPT", side="SELL", quantity=1.0,
            underlying="BTBT", strike=2.5, right="C", expiration=date(2026, 5, 22),
        )
        row = broker_execution_to_raw_row(execution, 1)
        self.assertEqual(row["opt_info"], ("BTBT", "C", 2.5, "2026-05-22"))

        # Si build_parsed_transactions hubiera intentado reparsear el symbol con
        # regex, esta fila habría fallado con "símbolo de opción no reconocido".
        parsed, errors = build_parsed_transactions([row], set())
        self.assertEqual(errors, [])
        self.assertEqual(parsed[0].ticker, "BTBT")

    def test_cancellation_code_is_dropped(self):
        execution = make_execution(codes=["Ca"])
        self.assertIsNone(broker_execution_to_raw_row(execution, 1))

    def test_dropped_cancellations_leave_no_gaps_in_line_numbers(self):
        """preview-flex renumera las filas de efectivo desde el "line" más alto de
        los trades. Si los trades dejaran huecos (numerando sobre las ejecuciones en
        vez de sobre las filas que quedan), dos filas terminarían con el mismo ib_row
        y "Forzar esta fila" desmarcaría las dos: un dividendo forzado arrastraría un
        trade sin relación, que se importaría duplicado en silencio."""
        executions = [
            make_execution(external_id="1"),
            make_execution(external_id="2", codes=["Ca"]),
            make_execution(external_id="3", codes=["Ca"]),
            make_execution(external_id="4"),
            make_execution(external_id="5"),
        ]
        trade_rows, _ = broker_executions_to_raw_rows(executions)

        lines = [r["line"] for r in trade_rows]
        self.assertEqual(lines, [1, 2, 3])

        cash_rows, _ = broker_cash_to_raw_rows([
            BrokerCashTransaction(external_id="c1", account_id="U1", type="Dividends",
                                  symbol="MSFT", amount=12.0, settle_date=date(2026, 5, 20),
                                  executed_at_utc=None),
        ])
        offset = max((r["line"] for r in trade_rows), default=0)
        for i, row in enumerate(cash_rows, start=1):
            row["line"] = offset + i

        all_lines = [r["line"] for r in trade_rows + cash_rows]
        self.assertEqual(len(all_lines), len(set(all_lines)))

    def test_expiration_produces_option_expiry_without_spurious_price_warning(self):
        execution = make_execution(
            symbol="BTBT  260327C00002000", asset_category="OPT", side="BUY",
            quantity=3.0, price=0.0, proceeds=0.0, commission=0.0, codes=["Ep"],
            underlying="BTBT", strike=2.0, right="C", expiration=date(2026, 3, 27),
        )
        row = broker_execution_to_raw_row(execution, 1)
        self.assertEqual(row["section"], "OptionExpiry")

        parsed, errors = build_parsed_transactions([row], set())
        self.assertEqual(errors, [])
        self.assertEqual(parsed[0].tipo, "OPTION_EXPIRY")
        # Precio 0 es esperable en una expiración, no una anomalía a advertir
        # (mismo criterio que ya existe para asignaciones).
        self.assertEqual(parsed[0].advertencia, "")

    def test_assignment_via_broker_execution_matches_csv_behavior(self):
        stock_leg = make_execution(
            external_id="1", symbol="F", asset_category="STK", side="SELL",
            quantity=100.0, price=12.0, proceeds=1200.0, commission=-0.04422, codes=["A", "C"],
        )
        option_leg = make_execution(
            external_id="2", symbol="F     260515C00012000", asset_category="OPT", side="BUY",
            quantity=1.0, price=0.0, proceeds=0.0, commission=0.0, codes=["A", "C"],
            underlying="F", strike=12.0, right="C", expiration=date(2026, 5, 15),
        )
        rows, _ = broker_executions_to_raw_rows([stock_leg, option_leg])
        parsed, errors = build_parsed_transactions(rows, set())

        self.assertEqual(errors, [])
        opcion = next(p for p in parsed if p.asset_category != "Stocks")
        self.assertTrue(opcion.es_asignacion)
        self.assertEqual(opcion.tipo, "BUY_CALL")

        accion = next(p for p in parsed if p.asset_category == "Stocks")
        self.assertEqual(accion.tipo, "SELL_STOCK")
        self.assertFalse(accion.es_asignacion)

    def test_sell_side_signs_quantity_negative_and_commission_is_inverted(self):
        execution = make_execution(side="SELL", quantity=2.0, commission=-1.40408)
        row = broker_execution_to_raw_row(execution, 1)
        self.assertEqual(row["quantity"], -2.0)
        self.assertAlmostEqual(row["comm_fee"], 1.40408)


# ─── Adaptador: BrokerCashTransaction -> raw_row ───────────────────────────────

def make_cash(**overrides):
    defaults = dict(
        external_id="1", account_id="U7013196", type="Dividends", symbol="KHC",
        amount=4.0, settle_date=date(2025, 12, 26), executed_at_utc=None, description=None,
    )
    defaults.update(overrides)
    return BrokerCashTransaction(**defaults)


class BrokerCashAdapterTests(unittest.TestCase):
    def test_dividend_maps_to_dividends_section(self):
        rows, errors = broker_cash_to_raw_rows([make_cash()])
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["section"], "Dividends")
        self.assertEqual(rows[0]["proceeds"], 4.0)

    def test_payment_in_lieu_also_maps_to_dividends_with_distinct_note(self):
        rows, _ = broker_cash_to_raw_rows([make_cash(type="Payment In Lieu Of Dividends")])
        self.assertEqual(rows[0]["section"], "Dividends")
        self.assertIn("sustitutivo", rows[0]["description"])

    def test_withholding_tax_sign_is_not_double_inverted(self):
        # El adaptador NO invierte el signo — build_parsed_transactions ya hace
        # -raw["proceeds"]. Invertir en ambos lados dejaría el monto con signo
        # incorrecto en silencio.
        rows, _ = broker_cash_to_raw_rows([make_cash(type="Withholding Tax", amount=-1.2, symbol="F")])
        parsed, _ = build_parsed_transactions(rows, set())
        self.assertEqual(parsed[0].total_usd, 1.2)

    def test_unknown_type_falls_back_to_generic_fee(self):
        rows, _ = broker_cash_to_raw_rows([make_cash(type="AF", amount=-1.5, symbol=None)])
        self.assertEqual(rows[0]["section"], "Fee")

    def test_missing_settle_date_is_an_error_not_a_silent_drop(self):
        rows, errors = broker_cash_to_raw_rows([make_cash(settle_date=None)])
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)


# ─── Reconciliación de posiciones ──────────────────────────────────────────────

class PositionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(User(id=1, email="t@t.cl", username="t", hashed_password="x"))
        self.db.add(Stock(id=1, user_id=1, ticker="SMR", company_name="NuScale", shares=10,
                           average_cost=8.66, total_invested=86.6, adjusted_cost_basis=8.66,
                           is_active=True))
        self.db.commit()
        self.user = self.db.query(User).first()

    def tearDown(self):
        self.db.close()

    def test_matching_shares_produce_no_discrepancy(self):
        lots = [BrokerPositionLot(account_id="U1", symbol="SMR", asset_category="STK",
                                   quantity=10.0, cost_basis_price=8.66, cost_basis_money=86.6, open_date=None)]
        self.assertEqual(build_position_reconciliation(self.db, self.user, lots), [])

    def test_mismatched_shares_are_reported(self):
        lots = [BrokerPositionLot(account_id="U1", symbol="SMR", asset_category="STK",
                                   quantity=15.0, cost_basis_price=8.66, cost_basis_money=129.9, open_date=None)]
        result = build_position_reconciliation(self.db, self.user, lots)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ticker"], "SMR")
        self.assertEqual(result[0]["diferencia"], 5.0)

    def test_option_lots_are_ignored(self):
        # El lote OPT no debe sumarse ni contarse como si fueran acciones — con el
        # lote STK que sí calza (10), el resultado debe seguir sin discrepancias.
        lots = [
            BrokerPositionLot(account_id="U1", symbol="SMR", asset_category="STK",
                               quantity=10.0, cost_basis_price=8.66, cost_basis_money=86.6, open_date=None),
            BrokerPositionLot(account_id="U1", symbol="SMR", asset_category="OPT",
                               quantity=-2.0, cost_basis_price=None, cost_basis_money=None, open_date=None),
        ]
        self.assertEqual(build_position_reconciliation(self.db, self.user, lots), [])


# ─── Proveedor IBKR Flex (HTTP mockeado, nunca contra Flex real) ───────────────

class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


SEND_SUCCESS = FakeResponse(
    "<FlexStatementResponse><Status>Success</Status>"
    "<ReferenceCode>REF123</ReferenceCode><Url>https://x</Url></FlexStatementResponse>"
)


def statement_generating():
    return FakeResponse(
        "<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
        "<ErrorMessage>Statement generating. Please try again shortly.</ErrorMessage>"
        "</FlexStatementResponse>"
    )


def statement_ready():
    return FakeResponse(
        '<FlexQueryResponse queryName="q" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U1"><Trades/></FlexStatement>'
        "</FlexStatements></FlexQueryResponse>"
    )


def statement_fail():
    return FakeResponse(
        "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1003</ErrorCode>"
        "<ErrorMessage>Invalid request</ErrorMessage></FlexStatementResponse>"
    )


SEND_COOLDOWN = FakeResponse(
    "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1001</ErrorCode>"
    "<ErrorMessage>Statement could not be generated at this time. Please try again shortly.</ErrorMessage>"
    "</FlexStatementResponse>"
)


class IbkrFlexProviderTests(unittest.TestCase):
    def _provider(self, responses):
        session = FakeSession(responses)
        provider = IbkrFlexBrokerProvider(
            token="TESTTOKEN123", query_id_activity="Q1", query_id_trades="Q2", session=session
        )
        return provider, session

    def _without_sleeping(self, fn):
        orig_sleep = ibkr_flex_module.time.sleep
        ibkr_flex_module.time.sleep = lambda s: None
        try:
            return fn()
        finally:
            ibkr_flex_module.time.sleep = orig_sleep

    def test_retries_on_1019_then_succeeds(self):
        provider, session = self._provider([SEND_SUCCESS, statement_generating(), statement_ready()])
        xml = self._without_sleeping(provider._fetch_activity_xml)
        self.assertIn("FlexQueryResponse", xml)
        self.assertEqual(len(session.calls), 3)

    def test_gives_up_after_exhausting_backoff(self):
        responses = [SEND_SUCCESS] + [statement_generating() for _ in range(len(POLL_BACKOFF_SECONDS) + 1)]
        provider, _ = self._provider(responses)
        with self.assertRaises(ProviderError):
            self._without_sleeping(provider._fetch_activity_xml)

    def test_status_fail_raises_immediately_never_treated_as_no_data(self):
        provider, session = self._provider([SEND_SUCCESS, statement_fail()])
        with self.assertRaises(ProviderError):
            self._without_sleeping(provider._fetch_activity_xml)
        self.assertEqual(len(session.calls), 2)  # no reintenta un Fail real

    def test_cache_avoids_second_round_trip_within_ttl(self):
        provider, session = self._provider([SEND_SUCCESS, statement_ready()])
        xml1 = provider._fetch_activity_xml()
        xml2 = provider._fetch_activity_xml()
        self.assertEqual(xml1, xml2)
        self.assertEqual(len(session.calls), 2)

    def test_token_never_leaks_into_error_message(self):
        class BoomSession:
            def get(self, url, params=None, timeout=None):
                raise requests.exceptions.ConnectionError(
                    f"Max retries exceeded with url: /x?t={params['t']}&q={params['q']}"
                )

        provider = IbkrFlexBrokerProvider(
            token="SUPERSECRETTOKEN123", query_id_activity="Q1", session=BoomSession()
        )
        with self.assertRaises(ProviderError) as ctx:
            provider._fetch_activity_xml()
        self.assertNotIn("SUPERSECRETTOKEN123", str(ctx.exception))

    def test_probe_validates_config_without_network_calls(self):
        provider = IbkrFlexBrokerProvider(
            token="T", query_id_activity="Q1", query_id_trades="Q2", session=FakeSession([])
        )
        self.assertTrue(provider.probe()["configured"])

    def test_probe_fails_fast_without_token(self):
        provider = IbkrFlexBrokerProvider(token="", query_id_activity="Q1", session=FakeSession([]))
        with self.assertRaises(ProviderError):
            provider.probe()

    def test_cooldown_1001_is_its_own_error_type(self):
        """El 1001 no es una falla del sync sino el límite de IBKR entre peticiones
        de la misma query. Se distingue del resto para que el endpoint responda 429
        y la UI no invite a reintentar, que es lo único que garantiza otro 1001."""
        provider, session = self._provider([SEND_COOLDOWN])
        with self.assertRaises(FlexCooldownError) as ctx:
            provider._fetch_activity_xml()

        self.assertIsInstance(ctx.exception, ProviderError)  # sigue siendo manejable como tal
        self.assertEqual(len(session.calls), 1)  # ni siquiera llega a GetStatement
        self.assertNotIn("TESTTOKEN123", str(ctx.exception))

    def test_budget_stops_the_polling_before_the_proxy_cuts(self):
        """Con el backoff completo y timeouts de 60s el peor caso pasaba los 8
        minutos: Cloudflare cortaba en ~100s y el usuario veía un 524 con el backend
        todavía trabajando. El presupuesto total corta antes, con un error propio."""
        responses = [SEND_SUCCESS] + [statement_generating() for _ in range(len(POLL_BACKOFF_SECONDS) + 1)]
        provider, session = self._provider(responses)

        orig = ibkr_flex_module.STATEMENT_TOTAL_BUDGET_SECONDS
        ibkr_flex_module.STATEMENT_TOTAL_BUDGET_SECONDS = 0
        try:
            with self.assertRaises(ProviderError) as ctx:
                provider._fetch_activity_xml()
        finally:
            ibkr_flex_module.STATEMENT_TOTAL_BUDGET_SECONDS = orig

        self.assertNotIsInstance(ctx.exception, FlexCooldownError)
        self.assertEqual(len(session.calls), 1)  # SendRequest y nada más: no gastó el backoff


class EndpointShapeTests(unittest.TestCase):
    def test_preview_flex_is_sync_so_it_never_blocks_the_event_loop(self):
        """`async def` + requests/time.sleep congela el backend entero mientras dura
        el sync (uvicorn corre con un solo worker). Siendo sync, FastAPI la despacha
        al threadpool. Es una propiedad del endpoint, no un detalle de estilo."""
        import asyncio
        from app.api.import_ib import preview_flex_import

        self.assertFalse(asyncio.iscoroutinefunction(preview_flex_import))


if __name__ == "__main__":
    unittest.main()
