"""
Importador de Interactive Brokers Activity Statement
------------------------------------------------------
Soporta el formato CSV exportado desde:
  IB Client Portal / TWS → Reports → Activity → Statements → Format: CSV

Las secciones que se procesan:
  - Trades                  → acciones (Stocks) y opciones (Equity and Index Options)
  - Dividends               → dividendos
  - Deposits & Withdrawals  → movimientos de efectivo (ticker sintético CASH)
  - Corporate Actions con "Assignment" → asignaciones

Las asignaciones no llegan por Corporate Actions: IB las reporta como filas de
Trades con el código `A` (dos patas, la del contrato y la de las acciones).

Cómo exportar desde IB:
  1. Ir a Reports → Activity → Statements
  2. Tipo: Activity
  3. Período: el año que quieres importar
  4. Formato: CSV → Download
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from zoneinfo import ZoneInfo
import csv
import io
import re

from ..database import get_db
from ..models import Transaction, TransactionType, Stock, Option, OptionType, OptionStrategy, OptionStatus, User, BrokerSyncRun
from ..utils.auth import get_current_user
from ..market.market_data import MarketDataService
from ..providers.base import BrokerCashTransaction, BrokerExecution, BrokerPositionLot, ProviderError
from ..providers.ibkr_flex import IbkrFlexBrokerProvider

router = APIRouter()

# ─── Schemas ──────────────────────────────────────────────────────────────────

class ParsedTransaction(BaseModel):
    ib_row: int                       # número de fila en el CSV original
    fecha: str                        # YYYY-MM-DD HH:MM:SS
    ticker: str
    tipo: str                         # valor de TransactionType
    tipo_label: str                   # etiqueta legible
    asset_category: str               # Stocks / Options
    cantidad: float
    precio_usd: float
    total_usd: float                  # |Proceeds|
    comision_usd: float
    notas: str
    advertencia: str                  # si hay algo a revisar
    duplicado: bool                   # si ya existe en la BD
    strike_price: Optional[float] = None   # solo para opciones
    expiration_date: Optional[str] = None  # YYYY-MM-DD, solo para opciones
    opt_type: Optional[str] = None         # C o P, solo para opciones
    es_asignacion: bool = False            # el contrato se cerró por asignación
    duplicado_metodo: Optional[str] = None  # hash_exacto | cierre_cero | grupo_agregado


class PreviewResponse(BaseModel):
    transacciones: List[ParsedTransaction]
    tickers_acciones: List[str]
    total_filas_csv: int
    total_importables: int
    total_duplicados: int
    total_advertencias: int
    errores_parseo: List[str]


class ImportRequest(BaseModel):
    transacciones: List[ParsedTransaction]
    omitir_duplicados: bool = True


class ImportResult(BaseModel):
    importadas: int
    omitidas: int
    stocks_creados: List[str]
    stocks_actualizados: List[str]
    errores: List[str]


class FlexPreviewResponse(PreviewResponse):
    posiciones_discrepantes: List[dict] = []
    advertencia_global: Optional[str] = None


class ManualPreviewRequest(BaseModel):
    raw_text: str
    trade_date: str                    # YYYY-MM-DD


# ─── Parser del formato IB Activity Statement ─────────────────────────────────

# Formato compacto IB: 'AAPL  250117C00150000'
IB_OPTION_RE = re.compile(
    r"^(?P<underlying>[A-Z]{1,6})\s+"        # ticker subyacente (1-6 letras + espacios)
    r"(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"  # YYMMDD
    r"(?P<opttype>[CP])"                      # C=Call, P=Put
    r"(?P<strike>\d{8})$"                     # strike × 1000 (8 dígitos)
)

# Formato legible IB: 'MARA 20FEB26 8.5 C'
IB_OPTION_RE2 = re.compile(
    r"^(?P<underlying>[A-Z]{1,6})\s+"        # ticker subyacente
    r"(?P<dd>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2})\s+"  # DDMMMYY (ej: 20FEB26)
    r"(?P<strike>[\d.]+)\s+"                 # strike decimal (ej: 8.5)
    r"(?P<opttype>[CP])$"                    # C=Call, P=Put
)

# Formato visible en tabla de Trades: 'F May15'26 12 Call' o 'F May08 '26 12 Call'
IB_OPTION_RE3 = re.compile(
    r"^(?P<underlying>[A-Z]{1,10})\s+"
    r"(?P<mon>[A-Za-z]{3})\s*(?P<dd>\d{1,2})\s*'(?P<yy>\d{2})\s+"
    r"(?P<strike>[\d.]+)\s+"
    r"(?P<opttype>Call|Put|C|P)$",
    re.IGNORECASE,
)

MANUAL_SUMMARY_RE = re.compile(
    r"^(?P<action>Sold|Bought|Bot|Buy|Sell)\s+"
    r"(?P<qty>[-\d.,]+)\s+@\s+"
    r"(?P<price>[-\d.,]+)"
    r"(?:\s+on\s+(?P<venue>.+))?$",
    re.IGNORECASE,
)
MANUAL_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
# Formato fecha+hora visible en tabla de Trades: '8/5/2026, 9:42' (D/M/YYYY H:MM europeo)
MANUAL_DATETIME_RE = re.compile(
    r"^(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4}),?\s+(?P<hm>\d{1,2}:\d{2})$"
)
MANUAL_ACCOUNT_RE = re.compile(r"^[A-Z]\d{5,}$")
MANUAL_COMMISSION_RE = re.compile(
    r"^(?:Comisiones?|Commission(?:s)?):\s*(?P<value>[-\d.,]+)$",
    re.IGNORECASE,
)
# Formato de expiración en tabla de Trades: 'EXPIRED 2 on OCC'
MANUAL_EXPIRY_RE = re.compile(
    r"^EXPIRED\s+(?P<qty>\d+)(?:\s+on\s+(?P<venue>.+))?$",
    re.IGNORECASE,
)
MANUAL_STATUS_TOKENS = {
    "filled",
    "partially filled",
    "submitted",
    "cancelled",
    "pending",
    "expired",
}
MANUAL_HEADER_TOKENS = {
    "TRADES",
    "CUENTA",
    "ACCION",
    "ACCIÓN",
    "CANTIDAD",
    "STATUS",
    "PRECIO",
    "COMISIONES",
}

_MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def parse_ib_option_symbol(symbol: str):
    """
    Parsea el símbolo de opción de IB al formato legible.
    Soporta dos formatos:
      - Compacto: 'AAPL  250117C00150000' → ('AAPL', 'C', 150.0, '2025-01-17')
      - Legible:  'MARA 20FEB26 8.5 C'   → ('MARA', 'C', 8.5,   '2026-02-20')
    Retorna (underlying, opt_type, strike, expiry_str) o None si no es opción.
    """
    s = symbol.strip()

    # Intenta formato compacto primero
    m = IB_OPTION_RE.match(s)
    if m:
        underlying = m.group("underlying").strip()
        opt_type = m.group("opttype")
        strike = int(m.group("strike")) / 1000.0
        expiry = f"20{m.group('yy')}-{m.group('mm')}-{m.group('dd')}"
        return underlying, opt_type, strike, expiry

    # Intenta formato legible: 'MARA 20FEB26 8.5 C'
    m2 = IB_OPTION_RE2.match(s)
    if m2:
        underlying = m2.group("underlying").strip()
        opt_type = m2.group("opttype")
        strike = float(m2.group("strike"))
        mm = _MONTH_MAP.get(m2.group("mon").upper(), "01")
        expiry = f"20{m2.group('yy')}-{mm}-{m2.group('dd')}"
        return underlying, opt_type, strike, expiry

    # Intenta formato visible en tabla de trades: 'F May15'26 12 Call'
    m3 = IB_OPTION_RE3.match(s)
    if m3:
        underlying = m3.group("underlying").strip()
        opt_label = m3.group("opttype").upper()
        opt_type = "C" if opt_label.startswith("C") else "P"
        strike = float(m3.group("strike"))
        mm = _MONTH_MAP.get(m3.group("mon").upper(), "01")
        dd = m3.group("dd").zfill(2)
        expiry = f"20{m3.group('yy')}-{mm}-{dd}"
        return underlying, opt_type, strike, expiry

    return None


def determine_transaction_type(asset_category: str, quantity: float, opt_type: Optional[str]) -> TransactionType:
    """Determina el TransactionType según la categoría y la dirección de la operación."""
    cat = asset_category.lower()
    if "stock" in cat:
        return TransactionType.BUY_STOCK if quantity > 0 else TransactionType.SELL_STOCK
    elif "option" in cat or "equity and index" in cat:
        if opt_type == "C":
            return TransactionType.BUY_CALL if quantity > 0 else TransactionType.SELL_CALL
        else:
            return TransactionType.BUY_PUT if quantity > 0 else TransactionType.SELL_PUT
    return TransactionType.BUY_STOCK  # fallback


TIPO_LABELS = {
    "BUY_STOCK":     "Compra Acción",
    "SELL_STOCK":    "Venta Acción",
    "SELL_CALL":     "Prima Covered Call",
    "BUY_CALL":      "Cierre Call",
    "SELL_PUT":      "Prima Cash-Secured Put",
    "BUY_PUT":       "Cierre Put",
    "DIVIDEND":      "Dividendo",
    "ASSIGNMENT":    "Asignación",
    "OPTION_EXPIRY": "Expiración Opción",
    "DEPOSIT":       "Depósito",
    "WITHDRAWAL":    "Retiro",
}

# Los movimientos de efectivo no tienen instrumento, pero `Transaction.ticker`
# es NOT NULL. Este ticker sintético los agrupa sin ensuciar el portafolio:
# ningún `Stock` se llama así, por lo que quedan con `stock_id = NULL`.
CASH_TICKER = "CASH"


def has_ib_code(code: str, target: str) -> bool:
    """
    ¿El campo Code de IB contiene el código `target`?

    Viene como lista separada por `;` ("A;C", "IM;O;P"). Hay que comparar token
    a token: buscar el substring "A" daría positivo en "IA" (importado ajustado),
    que no tiene nada que ver con una asignación.
    """
    return target in {token.strip() for token in (code or "").split(";")}


def parse_float(value: str) -> float:
    """Parsea números con formato US o local, por ejemplo 1,234.56 o 1.234,56."""
    try:
        if value is None:
            return 0.0

        normalized = str(value).strip()
        if not normalized:
            return 0.0

        normalized = (
            normalized
            .replace("$", "")
            .replace("USD", "")
            .replace("US$", "")
            .replace("\xa0", "")
            .replace("−", "-")
            .replace(" ", "")
        )

        if normalized.startswith("(") and normalized.endswith(")"):
            normalized = f"-{normalized[1:-1]}"

        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
        elif "," in normalized:
            whole, decimal = normalized.rsplit(",", 1)
            # European decimal separator: 1-2 digits (e.g. "1,50") or 4+ digits
            # (e.g. "1268,1375" from IB 4-decimal exports). US thousands groups
            # are always exactly 3 digits (e.g. "1,268"), so treat 3-digit suffix
            # as a thousands separator and remove the comma.
            if decimal.isdigit() and (len(decimal) <= 2 or len(decimal) >= 4):
                normalized = f"{whole.replace('.', '')}.{decimal}"
            else:
                normalized = normalized.replace(",", "")

        return float(normalized)
    except (ValueError, AttributeError):
        return 0.0


def parse_ib_datetime(value: str) -> Optional[datetime]:
    """
    IB puede exportar fechas en varios formatos:
      '2025-01-15, 10:30:00'  (coma interna)
      '2025-01-15 10:30:00'
      '2025-01-15'
    """
    value = value.replace(",", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_ib_csv(content: str) -> tuple[list[dict], list[str]]:
    """
    Parsea el CSV de IB Activity Statement.
    Retorna (filas_procesadas, errores).
    Cada fila es un dict con:
      section, asset_category, symbol, datetime_str, quantity, t_price,
      proceeds, comm_fee, description (para dividendos)
    """
    rows = []
    errors = []

    # IB usa múltiples secciones en el mismo CSV.
    # Estrategia: procesar línea a línea guardando los headers por sección.
    section_headers: dict[str, list[str]] = {}
    reader = csv.reader(io.StringIO(content))
    raw_rows = list(reader)

    for line_num, row in enumerate(raw_rows, start=1):
        if not row or len(row) < 2:
            continue

        section = row[0].strip()
        discriminator = row[1].strip()

        # Guardar headers de cada sección
        if discriminator == "Header":
            section_headers[section] = [c.strip() for c in row[2:]]
            continue

        if discriminator not in ("Data", "SubTotal", "Total"):
            continue
        if discriminator in ("SubTotal", "Total"):
            continue

        headers = section_headers.get(section, [])
        if not headers:
            continue

        data_cols = row[2:]
        # Algunas filas de IB tienen una columna extra "DataDiscriminator" al inicio
        # La removemos si el primer header es "DataDiscriminator"
        if headers and headers[0] == "DataDiscriminator":
            headers = headers[1:]
            if data_cols:
                data_cols = data_cols[1:]

        data = dict(zip(headers, data_cols))

        # ── Sección Trades ──────────────────────────────────────────────────
        if section == "Trades":
            asset_cat = data.get("Asset Category", "").strip()
            if asset_cat not in ("Stocks", "Equity and Index Options", "Options"):
                continue  # ignorar Forex, Bonds, etc.

            symbol = data.get("Symbol", "").strip()
            datetime_str = data.get("Date/Time", "").strip()
            quantity_str = data.get("Quantity", "0")
            price_str = data.get("T. Price", "0")
            proceeds_str = data.get("Proceeds", "0")
            comm_str = data.get("Comm/Fee", "0")
            code = data.get("Code", "").strip()

            # Ignorar cancelaciones/correcciones (Code 'Ca' = cancel)
            if "Ca" in code:
                continue

            rows.append({
                "line": line_num,
                "section": "Trades",
                "asset_category": asset_cat,
                "symbol": symbol,
                "datetime_str": datetime_str,
                "quantity": parse_float(quantity_str),
                "t_price": parse_float(price_str),
                "proceeds": parse_float(proceeds_str),
                # IB reporta la comisión negativa cuando cobra. Se invierte para
                # dejar positivo = costo, que es la convención en la BD. Las
                # recompras en que IB devuelve comisión quedan negativas y así
                # el saldo de caja cuadra sin casos especiales.
                "comm_fee": -parse_float(comm_str),
                "description": "",
                "code": code,
            })

        # ── Sección Dividends ───────────────────────────────────────────────
        elif section == "Dividends":
            currency = data.get("Currency", "").strip()
            if currency == "Total":
                continue

            date_str = data.get("Date", "").strip()
            description = data.get("Description", "").strip()
            amount_str = data.get("Amount", "0")

            # Extraer ticker del description: "AAPL(US0378...) Cash Dividend..."
            ticker_match = re.match(r"^([A-Z0-9]{1,10})[\s(]", description)
            if not ticker_match:
                errors.append(f"Línea {line_num}: no se pudo extraer ticker del dividendo '{description}'")
                continue

            rows.append({
                "line": line_num,
                "section": "Dividends",
                "asset_category": "Stocks",
                "symbol": ticker_match.group(1),
                "datetime_str": date_str,
                "quantity": 0.0,
                "t_price": 0.0,
                "proceeds": parse_float(amount_str),
                "comm_fee": 0.0,
                "description": description,
            })

        # ── Sección Withholding Tax ─────────────────────────────────────────
        # Va separada de Fees: la retención de EE.UU. es acreditable contra el
        # Global Complementario (Art. 41A) y `api/fiscal.py` la necesita aparte.
        elif section == "Withholding Tax":
            if data.get("Currency", "").strip() == "Total":
                continue

            amount = parse_float(data.get("Amount", "0"))
            if amount == 0:
                continue

            description = data.get("Description", "").strip()
            # "F(US3453708600) Payment in Lieu of Dividend - US Tax" → F
            ticker_match = re.match(r"^([A-Z0-9]{1,10})[\s(]", description)

            rows.append({
                "line": line_num,
                "section": "WithholdingTax",
                "asset_category": "Stocks",
                "symbol": ticker_match.group(1) if ticker_match else CASH_TICKER,
                "datetime_str": data.get("Date", "").strip(),
                "quantity": 0.0,
                "t_price": 0.0,
                "proceeds": amount,
                "comm_fee": 0.0,
                "description": description,
            })

        # ── Sección Fees ────────────────────────────────────────────────────
        elif section == "Fees":
            if data.get("Subtitle", "").strip() == "Total" or data.get("Currency", "").strip() == "Total":
                continue

            amount = parse_float(data.get("Amount", "0"))
            if amount == 0:
                continue

            rows.append({
                "line": line_num,
                "section": "Fee",
                "asset_category": "Cash",
                "symbol": CASH_TICKER,
                "datetime_str": data.get("Date", "").strip(),
                "quantity": 0.0,
                "t_price": 0.0,
                "proceeds": amount,   # negativo = cobro, positivo = reverso
                "comm_fee": 0.0,
                "description": data.get("Description", "").strip(),
            })

        # ── Sección Deposits & Withdrawals ──────────────────────────────────
        elif section == "Deposits & Withdrawals":
            if data.get("Currency", "").strip() == "Total":
                continue

            amount = parse_float(data.get("Amount", "0"))
            if amount == 0:
                continue

            rows.append({
                "line": line_num,
                "section": "CashFlow",
                "asset_category": "Cash",
                "symbol": CASH_TICKER,
                "datetime_str": data.get("Settle Date", "").strip(),
                "quantity": 0.0,
                "t_price": 0.0,
                "proceeds": amount,          # el signo distingue depósito de retiro
                "comm_fee": 0.0,
                "description": data.get("Description", "").strip(),
            })

        # ── Sección Corporate Actions (Assignments) ─────────────────────────
        elif section == "Corporate Actions":
            description = data.get("Description", "").strip()
            if "assignment" not in description.lower():
                continue

            symbol = data.get("Symbol") or data.get("Asset Category", "").strip()
            datetime_str = data.get("Date/Time") or data.get("Report Date", "").strip()
            quantity_str = data.get("Quantity", "0")
            proceeds_str = data.get("Proceeds", "0")
            comm_str = data.get("Comm/Fee", "0")

            rows.append({
                "line": line_num,
                "section": "CorporateActions",
                "asset_category": "Options",
                "symbol": symbol.strip(),
                "datetime_str": datetime_str,
                "quantity": parse_float(quantity_str),
                "t_price": 0.0,
                "proceeds": parse_float(proceeds_str),
                "comm_fee": -parse_float(comm_str),
                "description": description,
            })

    return rows, errors


def normalize_manual_line(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_manual_action(value: str) -> Optional[str]:
    action = value.strip().lower()
    if action in ("bought", "bot", "buy"):
        return "BUY"
    if action in ("sold", "sell"):
        return "SELL"
    return None


def is_header_like_line(value: str) -> bool:
    return value.strip().upper() in MANUAL_HEADER_TOKENS


def is_numeric_line(value: str) -> bool:
    candidate = value.strip().replace(" ", "")
    if not candidate:
        return False
    return bool(re.fullmatch(r"[-\d.,]+", candidate))


def is_symbol_candidate(value: str) -> bool:
    lower_value = value.strip().lower()
    if not value or is_header_like_line(value):
        return False
    if MANUAL_SUMMARY_RE.match(value):
        return False
    if MANUAL_TIME_RE.match(value):
        return False
    if MANUAL_ACCOUNT_RE.match(value):
        return False
    if MANUAL_COMMISSION_RE.match(value):
        return False
    if normalize_manual_action(value) is not None:
        return False
    if lower_value in MANUAL_STATUS_TOKENS:
        return False
    if is_numeric_line(value):
        return False
    if MANUAL_DATETIME_RE.match(value):
        return False
    return True


def split_manual_trade_blocks(content: str) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    current_lines: list[str] = []
    current_start = 1

    # Strip trailing tabs per line before converting tabs to newlines; IB table copies
    # produce lines like "U7013196\tSold\t1\t" whose trailing tab would create a
    # spurious empty line that prematurely splits the block.
    pre = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip("\t") for line in pre.split("\n")).replace("\t", "\n")

    for index, raw_line in enumerate(normalized.split("\n"), start=1):
        line = normalize_manual_line(raw_line)
        if not line:
            if current_lines:
                blocks.append((current_start, current_lines))
                current_lines = []
            current_start = index + 1
            continue

        if not current_lines:
            current_start = index
        current_lines.append(line)

        if MANUAL_COMMISSION_RE.match(line):
            blocks.append((current_start, current_lines))
            current_lines = []
            current_start = index + 1

    if current_lines:
        blocks.append((current_start, current_lines))

    return blocks


def _extract_dt_from_block(block: list[str], trade_date: str) -> Optional[datetime]:
    """Extrae datetime del bloque: primero busca formato D/M/YYYY, luego solo hora."""
    for line in block:
        dm = MANUAL_DATETIME_RE.match(line)
        if dm:
            try:
                day, month, year = int(dm.group("d")), int(dm.group("m")), int(dm.group("y"))
                hm = dm.group("hm")
                if len(hm.split(":")) == 2:
                    hm = f"{hm}:00"
                return datetime.strptime(f"{year:04d}-{month:02d}-{day:02d} {hm}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
            break
    time_line = next((line for line in block if MANUAL_TIME_RE.match(line)), None)
    time_value = time_line or "00:00:00"
    if len(time_value.split(":")) == 2:
        time_value = f"{time_value}:00"
    return parse_ib_datetime(f"{trade_date} {time_value}")


def parse_manual_trade_block(start_line: int, block: list[str], trade_date: str) -> tuple[Optional[dict], list[str]]:
    if not block or all(is_header_like_line(line) for line in block):
        return None, []

    # ── Bloque de expiración: 'EXPIRED 2 on OCC' ──────────────────────────────
    expiry_line = next((line for line in block if MANUAL_EXPIRY_RE.match(line)), None)
    if expiry_line:
        expiry_match = MANUAL_EXPIRY_RE.match(expiry_line)
        qty = int(expiry_match.group("qty"))
        if qty == 0:
            return None, [f"Bloque desde línea {start_line}: cantidad 0 en expiración '{expiry_line}'."]

        symbol_line = next((line for line in block if is_symbol_candidate(line)), None)
        if not symbol_line:
            return None, [f"Bloque desde línea {start_line}: no se pudo identificar el símbolo de la expiración."]

        dt = _extract_dt_from_block(block, trade_date)
        if not dt:
            return None, [f"Bloque desde línea {start_line}: fecha/hora inválida en bloque de expiración."]

        return {
            "line": start_line,
            "section": "OptionExpiry",
            "asset_category": "Equity and Index Options",
            "symbol": symbol_line,
            "datetime_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "quantity": qty,
            "t_price": 0.0,
            "proceeds": 0.0,
            "comm_fee": 0.0,
            "description": f"Expiración | {symbol_line}",
        }, []

    summary_line = next((line for line in block if MANUAL_SUMMARY_RE.match(line)), None)
    if not summary_line:
        return None, [f"Bloque desde línea {start_line}: no se encontró una línea tipo 'Bought 1 @ 0.22 on CBOE'."]

    summary_match = MANUAL_SUMMARY_RE.match(summary_line)
    if not summary_match:
        return None, [f"Bloque desde línea {start_line}: formato de resumen inválido '{summary_line}'."]

    action = normalize_manual_action(summary_match.group("action") or "")
    if not action:
        return None, [f"Bloque desde línea {start_line}: acción no reconocida en '{summary_line}'."]

    symbol_line = next((line for line in block if is_symbol_candidate(line)), None)
    if not symbol_line:
        return None, [f"Bloque desde línea {start_line}: no se pudo identificar el símbolo de la operación."]

    status_line = next((line for line in block if line.strip().lower() in MANUAL_STATUS_TOKENS), None)
    if status_line and status_line.strip().lower() != "filled":
        return None, [
            f"Bloque desde línea {start_line}: status '{status_line}' no es final. Solo se importan operaciones ejecutadas (Filled)."
        ]

    dt = _extract_dt_from_block(block, trade_date)
    if not dt:
        return None, [f"Bloque desde línea {start_line}: fecha/hora inválida."]

    quantity_abs = abs(parse_float(summary_match.group("qty") or "0"))
    price_value = abs(parse_float(summary_match.group("price") or "0"))
    if quantity_abs == 0:
        return None, [f"Bloque desde línea {start_line}: cantidad inválida en '{summary_line}'."]

    number_values: list[float] = []
    for line in block:
        if not is_numeric_line(line):
            continue
        parsed_number = abs(parse_float(line))
        if parsed_number == 0:
            continue
        number_values.append(parsed_number)

    total_value = 0.0
    if number_values:
        for parsed_number in reversed(number_values):
            if round(parsed_number, 4) not in (round(quantity_abs, 4), round(price_value, 4)):
                total_value = parsed_number
                break

    opt_info = parse_ib_option_symbol(symbol_line)
    is_option_trade = opt_info is not None

    if total_value == 0:
        multiplier = 100 if is_option_trade else 1
        total_value = round(quantity_abs * price_value * multiplier, 2)

    commission_match = next((MANUAL_COMMISSION_RE.match(line) for line in block if MANUAL_COMMISSION_RE.match(line)), None)
    commission_value = abs(parse_float(commission_match.group("value"))) if commission_match else 0.0

    signed_quantity = quantity_abs if action == "BUY" else -quantity_abs

    return {
        "line": start_line,
        "section": "Trades",
        "asset_category": "Equity and Index Options" if is_option_trade else "Stocks",
        "symbol": symbol_line,
        "datetime_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "quantity": signed_quantity,
        "t_price": price_value,
        "proceeds": total_value,
        "comm_fee": commission_value,
        "description": f"Manual trade import | {summary_line}",
    }, []


def parse_manual_trades_text(content: str, trade_date: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    errors: list[str] = []

    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        return [], ["La fecha de operaciones debe venir en formato YYYY-MM-DD."]

    for start_line, block in split_manual_trade_blocks(content):
        parsed_row, block_errors = parse_manual_trade_block(start_line, block, trade_date)
        if parsed_row:
            rows.append(parsed_row)
        errors.extend(block_errors)

    return rows, errors


# Un cierre de opción sin valor puede quedar registrado como OPTION_EXPIRY o como
# BUY_CALL/BUY_PUT ("Cierre Call/Put") según la vía de importación usada (CSV de
# Trades vs texto pegado de la tabla con "EXPIRED ... on OCC"). Para el detector de
# duplicados estos tipos son equivalentes cuando el monto es $0.
ZERO_VALUE_CLOSE_TYPES = {"OPTION_EXPIRY", "BUY_CALL", "BUY_PUT"}
# Margen de días porque la fecha registrada puede ser la de expiración o la de
# liquidación (settlement), que IB reporta con hasta un par de días de diferencia.
ZERO_CLOSE_DATE_MARGIN_DAYS = 3


def build_existing_hashes(db: Session, current_user: User) -> tuple[set, dict, dict]:
    existing_txs = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .all()
    )

    existing_hashes: set = set()
    existing_zero_closes: dict[tuple[str, float], list[datetime]] = {}
    # Una misma orden de IB puede quedar registrada en BD como varias filas
    # (ej. fills parciales importados por separado) en vez de la fila agregada
    # que trae el CSV. Se agrupa por (ticker, fecha, tipo) para poder comparar
    # la suma de cantidad/total contra la fila nueva.
    existing_groups: dict[tuple[str, str, str], dict] = {}
    for t in existing_txs:
        total_abs = round(abs(t.total_amount), 2)
        date_str = t.transaction_date.strftime("%Y-%m-%d")
        sig = (t.ticker, date_str, t.transaction_type.value, total_abs, round(t.quantity, 4))
        existing_hashes.add(sig)

        if t.transaction_type.value in ZERO_VALUE_CLOSE_TYPES and total_abs == 0.0:
            key = (t.ticker, round(t.quantity, 4))
            existing_zero_closes.setdefault(key, []).append(t.transaction_date)

        group_key = (t.ticker, date_str, t.transaction_type.value)
        group = existing_groups.setdefault(group_key, {"qty_sum": 0.0, "total_sum": 0.0, "count": 0})
        group["qty_sum"] += t.quantity
        group["total_sum"] += total_abs
        group["count"] += 1

    return existing_hashes, existing_zero_closes, existing_groups


def build_preview_response(raw_rows: list[dict], parse_errors: list[str], db: Session, current_user: User) -> PreviewResponse:
    existing_hashes, existing_zero_closes, existing_groups = build_existing_hashes(db, current_user)
    parsed, build_errors = build_parsed_transactions(raw_rows, existing_hashes, existing_zero_closes, existing_groups)
    all_errors = parse_errors + build_errors

    tickers_acciones = sorted({
        p.ticker for p in parsed
        if p.tipo in ("BUY_STOCK", "SELL_STOCK")
    })

    return PreviewResponse(
        transacciones=parsed,
        tickers_acciones=tickers_acciones,
        total_filas_csv=len(raw_rows),
        total_importables=sum(1 for p in parsed if not p.duplicado),
        total_duplicados=sum(1 for p in parsed if p.duplicado),
        total_advertencias=sum(1 for p in parsed if p.advertencia),
        errores_parseo=all_errors,
    )


def build_parsed_transactions(
    raw_rows: list[dict],
    existing_hashes: set,
    existing_zero_closes: Optional[dict] = None,
    existing_groups: Optional[dict] = None,
) -> tuple[list[ParsedTransaction], list[str]]:
    """
    Convierte las filas crudas en ParsedTransaction.
    existing_hashes: set de (ticker, fecha_str, tipo, total) ya en BD → para detectar duplicados.

    El fallback de grupo (fills fragmentados vs. fila agregada) es simétrico:
    se agrupan tanto las filas ya en BD como las filas entrantes de esta
    importación por (ticker, fecha, tipo) y se comparan las sumas — sin
    importar de qué lado está fragmentada la orden. Antes solo cubría BD
    fragmentada + fila entrante agregada (una fuente CSV/manual siempre trae
    una fila por orden); IBKR Flex puede entregar fills fragmentados contra
    una BD que ya tiene la fila agregada, el caso inverso. Ver
    wiki/projects/kover/bugs/duplicado-btbt-import-manual-csv.md.
    """
    errors: list[str] = []
    zero_closes = existing_zero_closes or {}
    groups = existing_groups or {}

    # ── Pasada 1: derivar los campos de cada fila (misma lógica de siempre) ────
    staged: list[dict] = []

    for raw in raw_rows:
        line = raw["line"]
        section = raw["section"]
        symbol = raw["symbol"]
        datetime_str = raw["datetime_str"]

        # Parsear fecha
        dt = parse_ib_datetime(datetime_str)
        if not dt:
            errors.append(f"Línea {line}: fecha inválida '{datetime_str}' – fila omitida")
            continue

        fecha_iso = dt.strftime("%Y-%m-%d %H:%M:%S")

        advertencia = ""
        opt_info = None
        es_asignacion = False
        _strike = _expiry = _opt_type = None

        # ── Dividendo ──────────────────────────────────────────────────────
        if section == "Dividends":
            ticker = symbol.upper()
            tipo = TransactionType.DIVIDEND
            total_usd = abs(raw["proceeds"])
            cantidad = 0.0
            precio = 0.0
            notas = raw.get("description", "Dividendo IB")

        # ── Asignación ─────────────────────────────────────────────────────
        elif section == "CorporateActions":
            # opt_info: si el adaptador de un bróker ya trae los datos
            # estructurados (underlying/strike/expiración/right) se usan
            # directos — evita reparsear un string sintetizado con regex.
            opt_info = raw.get("opt_info") or parse_ib_option_symbol(symbol)
            ticker = opt_info[0] if opt_info else symbol.upper()
            tipo = TransactionType.ASSIGNMENT
            total_usd = abs(raw["proceeds"])
            cantidad = abs(raw["quantity"])
            precio = raw["t_price"]
            notas = raw.get("description", "Assignment IB")

        # ── Retención de impuesto / fee del bróker ─────────────────────────
        elif section in ("WithholdingTax", "Fee"):
            ticker = symbol.upper()
            tipo = (TransactionType.WITHHOLDING_TAX if section == "WithholdingTax"
                    else TransactionType.FEE)
            # IB los reporta negativos cuando cobra. Se invierte el signo para
            # respetar la convención (positivo = sale caja), de modo que un
            # reverso —IB cobró y devolvió— queda negativo y suma de vuelta.
            total_usd = -raw["proceeds"]
            cantidad = 0.0
            precio = 0.0
            notas = raw.get("description", "") or (
                "Retención IB" if section == "WithholdingTax" else "Fee IB"
            )

        # ── Movimiento de efectivo ─────────────────────────────────────────
        elif section == "CashFlow":
            monto = raw["proceeds"]
            ticker = CASH_TICKER
            tipo = TransactionType.DEPOSIT if monto > 0 else TransactionType.WITHDRAWAL
            total_usd = abs(monto)
            cantidad = 0.0
            precio = 0.0
            notas = raw.get("description", "Movimiento de efectivo IB")

        # ── Expiración de opción sin valor ──────────────────────────────────
        elif section == "OptionExpiry":
            opt_info = raw.get("opt_info") or parse_ib_option_symbol(symbol)
            if not opt_info:
                errors.append(f"Línea {line}: símbolo de opción no reconocido '{symbol}' – fila omitida")
                continue
            underlying, opt_type, strike, expiry = opt_info
            ticker = underlying
            tipo = TransactionType.OPTION_EXPIRY
            total_usd = 0.0
            cantidad = abs(raw["quantity"])
            precio = 0.0
            notas = f"Expiración | {symbol} | Strike ${strike} | Exp {expiry}"
            _strike = strike
            _expiry = expiry
            _opt_type = opt_type

        # ── Trade (acción u opción) ─────────────────────────────────────────
        else:
            asset_cat = raw["asset_category"]
            quantity = raw["quantity"]

            # IB marca ambas patas de una asignación con el código `A`: la compra
            # del contrato a precio 0 y la venta/compra de las acciones al strike.
            asignado = has_ib_code(raw.get("code", ""), "A")

            if "option" in asset_cat.lower():
                opt_info = raw.get("opt_info") or parse_ib_option_symbol(symbol)
                if not opt_info:
                    errors.append(f"Línea {line}: símbolo de opción no reconocido '{symbol}' – fila omitida")
                    continue
                underlying, opt_type, strike, expiry = opt_info
                ticker = underlying
                tipo = determine_transaction_type(asset_cat, quantity, opt_type)
                notas = f"IB | {symbol} | Strike ${strike} | Exp {expiry}"
                # Las opciones en IB reportan Proceeds por contrato × 100 multiplo
                total_usd = abs(raw["proceeds"])
                cantidad = abs(quantity)
                precio = abs(raw["t_price"])
                # Guardar info de la opción para crear Option record
                _strike = strike
                _expiry = expiry
                _opt_type = opt_type
                # Solo la pata que cierra el contrato (compra) es la asignación.
                # El tipo sigue siendo BUY_CALL/BUY_PUT — contablemente es un
                # cierre a $0 — pero marca la opción como ASSIGNED al importar.
                if asignado and quantity > 0:
                    es_asignacion = True
                    notas = f"Asignación | {symbol} | Strike ${strike} | Exp {expiry}"
            else:
                ticker = symbol.upper()
                opt_type = None
                tipo = determine_transaction_type(asset_cat, quantity, opt_type)
                total_usd = abs(raw["proceeds"])
                cantidad = abs(quantity)
                precio = abs(raw["t_price"])
                # Sigue siendo BUY_STOCK/SELL_STOCK: las acciones se mueven de
                # verdad y tienen que afectar la posición como cualquier trade.
                notas = "Asignación | acciones al strike" if asignado else "Importado desde IB"

            # Advertir si precio es 0 (en una asignación el contrato vale 0 por definición)
            if precio == 0 and not es_asignacion and tipo not in (TransactionType.DIVIDEND, TransactionType.ASSIGNMENT):
                advertencia = "Precio T. Price = 0, verifica el registro."
            # Advertir si total_usd difiere significativamente de cantidad × precio
            elif precio > 0 and cantidad > 0:
                expected = cantidad * precio * (100 if "option" in asset_cat.lower() else 1)
                if total_usd > 0 and (total_usd / expected > 10 or expected / total_usd > 10):
                    advertencia = f"Total ${total_usd:,.2f} difiere mucho de qty×precio (${expected:,.2f}). Posible error de formato en el CSV."

        # Con signo: el CSV ya viene normalizado a positivo = costo, y el pegado
        # manual solo produce positivos. Un negativo es una devolución de IB.
        comision = raw.get("comm_fee", 0.0)

        staged.append({
            "line": line, "section": section, "fecha_iso": fecha_iso, "dt": dt,
            "ticker": ticker, "tipo": tipo, "asset_category": raw["asset_category"],
            "cantidad": cantidad, "precio": precio, "total_usd": total_usd,
            "comision": comision, "notas": notas, "advertencia": advertencia,
            "strike": _strike, "expiry": _expiry, "opt_type": _opt_type,
            "es_asignacion": es_asignacion,
        })

    # ── Pasada 2: agrupar las filas ENTRANTES por (ticker, fecha, tipo) ────────
    # Mismo agrupamiento que build_existing_hashes aplica sobre la BD.
    incoming_groups: dict[tuple[str, str, str], dict] = {}
    for row in staged:
        key = (row["ticker"], row["dt"].strftime("%Y-%m-%d"), row["tipo"].value)
        g = incoming_groups.setdefault(key, {"qty_sum": 0.0, "total_sum": 0.0, "count": 0})
        g["qty_sum"] += row["cantidad"]
        g["total_sum"] += row["total_usd"]
        g["count"] += 1

    # ── Pasada 3: decidir duplicado (hash exacto → cierre cero → grupo) ────────
    results: list[ParsedTransaction] = []
    for row in staged:
        ticker, tipo, dt = row["ticker"], row["tipo"], row["dt"]
        cantidad, total_usd = row["cantidad"], row["total_usd"]

        sig = (ticker, dt.strftime("%Y-%m-%d"), tipo.value, round(total_usd, 2), round(cantidad, 4))
        duplicado = sig in existing_hashes
        duplicado_metodo = "hash_exacto" if duplicado else None

        # Fallback: cierres de opción sin valor (OPTION_EXPIRY / BUY_CALL / BUY_PUT a $0)
        # pueden estar ya en BD bajo otro tipo y/o con fecha de liquidación distinta.
        if not duplicado and tipo.value in ZERO_VALUE_CLOSE_TYPES and round(total_usd, 2) == 0.0:
            for existing_dt in zero_closes.get((ticker, round(cantidad, 4)), []):
                if abs((existing_dt.date() - dt.date()).days) <= ZERO_CLOSE_DATE_MARGIN_DAYS:
                    duplicado = True
                    duplicado_metodo = "cierre_cero"
                    break

        # Fallback: la misma orden puede estar repartida en varias filas (fills
        # parciales) de un lado y agregada del otro — no importa cuál lado (BD o
        # esta importación) esté fragmentado, solo que la suma calce.
        if not duplicado:
            key = (ticker, dt.strftime("%Y-%m-%d"), tipo.value)
            existing_group = groups.get(key)
            incoming_group = incoming_groups.get(key)
            if (
                existing_group and incoming_group
                and round(existing_group["qty_sum"], 4) == round(incoming_group["qty_sum"], 4)
                and round(existing_group["total_sum"], 2) == round(incoming_group["total_sum"], 2)
            ):
                duplicado = True
                duplicado_metodo = "grupo_agregado"

        results.append(ParsedTransaction(
            ib_row=row["line"],
            fecha=row["fecha_iso"],
            ticker=ticker,
            tipo=tipo.value,
            tipo_label=TIPO_LABELS.get(tipo.value, tipo.value),
            asset_category=row["asset_category"],
            cantidad=cantidad,
            precio_usd=round(row["precio"], 4),
            total_usd=round(total_usd, 2),
            comision_usd=round(row["comision"], 4),
            notas=row["notas"],
            advertencia=row["advertencia"],
            duplicado=duplicado,
            duplicado_metodo=duplicado_metodo,
            strike_price=row["strike"] if row["section"] in ("Trades", "OptionExpiry") else None,
            expiration_date=row["expiry"] if row["section"] in ("Trades", "OptionExpiry") else None,
            opt_type=row["opt_type"] if row["section"] in ("Trades", "OptionExpiry") else None,
            es_asignacion=row["es_asignacion"],
        ))

    return results, errors


# ─── Adaptador IBKR Flex → raw_rows ────────────────────────────────────────────
# Convierte los dataclasses de app/providers/base.py a la misma forma de dict
# que ya producen parse_ib_csv/parse_manual_trade_block, para que
# build_parsed_transactions y todo lo que sigue (incluido /confirm) no
# distinga si el origen fue un CSV, texto pegado o IBKR Flex.

def broker_execution_to_raw_row(execution: BrokerExecution, line: int) -> Optional[dict]:
    """Una BrokerExecution -> raw_row de sección Trades u OptionExpiry.

    El signo de `quantity` se reconstruye desde `side` (la dataclass lo
    guarda sin signo + dirección separada, justo para no tener que adivinar
    la convención de signo del bróker). La fecha civil se reconstruye desde
    `executed_at_utc` + `source_timezone` — nunca se usa el UTC directo: una
    ejecución después de ~19:00 ET cruza la medianoche UTC y correría la
    fecha un día, rompiendo el dedupe por (ticker, fecha, tipo) en silencio.
    """
    if execution.has_code("Ca"):
        return None  # cancelación/corrección — igual que parse_ib_csv

    local_dt = execution.executed_at_utc.astimezone(ZoneInfo(execution.source_timezone))
    datetime_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")

    opt_info = None
    if (
        execution.asset_category == "OPT"
        and execution.underlying and execution.right
        and execution.strike is not None and execution.expiration
    ):
        opt_info = (execution.underlying, execution.right, execution.strike, execution.expiration.isoformat())

    signed_qty = execution.quantity if execution.side == "BUY" else -execution.quantity
    # El bróker reporta la comisión negativa cuando cobra; se invierte para
    # dejar positivo = costo, igual que hace parse_ib_csv con el CSV crudo.
    comm_fee = -execution.commission

    if execution.has_code("Ep"):
        return {
            "line": line,
            "section": "OptionExpiry",
            "asset_category": "Equity and Index Options",
            "symbol": execution.symbol,
            "datetime_str": datetime_str,
            "quantity": execution.quantity,
            "t_price": 0.0,
            "proceeds": 0.0,
            "comm_fee": comm_fee,
            "description": f"Expiración IBKR Flex | {execution.symbol}",
            "opt_info": opt_info,
        }

    return {
        "line": line,
        "section": "Trades",
        "asset_category": "Stocks" if execution.asset_category == "STK" else "Equity and Index Options",
        "symbol": execution.symbol,
        "datetime_str": datetime_str,
        "quantity": signed_qty,
        "t_price": execution.price,
        "proceeds": execution.proceeds,
        "comm_fee": comm_fee,
        "description": "",
        "code": ";".join(execution.codes),
        "opt_info": opt_info,
    }


def broker_executions_to_raw_rows(executions: list[BrokerExecution]) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    for idx, execution in enumerate(executions, start=1):
        row = broker_execution_to_raw_row(execution, idx)
        if row is not None:
            rows.append(row)
    return rows, []


def broker_cash_to_raw_rows(cash_txs: list[BrokerCashTransaction]) -> tuple[list[dict], list[str]]:
    """CashTransaction (dividendos, retenciones, fees, depósitos/retiros) -> raw_rows.

    Usa `settle_date` (fecha civil pura que Flex ya entrega, sin componente de
    hora) en vez de convertir `executed_at_utc` — igual que parse_ib_csv, que
    lee la columna "Date"/"Settle Date" del CSV directo para estas secciones,
    nunca una hora exacta.
    """
    rows: list[dict] = []
    errors: list[str] = []
    for idx, tx in enumerate(cash_txs, start=1):
        if tx.settle_date is None:
            errors.append(
                f"Movimiento de efectivo IBKR Flex sin fecha de liquidación (tipo={tx.type!r}) – fila omitida"
            )
            continue

        datetime_str = tx.settle_date.strftime("%Y-%m-%d")
        symbol = (tx.symbol or "").strip().upper() or CASH_TICKER
        tx_type = (tx.type or "").strip()
        base = {
            "line": idx,
            "datetime_str": datetime_str,
            "quantity": 0.0,
            "t_price": 0.0,
            "proceeds": tx.amount,
            "comm_fee": 0.0,
        }

        if tx_type in ("Dividends", "Payment In Lieu Of Dividends"):
            description = tx.description or (
                "Dividendo IBKR Flex" if tx_type == "Dividends"
                else "Pago sustitutivo de dividendo (no calificado) IBKR Flex"
            )
            rows.append({**base, "section": "Dividends", "asset_category": "Stocks",
                         "symbol": symbol, "description": description})
        elif tx_type == "Withholding Tax":
            rows.append({**base, "section": "WithholdingTax", "asset_category": "Stocks",
                         "symbol": symbol, "description": tx.description or "Retención IBKR Flex"})
        elif tx_type in ("Deposits/Withdrawals", "Deposits & Withdrawals", "Transfers"):
            # Defensivo: al 2026-08-12 la Flex Query "Kover Activity" no trae
            # esta sección a nivel detalle (solo el total agregado en
            # CashReport) — ver docstring de app/providers/ibkr_flex.py. Si se
            # habilita en IBKR Client Portal, este branch ya queda listo.
            rows.append({**base, "section": "CashFlow", "asset_category": "Cash",
                         "symbol": CASH_TICKER, "description": tx.description or "Movimiento de efectivo IBKR Flex"})
        else:
            # "Other Fees", "AF" y cualquier otro tipo de cobro caen en Fee
            # genérico — igual que parse_ib_csv trata toda la sección Fees sin
            # distinguir subtipos.
            rows.append({**base, "section": "Fee", "asset_category": "Cash",
                         "symbol": CASH_TICKER, "description": tx.description or f"Fee IBKR Flex ({tx_type})"})

    return rows, errors


def build_position_reconciliation(
    db: Session, current_user: User, lots: list[BrokerPositionLot]
) -> list[dict]:
    """Compara Stock.shares de Kover contra las posiciones que reporta IBKR.

    Chequeo independiente del dedupe: si el dedupe se equivoca en cualquier
    dirección (importa de más o de menos), las acciones divergen de lo que
    IBKR realmente tiene — sin depender para nada de la heurística de grupo.
    Informativo: no bloquea el preview, solo lo advierte.
    """
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id, Stock.is_active == True).all()
    kover_shares = {s.ticker.upper(): s.shares for s in stocks}

    ibkr_shares: dict[str, float] = {}
    for lot in lots:
        if lot.asset_category != "STK":
            continue  # posiciones de opciones abiertas no tienen Stock.shares equivalente
        ticker = lot.symbol.upper()
        ibkr_shares[ticker] = ibkr_shares.get(ticker, 0.0) + lot.quantity

    discrepancias: list[dict] = []
    for ticker in sorted(set(kover_shares) | set(ibkr_shares)):
        kover_qty = kover_shares.get(ticker, 0.0)
        ibkr_qty = ibkr_shares.get(ticker, 0.0)
        if round(kover_qty, 4) != round(ibkr_qty, 4):
            discrepancias.append({
                "ticker": ticker,
                "kover_shares": kover_qty,
                "ibkr_shares": ibkr_qty,
                "diferencia": round(ibkr_qty - kover_qty, 4),
            })
    return discrepancias


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/preview", response_model=PreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Recibe el CSV de IB Activity Statement y devuelve una previsualización
    de las transacciones que se importarían, sin guardar nada.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un CSV (.csv)")

    content_bytes = await file.read()
    # IB puede exportar con encoding latin-1
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1")

    raw_rows, parse_errors = parse_ib_csv(content)
    return build_preview_response(raw_rows, parse_errors, db, current_user)


@router.post("/preview-manual", response_model=PreviewResponse)
async def preview_manual_import(
    body: ManualPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Recibe texto pegado desde la tabla de Trades de IBKR y devuelve una
    previsualización usando la misma lógica de importación del CSV.
    """
    if not body.raw_text or not body.raw_text.strip():
        raise HTTPException(status_code=400, detail="Debes pegar al menos una operación desde la tabla de Trades.")

    raw_rows, parse_errors = parse_manual_trades_text(body.raw_text, body.trade_date)
    if not raw_rows and parse_errors:
        raise HTTPException(status_code=400, detail=parse_errors[0])

    return build_preview_response(raw_rows, parse_errors, db, current_user)


@router.post("/preview-flex", response_model=FlexPreviewResponse)
async def preview_flex_import(
    incluir_efectivo: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trae ejecuciones, efectivo y posiciones desde IBKR Flex (Activity
    Statement), las adapta a la misma forma que el CSV/texto pegado, y
    devuelve un preview — no escribe nada. Se confirma con el mismo /confirm
    que ya usan el CSV y el texto pegado, sin cambios.
    """
    run = BrokerSyncRun(
        user_id=current_user.id,
        source="ACTIVITY",
        triggered_by="MANUAL",
        status="OK",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    provider = IbkrFlexBrokerProvider()
    try:
        executions = provider.get_executions()
        trade_rows, trade_errors = broker_executions_to_raw_rows(executions)

        cash_rows: list[dict] = []
        cash_errors: list[str] = []
        if incluir_efectivo:
            cash_txs = provider.get_cash_transactions()
            cash_rows, cash_errors = broker_cash_to_raw_rows(cash_txs)
            # Cada adaptador numera "line" desde 1 por su cuenta; al combinar
            # ambas listas hay que renumerar para que ib_row sea único (el
            # frontend lo usa como key de fila y como identificador del
            # checkbox de "forzar importación").
            offset = len(trade_rows)
            for i, row in enumerate(cash_rows, start=1):
                row["line"] = offset + i

        lots = provider.get_position_lots()
    except ProviderError as exc:
        # Nunca dejar caer al fallback silencioso de "0 filas": un preview
        # vacío por error es indistinguible de "ya está todo sincronizado".
        run.status = "ERROR"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=502, detail=f"IBKR Flex falló: {exc}")

    raw_rows = trade_rows + cash_rows
    parse_errors = trade_errors + cash_errors

    base_preview = build_preview_response(raw_rows, parse_errors, db, current_user)
    posiciones_discrepantes = build_position_reconciliation(db, current_user, lots)

    advertencia_global = None
    if len(raw_rows) > 500:
        advertencia_global = (
            f"{len(raw_rows)} filas en este preview — volumen inusualmente alto. "
            "Verifica que la Flex Query esté trayendo el período esperado antes de confirmar."
        )

    run.raw_row_count = len(raw_rows)
    run.importable_count = base_preview.total_importables
    run.duplicate_count = base_preview.total_duplicados
    run.warning_count = base_preview.total_advertencias
    run.position_mismatches = posiciones_discrepantes
    run.finished_at = datetime.utcnow()
    db.commit()

    return FlexPreviewResponse(
        **base_preview.model_dump(),
        posiciones_discrepantes=posiciones_discrepantes,
        advertencia_global=advertencia_global,
    )


@router.post("/confirm", response_model=ImportResult)
async def confirm_import(
    body: ImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Importa las transacciones confirmadas. Crea o actualiza posiciones de stocks.
    - omitir_duplicados=true (default): salta filas ya existentes
    - omitir_duplicados=false: importa todo (puede crear duplicados)
    """
    errores: list[str] = []
    importadas = 0
    omitidas = 0
    stocks_creados: list[str] = []
    stocks_actualizados: list[str] = []

    # Recopilar transacciones a procesar
    to_import = [
        t for t in body.transacciones
        if not (body.omitir_duplicados and t.duplicado)
    ]
    omitidas = len(body.transacciones) - len(to_import)

    # ── Fase 1: upsert de stocks para acciones ────────────────────────────
    # Agrupar compras/ventas por ticker para calcular posición neta
    stock_trades: dict[str, list[ParsedTransaction]] = {}
    for t in to_import:
        if t.tipo in ("BUY_STOCK", "SELL_STOCK"):
            stock_trades.setdefault(t.ticker, []).append(t)

    for ticker, trades in stock_trades.items():
        existing_stock = db.query(Stock).filter(
            Stock.ticker == ticker,
            Stock.user_id == current_user.id,
        ).first()

        # Calcular compras netas para este lote de importación
        total_shares_bought = sum(t.cantidad for t in trades if t.tipo == "BUY_STOCK")
        total_cost_bought = sum(t.total_usd for t in trades if t.tipo == "BUY_STOCK")
        total_shares_sold = sum(t.cantidad for t in trades if t.tipo == "SELL_STOCK")

        net_shares = total_shares_bought - total_shares_sold
        avg_cost = (total_cost_bought / total_shares_bought) if total_shares_bought > 0 else 0.0

        if existing_stock:
            # Actualizar posición existente
            if total_shares_bought > 0:
                # Determinar si la posición quedó completamente cerrada por las ventas de este lote
                # (mismo batch: ej. assignment + nueva compra en el mismo extracto)
                position_fully_closed = (
                    existing_stock.shares == 0 or
                    total_shares_sold >= existing_stock.shares
                )
                if position_fully_closed:
                    # Nuevo ciclo: el premium del ciclo anterior ya fue realizado
                    # al venderse/ejercerse las acciones. Partir de cero.
                    existing_stock.total_premium_earned = 0
                    prev_total = 0.0
                    effective_base_shares = 0
                else:
                    prev_total = existing_stock.shares * existing_stock.average_cost
                    effective_base_shares = existing_stock.shares

                new_total = effective_base_shares + total_shares_bought
                if new_total > 0:
                    new_avg = (prev_total + total_cost_bought) / new_total
                    existing_stock.average_cost = round(new_avg, 4)
            existing_stock.shares = max(0, existing_stock.shares + net_shares)
            existing_stock.total_invested = existing_stock.shares * existing_stock.average_cost
            # Recalculate adjusted_cost_basis preserving premium adjustment
            if existing_stock.shares > 0 and (existing_stock.total_premium_earned or 0) > 0:
                existing_stock.adjusted_cost_basis = round(
                    existing_stock.average_cost - (existing_stock.total_premium_earned / existing_stock.shares), 4
                )
            else:
                existing_stock.adjusted_cost_basis = existing_stock.average_cost
            existing_stock.is_active = existing_stock.shares > 0
            stocks_actualizados.append(ticker)
        else:
            # Crear nueva posición solo si hay shares netas positivas
            if net_shares > 0:
                company_name = ticker  # sin llamada a market para no ralentizar
                try:
                    info = MarketDataService.get_stock_info(ticker)
                    if info:
                        company_name = info.get("company_name", ticker)
                except Exception:
                    pass

                new_stock = Stock(
                    user_id=current_user.id,
                    ticker=ticker,
                    company_name=company_name,
                    shares=net_shares,
                    average_cost=round(avg_cost, 4),
                    total_invested=round(net_shares * avg_cost, 2),
                    adjusted_cost_basis=round(avg_cost, 4),
                    is_active=True,
                )
                db.add(new_stock)
                stocks_creados.append(ticker)

    # Flush para obtener IDs de los stocks recién creados
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear stocks: {str(e)}")

    # ── Fase 1.5: actualizar total_premium_earned para opciones ──────────
    # SELL_CALL/SELL_PUT = ingreso de prima (+), BUY_CALL/BUY_PUT = cierre/coste (-)
    option_trades: dict[str, list[ParsedTransaction]] = {}
    for t in to_import:
        if t.tipo in ("SELL_CALL", "BUY_CALL", "SELL_PUT", "BUY_PUT"):
            option_trades.setdefault(t.ticker, []).append(t)

    for ticker, trades in option_trades.items():
        stk = db.query(Stock).filter(
            Stock.ticker == ticker,
            Stock.user_id == current_user.id,
        ).first()
        if not stk:
            continue

        net_premium = sum(
            t.total_usd if t.tipo in ("SELL_CALL", "SELL_PUT") else -t.total_usd
            for t in trades
        )
        stk.total_premium_earned = max(0, round((stk.total_premium_earned or 0) + net_premium, 2))
        # Ajustar cost basis: average_cost menos prima por acción
        if stk.shares > 0:
            stk.adjusted_cost_basis = round(
                stk.average_cost - (stk.total_premium_earned / stk.shares), 4
            )

    # ── Fase 2: insertar transacciones ────────────────────────────────────
    for t in to_import:
        try:
            dt = datetime.strptime(t.fecha, "%Y-%m-%d %H:%M:%S")

            # Buscar stock_id si aplica
            stock_id = None
            if t.tipo in ("BUY_STOCK", "SELL_STOCK", "SELL_CALL", "BUY_CALL",
                          "SELL_PUT", "BUY_PUT", "DIVIDEND", "ASSIGNMENT", "OPTION_EXPIRY"):
                stk = db.query(Stock).filter(
                    Stock.ticker == t.ticker,
                    Stock.user_id == current_user.id,
                ).first()
                if stk:
                    stock_id = stk.id

            tx = Transaction(
                user_id=current_user.id,
                stock_id=stock_id,
                ticker=t.ticker,
                transaction_type=TransactionType(t.tipo),
                quantity=t.cantidad,
                price=t.precio_usd,
                total_amount=t.total_usd,
                commission=t.comision_usd,
                notes=t.notas,
                transaction_date=dt,
            )
            db.add(tx)
            importadas += 1
        except Exception as e:
            errores.append(f"Fila {t.ib_row} ({t.ticker} {t.tipo}): {str(e)}")

    # ── Fase 3: crear / cerrar registros de Option ─────────────────────
    for t in to_import:
        if t.tipo not in ("SELL_CALL", "BUY_CALL", "SELL_PUT", "BUY_PUT"):
            continue
        if not t.strike_price or not t.expiration_date:
            continue

        stk = db.query(Stock).filter(
            Stock.ticker == t.ticker,
            Stock.user_id == current_user.id,
        ).first()
        if not stk:
            continue

        try:
            dt_open = datetime.strptime(t.fecha, "%Y-%m-%d %H:%M:%S")
            dt_exp = datetime.strptime(t.expiration_date, "%Y-%m-%d")
        except ValueError:
            continue

        if t.tipo in ("SELL_CALL", "SELL_PUT"):
            opt_type_enum = OptionType.CALL if t.opt_type == "C" else OptionType.PUT
            strategy = OptionStrategy.COVERED_CALL if t.opt_type == "C" else OptionStrategy.CASH_SECURED_PUT
            contracts = int(t.cantidad)
            premium_per = t.precio_usd
            total_premium = round(contracts * 100 * premium_per, 2)

            # Si ya existe un Option abierto para el mismo contrato, consolidar contratos
            # (autoflush=False: flush previo para ver los que se acaban de agregar en este batch)
            db.flush()
            existing_opt = db.query(Option).filter(
                Option.stock_id == stk.id,
                Option.ticker == t.ticker,
                Option.strike_price == t.strike_price,
                Option.expiration_date == dt_exp,
                Option.option_type == opt_type_enum,
                Option.status == OptionStatus.OPEN,
            ).first()
            if existing_opt:
                existing_opt.contracts += contracts
                existing_opt.total_premium = round(existing_opt.total_premium + total_premium, 2)
                if existing_opt.contracts > 0:
                    existing_opt.premium_per_contract = round(
                        existing_opt.total_premium / (existing_opt.contracts * 100), 4
                    )
                continue

            new_opt = Option(
                stock_id=stk.id,
                ticker=t.ticker,
                option_type=opt_type_enum,
                strategy=strategy,
                strike_price=t.strike_price,
                contracts=contracts,
                premium_per_contract=premium_per,
                total_premium=total_premium,
                expiration_date=dt_exp,
                status=OptionStatus.OPEN,
                opened_at=dt_open,
            )
            db.add(new_opt)

        elif t.tipo in ("BUY_CALL", "BUY_PUT"):
            # Buscar la opción abierta correspondiente para cerrarla (total o parcialmente)
            opt_type_enum = OptionType.CALL if t.opt_type == "C" else OptionType.PUT
            open_opt = db.query(Option).filter(
                Option.stock_id == stk.id,
                Option.ticker == t.ticker,
                Option.strike_price == t.strike_price,
                Option.option_type == opt_type_enum,
                Option.status == OptionStatus.OPEN,
            ).first()
            if open_opt:
                try:
                    dt_close = datetime.strptime(t.fecha, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt_close = None
                closing_cost = t.total_usd
                contracts_closing = int(t.cantidad)

                if contracts_closing >= open_opt.contracts:
                    # Cierre total
                    per_share_premium = closing_cost / (open_opt.contracts * 100) if open_opt.contracts > 0 else 0.0
                    open_opt.status = OptionStatus.ASSIGNED if t.es_asignacion else OptionStatus.CLOSED
                    open_opt.closed_at = dt_close
                    open_opt.closing_premium = round(per_share_premium, 4)
                    open_opt.realized_pnl = round(open_opt.total_premium - closing_cost, 2)
                else:
                    # Cierre parcial: reducir contratos y prima proporcionalmente
                    ratio_closed = contracts_closing / open_opt.contracts
                    premium_closed = round(open_opt.total_premium * ratio_closed, 2)
                    partial_pnl = round(premium_closed - closing_cost, 2)
                    open_opt.contracts -= contracts_closing
                    open_opt.total_premium = round(open_opt.total_premium - premium_closed, 2)
                    # Acumular P&L realizado parcial en el campo realized_pnl
                    open_opt.realized_pnl = round((open_opt.realized_pnl or 0) + partial_pnl, 2)

    # ── Fase 3.5: marcar opciones expiradas ───────────────────────────
    for t in to_import:
        if t.tipo != "OPTION_EXPIRY":
            continue
        if not t.strike_price or not t.expiration_date:
            continue

        stk = db.query(Stock).filter(
            Stock.ticker == t.ticker,
            Stock.user_id == current_user.id,
        ).first()
        if not stk:
            continue

        try:
            dt_exp = datetime.strptime(t.fecha, "%Y-%m-%d %H:%M:%S")
            dt_exp_date = datetime.strptime(t.expiration_date, "%Y-%m-%d")
        except ValueError:
            continue

        opt_type_enum = OptionType.CALL if t.opt_type == "C" else OptionType.PUT
        open_opt = db.query(Option).filter(
            Option.stock_id == stk.id,
            Option.ticker == t.ticker,
            Option.strike_price == t.strike_price,
            Option.expiration_date == dt_exp_date,
            Option.option_type == opt_type_enum,
            Option.status == OptionStatus.OPEN,
        ).first()
        if open_opt:
            open_opt.status = OptionStatus.EXPIRED
            open_opt.closed_at = dt_exp
            open_opt.closing_premium = 0.0
            open_opt.realized_pnl = open_opt.total_premium

    # ── Fase 3.6: cerrar opciones asignadas ───────────────────────────
    for t in to_import:
        if t.tipo != "ASSIGNMENT":
            continue

        # Intentar extraer info de opción del símbolo (notas contienen el símbolo original)
        stk = db.query(Stock).filter(
            Stock.ticker == t.ticker,
            Stock.user_id == current_user.id,
        ).first()
        if not stk:
            continue

        try:
            dt_assign = datetime.strptime(t.fecha, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        # Find the earliest open option for this stock that could have been assigned
        # (expired or near expiration at assignment date)
        open_opt = (
            db.query(Option)
            .filter(
                Option.stock_id == stk.id,
                Option.status == OptionStatus.OPEN,
            )
            .order_by(Option.expiration_date)
            .first()
        )
        if open_opt:
            open_opt.status = OptionStatus.ASSIGNED
            open_opt.closed_at = dt_assign
            # Full premium earned on assignment (no closing cost)
            open_opt.realized_pnl = open_opt.total_premium

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar: {str(e)}")

    return ImportResult(
        importadas=importadas,
        omitidas=omitidas,
        stocks_creados=stocks_creados,
        stocks_actualizados=stocks_actualizados,
        errores=errores,
    )


# ─── Reconstruir posiciones desde transacciones ───────────────────────────────

@router.post("/rebuild-positions")
def rebuild_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Recalcula TODAS las posiciones (stocks) desde cero usando las transacciones
    almacenadas en orden cronológico. Útil cuando las importaciones se hicieron
    fuera de orden cronológico y los shares/average_cost quedaron incorrectos.

    Pasos:
      1. Elimina todos los registros de stocks del usuario
      2. Recorre transacciones ordenadas por fecha
      3. Reconstruye shares, average_cost, total_premium_earned correctamente
    """

    # ── 1. Obtener stocks existentes (no borrar: preservar FK de opciones) ─
    existing_stocks = {
        s.ticker: s
        for s in db.query(Stock).filter(Stock.user_id == current_user.id).all()
    }

    # ── 2. Obtener todas las transacciones en orden cronológico ───────────
    transactions = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.transaction_date)
        .all()
    )

    # Estado en memoria: ticker → dict acumulado
    positions: dict[str, dict] = {}

    for tx in transactions:
        ticker = tx.ticker
        qty = tx.quantity
        amount = tx.total_amount  # ya es positivo (proceeds o cost)
        tt = tx.transaction_type

        if tt == TransactionType.BUY_STOCK:
            if ticker not in positions:
                positions[ticker] = {
                    "shares": 0.0,
                    "total_cost": 0.0,
                    "average_cost": 0.0,
                    "total_premium_earned": 0.0,
                }
            pos = positions[ticker]
            # Weighted average cost
            new_total_shares = pos["shares"] + qty
            new_total_cost = pos["total_cost"] + amount
            pos["shares"] = new_total_shares
            pos["total_cost"] = new_total_cost
            pos["average_cost"] = new_total_cost / new_total_shares if new_total_shares > 0 else 0.0

        elif tt == TransactionType.SELL_STOCK:
            if ticker not in positions:
                # Vendido antes de tener registro de compra (ej: año incompleto)
                positions[ticker] = {
                    "shares": 0.0,
                    "total_cost": 0.0,
                    "average_cost": 0.0,
                    "total_premium_earned": 0.0,
                }
            pos = positions[ticker]
            pos["shares"] = max(0.0, pos["shares"] - qty)
            # Reducir total_cost proporcionalmente
            if (pos["shares"] + qty) > 0:
                pos["total_cost"] = pos["average_cost"] * pos["shares"]

        elif tt in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            if ticker not in positions:
                positions[ticker] = {
                    "shares": 0.0,
                    "total_cost": 0.0,
                    "average_cost": 0.0,
                    "total_premium_earned": 0.0,
                }
            positions[ticker]["total_premium_earned"] += amount

        elif tt in (TransactionType.BUY_CALL, TransactionType.BUY_PUT):
            if ticker in positions:
                positions[ticker]["total_premium_earned"] = max(
                    0.0, positions[ticker]["total_premium_earned"] - amount
                )

        # OPTION_EXPIRY: la opción expiró sin valor — el premium completo ya fue ganado,
        # no se descuenta nada (amount=0). Solo asegurar que el ticker esté en positions.
        elif tt == TransactionType.OPTION_EXPIRY:
            if ticker not in positions:
                positions[ticker] = {
                    "shares": 0.0,
                    "total_cost": 0.0,
                    "average_cost": 0.0,
                    "total_premium_earned": 0.0,
                }

    # ── 3. Actualizar o crear registros de stocks (upsert) ────────────────
    created = []
    skipped = []

    for ticker, pos in positions.items():
        shares = round(pos["shares"], 6)
        avg_cost = round(pos["average_cost"], 4)
        premium = round(pos["total_premium_earned"], 2)
        total_invested = round(shares * avg_cost, 2)
        is_active = shares > 0.0001

        if shares > 0 and premium > 0:
            adjusted = round(avg_cost - (premium / shares), 4)
        else:
            adjusted = avg_cost

        if ticker in existing_stocks:
            s = existing_stocks[ticker]
            s.shares = shares
            s.average_cost = avg_cost
            s.total_invested = total_invested
            s.total_premium_earned = premium
            s.adjusted_cost_basis = adjusted
            s.is_active = is_active
        else:
            company_name = ticker
            try:
                info = MarketDataService.get_stock_info(ticker)
                if info:
                    company_name = info.get("company_name", ticker)
            except Exception:
                pass

            new_stock = Stock(
                user_id=current_user.id,
                ticker=ticker,
                company_name=company_name,
                shares=shares,
                average_cost=avg_cost,
                total_invested=total_invested,
                total_premium_earned=premium,
                adjusted_cost_basis=adjusted,
                is_active=is_active,
            )
            db.add(new_stock)
        created.append(ticker)

    # Marcar como inactivos los tickers que no aparecen en transacciones
    for ticker, stk in existing_stocks.items():
        if ticker not in positions:
            stk.shares = 0
            stk.total_invested = 0
            stk.is_active = False

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al reconstruir: {str(e)}")

    active = [t for t in created if positions[t]["shares"] > 0.0001]
    closed = [t for t in created if positions[t]["shares"] <= 0.0001]

    return {
        "ok": True,
        "tickers_reconstruidos": len(created),
        "posiciones_activas": active,
        "posiciones_cerradas": closed,
        "total_transacciones_procesadas": len(transactions),
    }
