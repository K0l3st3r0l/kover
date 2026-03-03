"""
Importador de Interactive Brokers Activity Statement
------------------------------------------------------
Soporta el formato CSV exportado desde:
  IB Client Portal / TWS → Reports → Activity → Statements → Format: CSV

Las secciones que se procesan:
  - Trades       → acciones (Stocks) y opciones (Equity and Index Options)
  - Dividends    → dividendos
  - Corporate Actions con "Assignment" → asignaciones

Cómo exportar desde IB:
  1. Ir a Reports → Activity → Statements
  2. Tipo: Activity
  3. Período: el año que quieres importar
  4. Formato: CSV → Download
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
import csv
import io
import re

from ..database import get_db
from ..models import Transaction, TransactionType, Stock, Option, OptionType, OptionStrategy, OptionStatus, User
from ..utils.auth import get_current_user
from ..market.market_data import MarketDataService

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
    "BUY_STOCK":  "Compra Acción",
    "SELL_STOCK": "Venta Acción",
    "SELL_CALL":  "Prima Covered Call",
    "BUY_CALL":   "Cierre Call",
    "SELL_PUT":   "Prima Cash-Secured Put",
    "BUY_PUT":    "Cierre Put",
    "DIVIDEND":   "Dividendo",
    "ASSIGNMENT": "Asignación",
}


def parse_float(value: str) -> float:
    """Parsea un número que puede tener comas como separador de miles."""
    try:
        return float(value.replace(",", "").strip())
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
                "comm_fee": parse_float(comm_str),
                "description": "",
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
                "comm_fee": parse_float(comm_str),
                "description": description,
            })

    return rows, errors


def build_parsed_transactions(
    raw_rows: list[dict],
    existing_hashes: set,
) -> tuple[list[ParsedTransaction], list[str]]:
    """
    Convierte las filas crudas en ParsedTransaction.
    existing_hashes: set de (ticker, fecha_str, tipo, total) ya en BD → para detectar duplicados.
    """
    results: list[ParsedTransaction] = []
    errors: list[str] = []

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
            # Intentar extraer ticker del símbolo de opción
            opt_info = parse_ib_option_symbol(symbol)
            ticker = opt_info[0] if opt_info else symbol.upper()
            tipo = TransactionType.ASSIGNMENT
            total_usd = abs(raw["proceeds"])
            cantidad = abs(raw["quantity"])
            precio = raw["t_price"]
            notas = raw.get("description", "Assignment IB")

        # ── Trade (acción u opción) ─────────────────────────────────────────
        else:
            asset_cat = raw["asset_category"]
            quantity = raw["quantity"]

            if "option" in asset_cat.lower():
                opt_info = parse_ib_option_symbol(symbol)
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
            else:
                ticker = symbol.upper()
                opt_type = None
                tipo = determine_transaction_type(asset_cat, quantity, opt_type)
                total_usd = abs(raw["proceeds"])
                cantidad = abs(quantity)
                precio = abs(raw["t_price"])
                notas = "Importado desde IB"
                _strike = None
                _expiry = None
                _opt_type = None

            # Advertir si precio es 0
            if precio == 0 and tipo not in (TransactionType.DIVIDEND, TransactionType.ASSIGNMENT):
                advertencia = "Precio T. Price = 0, verifica el registro."

        comision = abs(raw.get("comm_fee", 0.0))

        # Detectar duplicado usando una firma de la operación
        sig = (ticker, dt.strftime("%Y-%m-%d"), tipo.value, round(total_usd, 2), round(cantidad, 4))
        duplicado = sig in existing_hashes

        results.append(ParsedTransaction(
            ib_row=line,
            fecha=fecha_iso,
            ticker=ticker,
            tipo=tipo.value,
            tipo_label=TIPO_LABELS.get(tipo.value, tipo.value),
            asset_category=raw["asset_category"],
            cantidad=cantidad,
            precio_usd=round(precio, 4),
            total_usd=round(total_usd, 2),
            comision_usd=round(comision, 4),
            notas=notas,
            advertencia=advertencia,
            duplicado=duplicado,
            strike_price=_strike if section == "Trades" else None,
            expiration_date=_expiry if section == "Trades" else None,
            opt_type=_opt_type if section == "Trades" else None,
        ))

    return results, errors


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

    # Construir set de firmas existentes en BD para detectar duplicados
    existing_txs = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .all()
    )
    existing_hashes: set = set()
    for t in existing_txs:
        sig = (
            t.ticker,
            t.transaction_date.strftime("%Y-%m-%d"),
            t.transaction_type.value,
            round(abs(t.total_amount), 2),
            round(t.quantity, 4),
        )
        existing_hashes.add(sig)

    parsed, build_errors = build_parsed_transactions(raw_rows, existing_hashes)
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
            # Actualizar posición existente (weighted average)
            if total_shares_bought > 0:
                prev_total = existing_stock.shares * existing_stock.average_cost
                new_total = existing_stock.shares + total_shares_bought
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
                          "SELL_PUT", "BUY_PUT", "DIVIDEND", "ASSIGNMENT"):
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
            # Verificar si ya existe un Option idéntico (evitar duplicados)
            existing_opt = db.query(Option).filter(
                Option.stock_id == stk.id,
                Option.ticker == t.ticker,
                Option.strike_price == t.strike_price,
                Option.expiration_date == dt_exp,
                Option.status == OptionStatus.OPEN,
            ).first()
            if existing_opt:
                continue

            opt_type_enum = OptionType.CALL if t.opt_type == "C" else OptionType.PUT
            strategy = OptionStrategy.COVERED_CALL if t.opt_type == "C" else OptionStrategy.CASH_SECURED_PUT
            contracts = int(t.cantidad)
            premium_per = t.precio_usd
            total_premium = round(contracts * 100 * premium_per, 2)

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
            # Buscar la opción abierta correspondiente para cerrarla
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
                # closing_premium se almacena por acción (igual que options.py): total / (contracts × 100)
                per_share_premium = closing_cost / (open_opt.contracts * 100) if open_opt.contracts > 0 else 0.0
                open_opt.status = OptionStatus.CLOSED
                open_opt.closed_at = dt_close
                open_opt.closing_premium = round(per_share_premium, 4)
                open_opt.realized_pnl = round(open_opt.total_premium - closing_cost, 2)

    # ── Fase 3.5: cerrar opciones asignadas ───────────────────────────
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
