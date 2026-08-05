"""Saldo de caja derivado y las secciones Fees / Withholding Tax.

El test que importa es `test_saldo_derivado_reproduce_el_extracto`: parte del
Starting Cash de IB, suma los flujos del período y tiene que llegar al Ending Cash
del mismo extracto. Si eso cuadra al centavo, la contabilidad está completa.
"""

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Transaction, TransactionType, User
from app.services.cash_ledger import compute_cash_balance
from app.api.import_ib import build_parsed_transactions, parse_ib_csv

FEES_CSV = (
    "Fees,Header,Subtitle,Currency,Date,Description,Amount\n"
    "Fees,Data,Other Fees,USD,2026-02-06,M******IN:OPRA NP L1 for Feb 2026,-1.5\n"
    "Fees,Data,Other Fees,USD,2026-03-03,Cancel[M******IN:OPRA NP L1] FOR FEB 2026,1.5\n"
    "Fees,Data,Total,,,,-9\n"
)

WITHHOLDING_CSV = (
    "Withholding Tax,Header,Currency,Date,Description,Amount,Code\n"
    "Withholding Tax,Data,USD,2026-06-01,F(US3453708600) Payment in Lieu of Dividend - US Tax,-4.5,\n"
    "Withholding Tax,Data,Total,,,-4.5,\n"
)

# La recompra del BTBT trae comisión positiva: IB devolvió, no cobró.
COMMISSION_REBATE_CSV = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,"
    "T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code\n"
    'Trades,Data,Order,Equity and Index Options,USD,BTBT 22MAY26 2.5 C,"2026-05-11, 13:26:17",'
    "-4,0.1,0.125,40,-2.806984,-37.193016,0,-10,O;P\n"
    'Trades,Data,Order,Equity and Index Options,USD,BTBT 22MAY26 2.5 C,"2026-05-22, 13:34:19",'
    "4,0.01,0,-4,0.727,37.193016,33.920016,-4,C\n"
)


def parse(csv_text):
    raw_rows, errors = parse_ib_csv(csv_text)
    parsed, build_errors = build_parsed_transactions(raw_rows, set())
    return parsed, errors + build_errors


class FeeAndWithholdingParsingTests(unittest.TestCase):
    def test_fee_positivo_y_reverso_negativo(self):
        parsed, errors = parse(FEES_CSV)
        self.assertEqual(errors, [])
        self.assertEqual(len(parsed), 2)  # la fila Total queda fuera

        cobro, reverso = parsed
        self.assertEqual(cobro.tipo, "FEE")
        self.assertEqual(cobro.total_usd, 1.5)     # sale caja
        self.assertEqual(reverso.total_usd, -1.5)  # IB lo devolvió

    def test_retencion_se_atribuye_al_ticker(self):
        parsed, errors = parse(WITHHOLDING_CSV)
        self.assertEqual(errors, [])
        self.assertEqual(len(parsed), 1)

        ret = parsed[0]
        self.assertEqual(ret.tipo, "WITHHOLDING_TAX")
        self.assertEqual(ret.ticker, "F")
        self.assertEqual(ret.total_usd, 4.5)

    def test_comision_devuelta_queda_negativa(self):
        parsed, _ = parse(COMMISSION_REBATE_CSV)
        venta, recompra = parsed

        self.assertAlmostEqual(venta.comision_usd, 2.807, places=3)
        self.assertAlmostEqual(recompra.comision_usd, -0.727, places=3)
        # Neto = lo que IB cobró de verdad por el ciclo.
        self.assertAlmostEqual(venta.comision_usd + recompra.comision_usd, 2.08, places=2)


class CashBalanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(User(id=1, email="t@t.cl", username="t", hashed_password="x"))
        self.db.commit()
        self.user = self.db.query(User).first()

    def tearDown(self):
        self.db.close()

    def add(self, tipo, monto, commission=0.0, when=datetime(2026, 3, 1, tzinfo=timezone.utc)):
        self.db.add(Transaction(
            user_id=1, ticker="X", transaction_type=tipo, quantity=1, price=1,
            total_amount=monto, commission=commission, transaction_date=when,
        ))
        self.db.commit()

    def test_entradas_salidas_y_comisiones(self):
        self.add(TransactionType.DEPOSIT, 1000.0)
        self.add(TransactionType.BUY_STOCK, 300.0, commission=1.0)
        self.add(TransactionType.SELL_CALL, 50.0, commission=1.5)
        self.add(TransactionType.WITHDRAWAL, 200.0)

        res = compute_cash_balance(self.db, self.user)
        self.assertEqual(res["cash_balance"], 547.5)  # 1000 - 300 + 50 - 200 - 2.5
        self.assertEqual(res["inflows"], 1050.0)
        self.assertEqual(res["outflows"], 500.0)

    def test_fee_revertido_vuelve_a_sumar(self):
        self.add(TransactionType.DEPOSIT, 100.0)
        self.add(TransactionType.FEE, 1.5)
        self.add(TransactionType.FEE, -1.5)

        self.assertEqual(compute_cash_balance(self.db, self.user)["cash_balance"], 100.0)

    def test_expiracion_y_asignacion_no_mueven_caja(self):
        self.add(TransactionType.DEPOSIT, 100.0)
        self.add(TransactionType.OPTION_EXPIRY, 0.0)
        self.add(TransactionType.ASSIGNMENT, 500.0)

        self.assertEqual(compute_cash_balance(self.db, self.user)["cash_balance"], 100.0)

    def test_el_ancla_excluye_lo_anterior_a_su_fecha(self):
        self.add(TransactionType.DEPOSIT, 999.0, when=datetime(2025, 6, 1, tzinfo=timezone.utc))
        self.add(TransactionType.DEPOSIT, 100.0, when=datetime(2026, 3, 1, tzinfo=timezone.utc))

        self.user.cash_opening_balance = 50.0
        self.user.cash_opening_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.db.commit()

        res = compute_cash_balance(self.db, self.user)
        self.assertEqual(res["cash_balance"], 150.0)   # 50 de ancla + 100, sin el depósito viejo
        self.assertEqual(res["transactions_counted"], 1)

    def test_sin_ancla_se_suma_todo_el_historial(self):
        self.add(TransactionType.DEPOSIT, 999.0, when=datetime(2025, 6, 1, tzinfo=timezone.utc))
        self.add(TransactionType.DEPOSIT, 100.0)

        self.assertEqual(compute_cash_balance(self.db, self.user)["cash_balance"], 1099.0)

    def test_saldo_derivado_reproduce_el_extracto(self):
        """Starting Cash + flujos del período = Ending Cash, según el Cash Report de IB."""
        self.user.cash_opening_balance = 377.623443381
        self.user.cash_opening_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.db.commit()

        # Totales del Cash Report del extracto U7013196_20260101_20260804.
        self.add(TransactionType.SELL_STOCK, 7980.6395)   # Trades (Sales), pata acciones
        self.add(TransactionType.SELL_CALL, 935.0)        # Trades (Sales), pata opciones
        self.add(TransactionType.BUY_STOCK, 7802.9047)    # Trades (Purchase), acciones
        self.add(TransactionType.BUY_CALL, 196.0)         # Trades (Purchase), opciones
        self.add(TransactionType.DIVIDEND, 15.0)          # Payment In Lieu of Dividends
        self.add(TransactionType.WITHHOLDING_TAX, 4.5)
        self.add(TransactionType.FEE, 9.0)                # Other Fees
        self.add(TransactionType.WITHDRAWAL, 1200.0)
        self.add(TransactionType.BUY_STOCK, 0.0, commission=53.18967345)  # Commissions

        res = compute_cash_balance(self.db, self.user)
        self.assertAlmostEqual(res["cash_balance"], 42.67, places=2)  # Ending Cash de IB


if __name__ == "__main__":
    unittest.main()
