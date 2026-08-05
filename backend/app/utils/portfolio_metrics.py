"""Pure accounting helpers used by portfolio analytics endpoints."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

SELL_TYPES = frozenset({"SELL_CALL", "SELL_PUT"})
BUY_TYPES = frozenset({"BUY_CALL", "BUY_PUT"})
OPTION_TRANSACTION_TYPES = SELL_TYPES | BUY_TYPES

# Un cierre puede quedar fechado en la expiración o en la liquidación, que IB
# reporta con hasta un par de días de diferencia. Solo se usa en la segunda
# pasada del matching, cuando la ventana estricta no encontró dueño.
MATCH_DATE_MARGIN_DAYS = 3


def annualize_simple_premium(net_premium: float, capital: float, duration_days: int) -> float:
    """Return a descriptive linear annualization, never a portfolio return."""
    if capital <= 0 or duration_days <= 0:
        return 0.0
    premium_yield = net_premium / capital * 100
    return round(premium_yield * 365 / duration_days, 2)


def split_option_premium(
    *,
    status: Any,
    total_premium: float,
    closing_cost: float = 0.0,
    realized_pnl: float | None = None,
) -> tuple[float, float]:
    """Return (realized_net_premium, still_open_premium) for one option row."""
    status_value = getattr(status, "value", status)
    if status_value == "OPEN":
        return round(float(realized_pnl or 0.0), 2), round(float(total_premium or 0.0), 2)
    realized = realized_pnl if realized_pnl is not None else float(total_premium or 0.0) - float(closing_cost or 0.0)
    return round(float(realized), 2), 0.0


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _as_date(value: Any) -> date | None:
    """Normalize to a calendar date in UTC, so the session timezone cannot shift it."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_iso(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


_STRIKE_RE = re.compile(r"Strike\s*\$?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_EXPIRY_RE = re.compile(r"Exp\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def describe_transaction(transaction: Any) -> dict[str, Any]:
    """Parse a transaction once so matching never re-runs the regexes per option."""
    transaction_type = _enum_value(_value(transaction, "transaction_type"))
    notes = str(_value(transaction, "notes", "") or "")
    strike_match = _STRIKE_RE.search(notes)
    expiry_match = _EXPIRY_RE.search(notes)
    try:
        strike = float(strike_match.group(1)) if strike_match else None
    except (TypeError, ValueError):
        strike = None
    return {
        "id": _value(transaction, "id"),
        "option_id": _value(transaction, "option_id"),
        "ticker": str(_value(transaction, "ticker", "") or "").upper(),
        "transaction_type": transaction_type,
        "side": 1 if transaction_type in SELL_TYPES else -1,
        "amount": abs(float(_value(transaction, "total_amount", 0.0) or 0.0)),
        "commission": abs(float(_value(transaction, "commission", 0.0) or 0.0)),
        "quantity": abs(float(_value(transaction, "quantity", 0.0) or 0.0)),
        "date": _as_date(_value(transaction, "transaction_date")),
        "strike": strike,
        "expiry": expiry_match.group(1) if expiry_match else None,
    }


def describe_option(option: Any) -> dict[str, Any]:
    """Parse an option row once, including the window that bounds its own cycle."""
    strike = _value(option, "strike_price")
    try:
        strike = float(strike) if strike is not None else None
    except (TypeError, ValueError):
        strike = None
    expiry = _date_iso(_value(option, "expiration_date"))
    ticker = str(_value(option, "ticker", "") or "").upper()
    return {
        "id": _value(option, "id"),
        "ticker": ticker,
        "strike": strike,
        "expiry": expiry,
        "signature": (ticker, strike, expiry),
        "status": _enum_value(_value(option, "status")),
        "contracts": float(_value(option, "contracts", 0.0) or 0.0),
        "total_premium": float(_value(option, "total_premium", 0.0) or 0.0),
        "closing_premium": float(_value(option, "closing_premium", 0.0) or 0.0),
        "realized_pnl": _value(option, "realized_pnl"),
        "opened": _as_date(_value(option, "opened_at")),
        "closed": _as_date(_value(option, "closed_at")),
        "raw_status": _value(option, "status"),
    }


def _metadata_matches(tx_meta: Mapping[str, Any], opt_meta: Mapping[str, Any]) -> bool:
    if not tx_meta["ticker"] or tx_meta["ticker"] != opt_meta["ticker"]:
        return False
    if tx_meta["strike"] is None or opt_meta["strike"] is None:
        return False
    if abs(tx_meta["strike"] - opt_meta["strike"]) > 1e-9:
        return False
    return tx_meta["expiry"] is not None and tx_meta["expiry"] == opt_meta["expiry"]


def _within_window(tx_meta: Mapping[str, Any], opt_meta: Mapping[str, Any], margin_days: int) -> bool:
    """Keep a transaction inside the cycle it belongs to.

    Without this, two option rows sharing ticker/strike/expiry (sell → buy to
    close → sell again) let the first row swallow every transaction while the
    second falls back to its own raw values, double counting the premium.
    """
    tx_date = tx_meta["date"]
    if tx_date is None:
        return True
    margin = timedelta(days=margin_days)
    opened = opt_meta["opened"]
    closed = opt_meta["closed"]
    if opened is not None and tx_date < opened - margin:
        return False
    if closed is not None and tx_date > closed + margin:
        return False
    return True


def _window_distance(tx_meta: Mapping[str, Any], opt_meta: Mapping[str, Any]) -> int:
    """Days between the transaction and the option's opening, to break ties."""
    tx_date = tx_meta["date"]
    opened = opt_meta["opened"]
    if tx_date is None or opened is None:
        return 0
    return abs((tx_date - opened).days)


def transaction_matches_option(transaction: Any, option: Any) -> bool:
    """Match a single transaction to an option by option_id or exact note metadata."""
    tx_meta = describe_transaction(transaction)
    opt_meta = describe_option(option)
    if opt_meta["id"] is not None and tx_meta["option_id"] == opt_meta["id"]:
        return True
    if tx_meta["option_id"] is not None:
        return False
    return _metadata_matches(tx_meta, opt_meta) and _within_window(tx_meta, opt_meta, MATCH_DATE_MARGIN_DAYS)


def build_option_transaction_ledger(options: Iterable[Any], transactions: Iterable[Any]) -> dict[str, Any]:
    """Reconcile option rows with imported cash-flow transactions without mutating data."""
    opts = [describe_option(option) for option in options]
    txs = [
        describe_transaction(transaction)
        for transaction in transactions
        if _enum_value(_value(transaction, "transaction_type")) in OPTION_TRANSACTION_TYPES
    ]

    owner: dict[int, int] = {}

    # Pasada 0 — option_id explícito: lo escribe la UI y es autoritativo.
    options_by_id = {opt["id"]: index for index, opt in enumerate(opts) if opt["id"] is not None}
    for tx_index, tx_meta in enumerate(txs):
        if tx_meta["option_id"] is not None and tx_meta["option_id"] in options_by_id:
            owner[tx_index] = options_by_id[tx_meta["option_id"]]

    # Pasadas 1 y 2 — metadata de las notas, primero con la ventana estricta del
    # ciclo y solo después con margen de liquidación.
    for margin in (0, MATCH_DATE_MARGIN_DAYS):
        for tx_index, tx_meta in enumerate(txs):
            if tx_index in owner or tx_meta["option_id"] is not None:
                continue
            candidates = [
                (_window_distance(tx_meta, opt_meta), opt_index)
                for opt_index, opt_meta in enumerate(opts)
                if _metadata_matches(tx_meta, opt_meta) and _within_window(tx_meta, opt_meta, margin)
            ]
            if candidates:
                candidates.sort()
                owner[tx_index] = candidates[0][1]

    matched_by_option: dict[int, list[int]] = defaultdict(list)
    for tx_index, opt_index in owner.items():
        matched_by_option[opt_index].append(tx_index)

    claimed_signatures = {opts[opt_index]["signature"] for opt_index in matched_by_option}

    options_ledger: list[dict[str, Any]] = []
    for opt_index, opt_meta in enumerate(opts):
        matched = [txs[tx_index] for tx_index in sorted(matched_by_option.get(opt_index, []))]

        raw_closing_cost = 0.0 if opt_meta["status"] == "OPEN" else (
            opt_meta["closing_premium"] * opt_meta["contracts"] * 100
        )
        raw_realized, raw_open = split_option_premium(
            status=opt_meta["raw_status"],
            total_premium=opt_meta["total_premium"],
            closing_cost=raw_closing_cost,
            realized_pnl=opt_meta["realized_pnl"],
        )

        transaction_net = None
        realized_net = raw_realized
        open_net = raw_open
        commissions = 0.0
        sold_contracts = 0.0
        contracts = opt_meta["contracts"]

        if matched:
            transaction_net = round(sum(tx["side"] * tx["amount"] for tx in matched), 2)
            commissions = round(sum(tx["commission"] for tx in matched), 2)
            sold_contracts = sum(tx["quantity"] for tx in matched if tx["side"] > 0)
            # Un cierre parcial reduce `contracts` en la fila, pero el ledger
            # sigue cubriendo el tamaño original: el denominador tiene que
            # hablar del mismo tamaño que el numerador.
            contracts = max(contracts, sold_contracts) if sold_contracts else contracts
            if opt_meta["status"] == "OPEN":
                realized_net = round(float(opt_meta["realized_pnl"] or 0.0), 2)
                open_net = round(transaction_net - realized_net, 2)
            else:
                realized_net = transaction_net
                open_net = 0.0

        # Sin match, pero otra fila con la misma terna sí consumió transacciones:
        # el fallback a los valores crudos duplicaría esa prima.
        ambiguous = not matched and opt_meta["signature"] in claimed_signatures

        options_ledger.append({
            "option_id": opt_meta["id"],
            "ticker": opt_meta["ticker"],
            "transaction_net": transaction_net,
            "raw_net": round(raw_realized + raw_open, 2),
            "realized_net": round(realized_net, 2),
            "open_net": round(open_net, 2),
            "commissions": commissions,
            "contracts": contracts,
            "row_contracts": opt_meta["contracts"],
            "sold_contracts": sold_contracts,
            "matched": bool(matched),
            "ambiguous": ambiguous,
            "premium_source": "TRANSACTIONS_EXACT" if matched else (
                "OPTION_ROW_AMBIGUOUS" if ambiguous else "OPTION_ROW_FALLBACK"
            ),
            "matched_transaction_ids": [tx["id"] for tx in matched],
        })

    unmatched_transaction_ids = [
        tx["id"] for tx_index, tx in enumerate(txs) if tx_index not in owner
    ]
    return {
        "options": options_ledger,
        "unmatched_transaction_ids": unmatched_transaction_ids,
        "matched_transaction_ids": sorted(
            (txs[tx_index]["id"] for tx_index in owner if txs[tx_index]["id"] is not None),
        ),
        "ambiguous_option_ids": [row["option_id"] for row in options_ledger if row["ambiguous"]],
    }


def premium_by_ticker(ledger: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Aggregate the canonical premium per ticker, for per-position endpoints."""
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"realized": 0.0, "open": 0.0, "commissions": 0.0, "net_of_fees": 0.0}
    )
    for row in ledger["options"]:
        bucket = totals[row["ticker"]]
        bucket["realized"] += row["realized_net"]
        bucket["open"] += row["open_net"]
        bucket["commissions"] += row["commissions"]
    for bucket in totals.values():
        bucket["realized"] = round(bucket["realized"], 2)
        bucket["open"] = round(bucket["open"], 2)
        bucket["commissions"] = round(bucket["commissions"], 2)
        bucket["net_of_fees"] = round(bucket["realized"] + bucket["open"] - bucket["commissions"], 2)
    return dict(totals)


def summarize_cycles(cycles: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Separate closed/open premium and describe the cycle-average metric."""
    rows = list(cycles)
    closed = [row for row in rows if row.get("status") != "OPEN"]
    opened = [row for row in rows if row.get("status") == "OPEN"]

    def total(rows_: list[Mapping[str, Any]], field: str) -> float:
        return round(sum(float(row.get(field) or 0.0) for row in rows_), 2)

    def average(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    closed_annualized = [float(row.get("annualized_return") or 0.0) for row in closed]
    closed_annualized_gross = [float(row.get("annualized_return_gross") or 0.0) for row in closed]
    all_annualized = [float(row.get("annualized_return") or 0.0) for row in rows]
    positive = sum(1 for row in closed if float(row.get("net_premium_net_of_fees") or 0.0) > 0)
    negative = sum(1 for row in closed if float(row.get("net_premium_net_of_fees") or 0.0) < 0)
    breakeven = len(closed) - positive - negative

    closed_net = total(closed, "net_premium")
    open_net = total(opened, "net_premium")
    closed_commissions = total(closed, "commissions")
    open_commissions = total(opened, "commissions")
    summary: dict[str, Any] = {
        "total_cycles": len(rows),
        "closed_cycles": len(closed),
        "avg_annualized_return": average(all_annualized),
        "avg_closed_annualized": average(closed_annualized),
        "avg_closed_annualized_gross": average(closed_annualized_gross),
        "closed_net_premium": closed_net,
        "open_net_premium": open_net,
        "total_net_premium": round(closed_net + open_net, 2),
        "closed_commissions": closed_commissions,
        "open_commissions": open_commissions,
        "total_commissions": round(closed_commissions + open_commissions, 2),
        "closed_net_premium_after_fees": round(closed_net - closed_commissions, 2),
        "total_net_premium_after_fees": round(closed_net + open_net - closed_commissions - open_commissions, 2),
        "closed_positive_cycles": positive,
        "closed_negative_cycles": negative,
        "closed_breakeven_cycles": breakeven,
        "closed_win_rate": round(positive / len(closed) * 100, 2) if closed else 0.0,
        "capital_deployed": round(sum(float(row.get("capital") or 0.0) for row in opened), 2),
        "open_cycles": [
            {
                "ticker": row.get("ticker"),
                "annualized": row.get("annualized_return"),
                "capital": row.get("capital"),
            }
            for row in opened
        ],
        "current_cycle_annualized": opened[-1].get("annualized_return") if opened else None,
        "annualized_metric": "simple_average_of_linear_cycle_premium_annualizations_net_of_fees",
        "annualized_is_portfolio_return": False,
    }
    return summary


def calculate_total_return_breakdown(
    *,
    stock_realized_pnl: float,
    stock_unrealized_pnl: float,
    closed_option_pnl: float,
    open_option_premium: float,
    dividends: float,
    commissions: float,
) -> dict[str, float]:
    """Build a marked stock + closed-option return without pretending open options are realized."""
    realized_total = stock_realized_pnl + closed_option_pnl + dividends - commissions
    marked_total = realized_total + stock_unrealized_pnl
    return {
        "realized_total_pnl": round(realized_total, 2),
        "mark_to_market_total_pnl": round(marked_total, 2),
        "open_option_premium": round(open_option_premium, 2),
    }
