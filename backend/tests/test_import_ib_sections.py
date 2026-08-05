"""Secciones del Activity Statement que antes se perdían: asignaciones y efectivo.

Los fragmentos de CSV son literales del extracto U7013196_20260101_20260804.csv.
"""

import asyncio
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Option, OptionStatus, OptionStrategy, OptionType,
    Stock, Transaction, TransactionType, User,
)
from app.api.import_ib import (
    CASH_TICKER, ImportRequest, build_parsed_transactions, confirm_import,
    has_ib_code, parse_ib_csv,
)

TRADES_HEADER = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,"
    "T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code\n"
)

# Asignación de F 15MAY26 12 C: el contrato se compra a 0 y las acciones salen al strike.
ASSIGNMENT_CSV = TRADES_HEADER + (
    'Trades,Data,Order,Stocks,USD,F,"2026-05-15, 16:20:00",-100,12,13.4,1200,'
    "-0.04422,-1158,66.901204,-140,A;C\n"
    'Trades,Data,Order,Equity and Index Options,USD,F 15MAY26 12 C,"2026-05-15, 16:20:00",'
    "1,0,1.4,0,0,24.945424,0,140,A;C\n"
)

# MSTR trae el código `IA` (importado ajustado), que contiene la letra A pero no es asignación.
IA_CODE_CSV = TRADES_HEADER + (
    'Trades,Data,Order,Stocks,USD,MSTR,"2026-01-07, 12:58:29",2,163.7571,161.83,-327.5142,'
    "-1,328.5142,0,-3.8542,IA;O\n"
)

CASHFLOW_CSV = (
    "Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount\n"
    "Deposits & Withdrawals,Data,USD,2026-05-11,Disbursement Initiated by Mauricio,-1200\n"
    "Deposits & Withdrawals,Data,USD,2026-03-02,Electronic Fund Transfer,500\n"
    "Deposits & Withdrawals,Data,Total,,,-700\n"
)


def parse(csv_text):
    raw_rows, errors = parse_ib_csv(csv_text)
    parsed, build_errors = build_parsed_transactions(raw_rows, set())
    return parsed, errors + build_errors


class IBCodeTests(unittest.TestCase):
    def test_codigo_a_se_compara_por_token_no_por_substring(self):
        self.assertTrue(has_ib_code("A;C", "A"))
        self.assertTrue(has_ib_code("C;A", "A"))
        self.assertFalse(has_ib_code("IA;O", "A"))
        self.assertFalse(has_ib_code("IM;O;P", "A"))
        self.assertFalse(has_ib_code("", "A"))


class AssignmentParsingTests(unittest.TestCase):
    def test_pata_de_opcion_queda_marcada_como_asignacion(self):
        parsed, errors = parse(ASSIGNMENT_CSV)
        self.assertEqual(errors, [])

        opcion = next(p for p in parsed if p.asset_category != "Stocks")
        self.assertTrue(opcion.es_asignacion)
        # El tipo no cambia: contablemente sigue siendo un cierre a $0.
        self.assertEqual(opcion.tipo, "BUY_CALL")
        self.assertEqual(opcion.total_usd, 0.0)
        self.assertIn("Asignación", opcion.notas)
        # Precio 0 es esperable en una asignación, no una anomalía que advertir.
        self.assertEqual(opcion.advertencia, "")

    def test_pata_de_acciones_sigue_siendo_una_venta_normal(self):
        parsed, _ = parse(ASSIGNMENT_CSV)

        accion = next(p for p in parsed if p.asset_category == "Stocks")
        self.assertEqual(accion.tipo, "SELL_STOCK")
        self.assertEqual(accion.cantidad, 100)
        self.assertEqual(accion.total_usd, 1200.0)
        # No se marca: la que cierra el contrato es la otra pata.
        self.assertFalse(accion.es_asignacion)
        self.assertIn("Asignación", accion.notas)

    def test_codigo_ia_no_se_confunde_con_asignacion(self):
        parsed, _ = parse(IA_CODE_CSV)

        self.assertEqual(len(parsed), 1)
        self.assertFalse(parsed[0].es_asignacion)
        self.assertEqual(parsed[0].notas, "Importado desde IB")


class CashFlowParsingTests(unittest.TestCase):
    def test_retiro_y_deposito_con_ticker_sintetico(self):
        parsed, errors = parse(CASHFLOW_CSV)
        self.assertEqual(errors, [])
        self.assertEqual(len(parsed), 2)  # la fila Total queda fuera

        retiro = next(p for p in parsed if p.tipo == "WITHDRAWAL")
        self.assertEqual(retiro.ticker, CASH_TICKER)
        self.assertEqual(retiro.total_usd, 1200.0)
        self.assertEqual(retiro.cantidad, 0.0)
        self.assertEqual(retiro.fecha, "2026-05-11 00:00:00")

        deposito = next(p for p in parsed if p.tipo == "DEPOSIT")
        self.assertEqual(deposito.total_usd, 500.0)


class AssignmentImportTests(unittest.TestCase):
    """La asignación tiene que dejar la opción en ASSIGNED, no en CLOSED."""

    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.db.add_all([
            User(id=1, email="t@t.cl", username="t", hashed_password="x"),
            Stock(id=1, user_id=1, ticker="F", company_name="Ford", shares=100,
                  average_cost=11.57, total_invested=1157.0, adjusted_cost_basis=11.57,
                  is_active=True),
        ])
        self.db.flush()
        self.db.add(Option(
            id=10, stock_id=1, ticker="F", option_type=OptionType.CALL,
            strategy=OptionStrategy.COVERED_CALL, strike_price=12.0,
            contracts=1, premium_per_contract=0.26, total_premium=26.0,
            expiration_date=datetime(2026, 5, 15), status=OptionStatus.OPEN,
            opened_at=datetime(2026, 5, 8),
        ))
        self.db.commit()
        self.user = self.db.query(User).first()

    def tearDown(self):
        self.db.close()

    def test_confirm_import_marca_la_opcion_como_assigned(self):
        parsed, _ = parse(ASSIGNMENT_CSV)
        asyncio.run(confirm_import(
            body=ImportRequest(transacciones=parsed, omitir_duplicados=False),
            db=self.db, current_user=self.user,
        ))

        opt = self.db.query(Option).filter(Option.id == 10).one()
        self.assertEqual(opt.status, OptionStatus.ASSIGNED)
        # La prima se gana completa: el contrato se cerró a $0.
        self.assertEqual(opt.realized_pnl, 26.0)

        # Y las acciones salieron de verdad de la posición.
        stock = self.db.query(Stock).filter(Stock.ticker == "F").one()
        self.assertEqual(stock.shares, 0)

    def test_cierre_normal_sigue_quedando_closed(self):
        recompra = TRADES_HEADER + (
            'Trades,Data,Order,Equity and Index Options,USD,F 15MAY26 12 C,'
            '"2026-05-15, 09:42:32",1,0.22,0.32,-22,-1.05075,11.948192,-11.102558,10,C\n'
        )
        parsed, _ = parse(recompra)
        asyncio.run(confirm_import(
            body=ImportRequest(transacciones=parsed, omitir_duplicados=False),
            db=self.db, current_user=self.user,
        ))

        opt = self.db.query(Option).filter(Option.id == 10).one()
        self.assertEqual(opt.status, OptionStatus.CLOSED)
        self.assertEqual(opt.realized_pnl, 4.0)


class CashFlowImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(User(id=1, email="t@t.cl", username="t", hashed_password="x"))
        self.db.commit()
        self.user = self.db.query(User).first()

    def tearDown(self):
        self.db.close()

    def test_el_efectivo_no_crea_posiciones(self):
        parsed, _ = parse(CASHFLOW_CSV)
        asyncio.run(confirm_import(
            body=ImportRequest(transacciones=parsed, omitir_duplicados=False),
            db=self.db, current_user=self.user,
        ))

        self.assertEqual(self.db.query(Stock).count(), 0)
        txs = self.db.query(Transaction).all()
        self.assertEqual(len(txs), 2)
        self.assertTrue(all(t.stock_id is None for t in txs))
        self.assertEqual(
            {t.transaction_type for t in txs},
            {TransactionType.DEPOSIT, TransactionType.WITHDRAWAL},
        )


if __name__ == "__main__":
    unittest.main()
