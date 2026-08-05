from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Stock, Option, Transaction, TransactionType, OptionStatus
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService
from ..utils import OptionsCalculator
from ..services.premium_ledger import load_option_ledger, load_premium_by_ticker
from ..utils.portfolio_metrics import calculate_total_return_breakdown

router = APIRouter()

@router.get("/summary")
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener resumen general del portafolio"""
    
    # Total de acciones activas del usuario
    stocks = db.query(Stock).filter(
        Stock.user_id == current_user.id,
        Stock.is_active == True
    ).all()
    total_stocks = len(stocks)
    
    # Obtener precios actuales
    tickers = [s.ticker for s in stocks]
    prices = MarketDataService.get_multiple_prices(tickers) if tickers else {}
    
    # Calcular valores totales
    total_invested = sum(s.total_invested for s in stocks)
    
    current_portfolio_value = 0
    total_unrealized_pnl = 0
    
    for stock in stocks:
        current_price = prices.get(stock.ticker)
        if current_price:
            current_value = current_price * stock.shares
            current_portfolio_value += current_value
            total_unrealized_pnl += current_value - stock.total_invested
        else:
            current_portfolio_value += stock.total_invested
    
    # Opciones abiertas: suma de contratos (no cantidad de registros)
    from sqlalchemy import func as _func
    open_options = db.query(_func.coalesce(_func.sum(Option.contracts), 0)).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status == OptionStatus.OPEN
    ).scalar() or 0
    
    # P&L realizado de ventas de acciones usando costo promedio histórico
    from collections import defaultdict
    all_txs_ordered = db.query(Transaction).filter(
        Transaction.user_id == current_user.id
    ).order_by(Transaction.transaction_date, Transaction.id).all()
    stock_txs = [
        tx for tx in all_txs_ordered
        if tx.transaction_type in (TransactionType.BUY_STOCK, TransactionType.SELL_STOCK)
    ]
    _running_shares: dict = defaultdict(float)
    _running_cost: dict = defaultdict(float)
    realized_stock_pnl = 0.0
    total_capital_deployed = 0.0
    for tx in stock_txs:
        if tx.transaction_type == TransactionType.BUY_STOCK:
            qty = float(tx.quantity or 0)
            total_amount = abs(float(tx.total_amount or 0))
            _running_shares[tx.ticker] += qty
            _running_cost[tx.ticker] += total_amount
            total_capital_deployed += total_amount
        elif _running_shares[tx.ticker] > 0:
            requested_qty = float(tx.quantity or 0)
            qty = min(requested_qty, _running_shares[tx.ticker])
            proceeds = abs(float(tx.total_amount or 0))
            if requested_qty > 0 and qty < requested_qty:
                proceeds *= qty / requested_qty
            avg = _running_cost[tx.ticker] / _running_shares[tx.ticker]
            cost_basis = avg * qty
            realized_stock_pnl += proceeds - cost_basis
            _running_shares[tx.ticker] = max(0.0, _running_shares[tx.ticker] - qty)
            _running_cost[tx.ticker] = max(0.0, _running_cost[tx.ticker] - cost_basis)

    total_commissions = sum(abs(float(tx.commission or 0.0)) for tx in all_txs_ordered)
    dividends = sum(
        float(tx.total_amount or 0.0)
        for tx in all_txs_ordered
        if tx.transaction_type == TransactionType.DIVIDEND
    )

    _, option_ledger = load_option_ledger(db, current_user.id, all_txs_ordered)
    closed_option_pnl = sum(row["realized_net"] for row in option_ledger["options"])
    open_option_premium = sum(row["open_net"] for row in option_ledger["options"])
    option_commissions = round(sum(row["commissions"] for row in option_ledger["options"]), 2)

    return_breakdown = calculate_total_return_breakdown(
        stock_realized_pnl=realized_stock_pnl,
        stock_unrealized_pnl=total_unrealized_pnl,
        closed_option_pnl=closed_option_pnl,
        open_option_premium=open_option_premium,
        dividends=dividends,
        commissions=total_commissions,
    )
    total_premium_earned = closed_option_pnl
    total_pnl = return_breakdown["mark_to_market_total_pnl"]

    # ROI histórico: ratio descriptivo sobre compras; no es TWR/MWR.
    roi_historical_pct = (total_pnl / total_capital_deployed * 100) if total_capital_deployed > 0 else 0

    # ROI actual: P&L precio puro / capital activo invertido
    roi_current_pct = (total_unrealized_pnl / total_invested * 100) if total_invested > 0 else 0

    # Mantener total_pnl_pct = histórico (para compatibilidad)
    total_pnl_pct = roi_historical_pct

    return {
        "total_stocks": total_stocks,
        "total_invested": round(total_invested, 2),
        "total_capital_deployed": round(total_capital_deployed, 2),
        "current_portfolio_value": round(current_portfolio_value, 2),
        "total_premium_earned": round(total_premium_earned, 2),
        "open_option_premium": round(open_option_premium, 2),
        "option_commissions": option_commissions,
        "total_premium_net_of_fees": round(total_premium_earned - option_commissions, 2),
        "dividends": round(dividends, 2),
        "commissions": round(total_commissions, 2),
        "open_options": open_options,
        "ledger_status": "RECONCILED" if (
            not option_ledger["unmatched_transaction_ids"]
            and not option_ledger["ambiguous_option_ids"]
        ) else "REVIEW_REQUIRED",
        "realized_pnl": round(total_premium_earned, 2),  # compat: primas netas cerradas
        "realized_stock_pnl": round(realized_stock_pnl, 2),
        "unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_scope": "mark_to_market_excludes_open_option_fair_value_over_historical_stock_buys",
        "total_pnl_pct": round(total_pnl_pct, 2),
        "roi_historical_pct": round(roi_historical_pct, 2),
        "roi_current_pct": round(roi_current_pct, 2),
    }

@router.get("/positions")
def get_positions_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener vista general de todas las posiciones con precios actuales"""
    
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id, Stock.is_active == True).all()
    tickers = [s.ticker for s in stocks]
    prices = MarketDataService.get_multiple_prices(tickers) if tickers else {}
    premiums = load_premium_by_ticker(db, current_user.id)

    positions = []
    for stock in stocks:
        current_price = prices.get(stock.ticker)

        bucket = premiums.get(stock.ticker, {})
        premium_realized = bucket.get("realized", 0.0)
        premium_net = round(premium_realized - bucket.get("commissions", 0.0), 2)
        adjusted_cost_basis = round(
            stock.average_cost - (premium_net / stock.shares), 4
        ) if stock.shares > 0 else stock.average_cost

        position_data = {
            "id": stock.id,
            "ticker": stock.ticker,
            "company_name": stock.company_name,
            "shares": stock.shares,
            "average_cost": stock.average_cost,
            "adjusted_cost_basis": adjusted_cost_basis,
            "stored_adjusted_cost_basis": stock.adjusted_cost_basis,
            "total_invested": stock.total_invested,
            "total_premium_earned": premium_net,
            "premium_realized": premium_realized,
            "premium_open": bucket.get("open", 0.0),
            "premium_commissions": bucket.get("commissions", 0.0),
            "current_price": current_price,
        }

        if current_price:
            pnl = OptionsCalculator.calculate_position_pnl(
                stock.shares,
                adjusted_cost_basis,
                current_price
            )
            position_data.update(pnl)
        
        # Contar opciones abiertas para esta acción
        open_options_count = db.query(Option).filter(
            Option.stock_id == stock.id,
            Option.status == OptionStatus.OPEN
        ).count()
        
        position_data["open_options"] = open_options_count
        
        positions.append(position_data)
    
    return positions
