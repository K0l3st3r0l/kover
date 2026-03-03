from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List
from datetime import datetime, timedelta, date
import math
from ..database import get_db
from ..models import Stock, Option, Transaction, TransactionType, User, OptionStatus, OptionStrategy
from ..utils.auth import get_current_user
from ..market.market_data import MarketDataService

router = APIRouter()

@router.get("/portfolio-history")
async def get_portfolio_history(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener el historial del valor del portafolio.
    - "invested": costo base neto del portafolio en cada fecha (considera TODO el historial)
    - "portfolio_value": valor de mercado actual de las posiciones activas (precio actual × shares)
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # Todas las transacciones del usuario, ordenadas
    all_transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id
    ).order_by(Transaction.transaction_date).all()

    active_stocks = db.query(Stock).filter(
        Stock.user_id == current_user.id, Stock.is_active == True
    ).all()

    # Valor de mercado actual (constante para todo el gráfico — no tenemos precios históricos)
    current_market_value = 0.0
    for stock in active_stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        current_market_value += (current_price * stock.shares) if current_price else stock.total_invested

    # ── Calcular costo base acumulado al inicio de la ventana ──────────────
    # Recorremos todas las transacciones ANTERIORES a start_date para obtener
    # el costo base real del portafolio en ese momento.
    positions: dict = {}  # ticker → {shares, total_cost}

    def _apply_tx(tx, pos):
        """Actualiza el dict de posiciones para una transacción."""
        t = tx.ticker
        if t not in pos:
            pos[t] = {"shares": 0.0, "total_cost": 0.0}
        p = pos[t]
        if tx.transaction_type == TransactionType.BUY_STOCK:
            p["shares"] += tx.quantity
            p["total_cost"] += tx.total_amount
        elif tx.transaction_type == TransactionType.SELL_STOCK:
            if p["shares"] > 0:
                avg = p["total_cost"] / p["shares"]
                sell_qty = min(tx.quantity, p["shares"])
                p["shares"] = max(0.0, p["shares"] - sell_qty)
                p["total_cost"] = max(0.0, p["total_cost"] - avg * sell_qty)

    for tx in all_transactions:
        if tx.transaction_date.date() >= start_date.date():
            break
        _apply_tx(tx, positions)

    baseline_invested = sum(p["total_cost"] for p in positions.values())

    # ── Construir historial día a día dentro de la ventana ─────────────────
    history = []
    current_date = start_date
    cumulative_invested = baseline_invested

    while current_date <= end_date:
        day_tx = [t for t in all_transactions if t.transaction_date.date() == current_date.date()]

        for tx in day_tx:
            t = tx.ticker
            if t not in positions:
                positions[t] = {"shares": 0.0, "total_cost": 0.0}
            p = positions[t]
            if tx.transaction_type == TransactionType.BUY_STOCK:
                p["shares"] += tx.quantity
                p["total_cost"] += tx.total_amount
                cumulative_invested += tx.total_amount
            elif tx.transaction_type == TransactionType.SELL_STOCK:
                if p["shares"] > 0:
                    avg = p["total_cost"] / p["shares"]
                    sell_qty = min(tx.quantity, p["shares"])
                    sold_cost = avg * sell_qty
                    p["shares"] = max(0.0, p["shares"] - sell_qty)
                    p["total_cost"] = max(0.0, p["total_cost"] - sold_cost)
                    cumulative_invested = max(0.0, cumulative_invested - sold_cost)

        invested = round(cumulative_invested, 2)
        history.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "portfolio_value": round(current_market_value, 2),
            "invested": invested,
            "pnl": round(current_market_value - invested, 2)
        })

        current_date += timedelta(days=1)

    return history

@router.get("/performance-metrics")
async def get_performance_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Métricas de rendimiento del portafolio
    """
    from collections import defaultdict

    active_stocks = db.query(Stock).filter(Stock.user_id == current_user.id, Stock.is_active == True).all()
    options = db.query(Option).join(Stock).filter(Stock.user_id == current_user.id).all()

    # ── Capital actualmente invertido y valor de mercado ──────────────────────
    total_invested = sum(stock.total_invested for stock in active_stocks)
    current_portfolio_value = 0.0
    for stock in active_stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        current_portfolio_value += (current_price * stock.shares) if current_price else stock.total_invested

    # P&L no realizado: solo posiciones abiertas, sin premiums
    unrealized_pnl = current_portfolio_value - total_invested
    roi_unrealized = (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0

    # ── Premiums netos históricos (todas las posiciones, cerradas y abiertas) ──
    all_stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    total_premium = sum(s.total_premium_earned or 0.0 for s in all_stocks)

    # ── P&L realizado en acciones (ventas históricas con costo base histórico) ─
    all_txns = (
        db.query(Transaction)
        .join(Stock)
        .filter(
            Stock.user_id == current_user.id,
            Transaction.transaction_type.in_([TransactionType.BUY_STOCK, TransactionType.SELL_STOCK])
        )
        .order_by(Transaction.transaction_date)
        .all()
    )
    running_qty: dict = defaultdict(float)
    running_cost: dict = defaultdict(float)
    realized_stock_pnl = 0.0
    total_capital_deployed = 0.0

    for txn in all_txns:
        ticker = txn.ticker
        if txn.transaction_type == TransactionType.BUY_STOCK:
            qty = txn.quantity or 0
            cost = abs(txn.total_amount or 0)
            total_capital_deployed += cost
            running_cost[ticker] += cost
            running_qty[ticker] += qty
        elif txn.transaction_type == TransactionType.SELL_STOCK:
            qty = txn.quantity or 0
            proceeds = abs(txn.total_amount or 0)
            commission = abs(txn.commission or 0)
            if running_qty[ticker] > 0:
                avg_cost_per_share = running_cost[ticker] / running_qty[ticker]
                cost_basis = avg_cost_per_share * qty
                realized_stock_pnl += (proceeds - commission) - cost_basis
                running_cost[ticker] -= avg_cost_per_share * qty
                running_qty[ticker] -= qty

    # ── P&L total = no realizado + premiums + realizado acciones ─────────────
    net_total_pnl = unrealized_pnl + total_premium + realized_stock_pnl
    roi_net_total = (net_total_pnl / total_capital_deployed * 100) if total_capital_deployed > 0 else 0

    # ── Mejor y peor posición (vs costo ajustado por premiums) ────────────────
    best_stock = None
    worst_stock = None
    best_pnl_pct = -float('inf')
    worst_pnl_pct = float('inf')

    for stock in active_stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        if current_price and stock.adjusted_cost_basis and stock.adjusted_cost_basis > 0:
            pnl_pct = ((current_price - stock.adjusted_cost_basis) / stock.adjusted_cost_basis) * 100
            pnl_abs = (current_price - stock.adjusted_cost_basis) * stock.shares
            entry = {
                "ticker": stock.ticker,
                "pnl_pct": round(pnl_pct, 2),
                "pnl": round(pnl_abs, 2),
                "current_price": round(current_price, 4),
                "adjusted_cost_basis": round(stock.adjusted_cost_basis, 4),
                "shares": stock.shares,
            }
            if pnl_pct > best_pnl_pct:
                best_pnl_pct = pnl_pct
                best_stock = entry
            if pnl_pct < worst_pnl_pct:
                worst_pnl_pct = pnl_pct
                worst_stock = entry

    return {
        # capital
        "total_invested": round(total_invested, 2),
        "total_capital_deployed": round(total_capital_deployed, 2),
        "current_value": round(current_portfolio_value, 2),
        # P&L desglosado
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_premium": round(total_premium, 2),
        "realized_stock_pnl": round(realized_stock_pnl, 2),
        "net_total_pnl": round(net_total_pnl, 2),
        # ROI
        "roi_unrealized": round(roi_unrealized, 2),
        "roi_net_total": round(roi_net_total, 2),
        # legacy (used by old frontend code)
        "total_pnl": round(net_total_pnl, 2),
        "roi": round(roi_unrealized, 2),
        # posiciones
        "best_position": best_stock,
        "worst_position": worst_stock,
        "total_positions": len(active_stocks),
        "active_options": len([o for o in options if o.status == OptionStatus.OPEN]),
    }

@router.get("/positions-pnl")
async def get_positions_pnl(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    P&L detallado por posición activa: unrealized, premium, total.
    Usado por el chart de barras en el dashboard.
    """
    active_stocks = db.query(Stock).filter(
        Stock.user_id == current_user.id, Stock.is_active == True
    ).all()

    positions = []
    for stock in active_stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        if not current_price:
            current_price = stock.adjusted_cost_basis or stock.total_invested / max(stock.shares, 1)

        # Unrealized puro (vs precio de compra promedio, sin ajuste de premiums)
        avg_cost_raw = stock.total_invested / max(stock.shares, 1)
        unrealized_pnl = (current_price - avg_cost_raw) * stock.shares
        unrealized_pct = ((current_price - avg_cost_raw) / avg_cost_raw * 100) \
            if avg_cost_raw > 0 else 0

        # Premium ganado para este ticker
        premium = stock.total_premium_earned or 0.0

        # P&L total = unrealized puro + premium neto cobrado
        total_pnl = unrealized_pnl + premium
        # ROI total = P&L total / capital bruto invertido (sin descontar premiums)
        total_pct = (total_pnl / stock.total_invested * 100) if stock.total_invested > 0 else 0

        positions.append({
            "ticker": stock.ticker,
            "shares": stock.shares,
            "cost_basis_raw": round(stock.total_invested / max(stock.shares, 1), 4),  # precio compra promedio bruto
            "adjusted_cost_basis": round(stock.adjusted_cost_basis or 0, 4),           # ajustado por premiums
            "current_price": round(current_price, 4),
            "current_value": round(current_price * stock.shares, 2),
            "total_invested": round(stock.total_invested, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pct": round(unrealized_pct, 2),
            "premium_earned": round(premium, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pct": round(total_pct, 2),
        })

    # Ordenar de mejor a peor
    positions.sort(key=lambda x: x["total_pct"], reverse=True)
    return positions

@router.get("/allocation")
async def get_portfolio_allocation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Distribución del portafolio por ticker
    """
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id, Stock.is_active == True).all()
    
    allocation = []
    total_value = 0
    
    for stock in stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        if current_price:
            value = current_price * stock.shares
        else:
            value = stock.total_invested
        
        total_value += value
        
        allocation.append({
            "ticker": stock.ticker,
            "value": round(value, 2),
            "shares": stock.shares,
            "current_price": current_price
        })
    
    # Calcular porcentajes
    for item in allocation:
        item["percentage"] = round((item["value"] / total_value * 100), 2) if total_value > 0 else 0
    
    # Ordenar por valor descendente
    allocation.sort(key=lambda x: x["value"], reverse=True)
    
    return {
        "allocation": allocation,
        "total_value": round(total_value, 2)
    }

@router.get("/premium-timeline")
async def get_premium_timeline(
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Timeline de premiums ganados
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Obtener ventas Y cierres/buybacks de opciones
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([
            TransactionType.SELL_CALL, TransactionType.SELL_PUT,
            TransactionType.BUY_CALL, TransactionType.BUY_PUT
        ]),
        Transaction.transaction_date >= start_date
    ).order_by(Transaction.transaction_date).all()
    
    # Agrupar por mes
    monthly_premium = {}
    
    for t in transactions:
        month_key = t.transaction_date.strftime("%Y-%m")
        if month_key not in monthly_premium:
            monthly_premium[month_key] = {
                "month": t.transaction_date.strftime("%b %Y"),
                "calls": 0.0,
                "puts": 0.0,
                "buybacks": 0.0,
                "total": 0.0,
            }
        
        amount = abs(t.total_amount)
        if t.transaction_type == TransactionType.SELL_CALL:
            monthly_premium[month_key]["calls"] += amount
            monthly_premium[month_key]["total"] += amount
        elif t.transaction_type == TransactionType.SELL_PUT:
            monthly_premium[month_key]["puts"] += amount
            monthly_premium[month_key]["total"] += amount
        else:  # BUY_CALL o BUY_PUT (cierre/buyback)
            monthly_premium[month_key]["buybacks"] += amount
    
    # Convertir a lista y ordenar
    timeline = list(monthly_premium.values())
    
    # Redondear valores y calcular neto
    for item in timeline:
        item["calls"]    = round(item["calls"], 2)
        item["puts"]     = round(item["puts"], 2)
        item["buybacks"] = round(item["buybacks"], 2)
        item["total"]    = round(item["total"], 2)
        item["net"]      = round(item["total"] - item["buybacks"], 2)
    
    return timeline

@router.get("/benchmark-comparison")
async def get_benchmark_comparison(
    days: int = Query(365, ge=30, le=1825),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Comparar rendimiento del portafolio vs S&P 500
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Obtener transacciones del usuario
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date >= start_date
    ).order_by(Transaction.transaction_date).all()
    
    # Calcular valor del portafolio diario
    portfolio_data = []
    current_date = start_date
    initial_invested = 0
    cumulative_invested = 0
    
    # Calcular inversión inicial (antes del período)
    pre_transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date < start_date
    ).all()
    
    for t in pre_transactions:
        if t.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
            initial_invested += abs(t.total_amount)
    
    cumulative_invested = initial_invested
    
    # Simular crecimiento del portafolio vs S&P 500
    # Para S&P 500 usamos un retorno promedio anual de ~10%
    sp500_daily_return = 0.10 / 365  # Aproximadamente 0.027% diario
    sp500_value = initial_invested if initial_invested > 0 else 10000  # Valor inicial
    initial_sp500_value = sp500_value
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id, Stock.is_active == True).all()
    
    while current_date <= end_date:
        # Transacciones del día
        day_transactions = [t for t in transactions if t.transaction_date.date() == current_date.date()]
        
        for t in day_transactions:
            if t.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
                cumulative_invested += abs(t.total_amount)
                sp500_value += abs(t.total_amount)
        
        # Calcular valor del portafolio
        portfolio_value = 0
        
        for stock in stocks:
            current_price = MarketDataService.get_current_price(stock.ticker)
            if current_price:
                portfolio_value += current_price * stock.shares
            else:
                portfolio_value += stock.total_invested
        
        # Agregar premiums
        premiums = sum(abs(t.total_amount) for t in transactions 
                      if t.transaction_type in [TransactionType.SELL_CALL, TransactionType.SELL_PUT] 
                      and t.transaction_date.date() <= current_date.date())
        portfolio_value += premiums
        
        # Si el portafolio está vacío, usar el valor invertido
        if portfolio_value == 0:
            portfolio_value = cumulative_invested
        
        # Calcular S&P 500 con crecimiento compuesto
        days_elapsed = (current_date - start_date).days
        sp500_value = initial_sp500_value * ((1 + sp500_daily_return) ** days_elapsed)
        
        # Calcular returns
        portfolio_return = ((portfolio_value - cumulative_invested) / cumulative_invested * 100) if cumulative_invested > 0 else 0
        sp500_return = ((sp500_value - initial_sp500_value) / initial_sp500_value * 100) if initial_sp500_value > 0 else 0
        
        portfolio_data.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "portfolio_value": round(portfolio_value, 2),
            "portfolio_return": round(portfolio_return, 2),
            "sp500_value": round(sp500_value, 2),
            "sp500_return": round(sp500_return, 2),
            "outperformance": round(portfolio_return - sp500_return, 2)
        })
        
        current_date += timedelta(days=1)
    
    # Calcular métricas de resumen
    if portfolio_data:
        latest = portfolio_data[-1]
        summary = {
            "portfolio_total_return": latest["portfolio_return"],
            "sp500_total_return": latest["sp500_return"],
            "outperformance": latest["outperformance"],
            "portfolio_final_value": latest["portfolio_value"],
            "sp500_final_value": latest["sp500_value"],
            "beat_market": latest["outperformance"] > 0
        }
    else:
        summary = {
            "portfolio_total_return": 0,
            "sp500_total_return": 0,
            "outperformance": 0,
            "portfolio_final_value": 0,
            "sp500_final_value": 0,
            "beat_market": False
        }
    
    return {
        "data": portfolio_data,
        "summary": summary,
        "period_days": days
    }

@router.get("/advanced-metrics")
async def get_advanced_metrics(
    days: int = Query(365, ge=30, le=1825),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Métricas de trading basadas únicamente en datos reales disponibles en la DB.
    Incluye: Win/Loss stats, duración de posiciones, breakdown por tipo de trade.
    NO incluye Sharpe/Sortino/MaxDD/Calmar — requieren precios históricos diarios.
    """
    from collections import defaultdict

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # ── Trades de opciones cerradas ─────────────────────────────────────────
    closed_options = (
        db.query(Option)
        .join(Stock)
        .filter(
            Stock.user_id == current_user.id,
            Option.status.in_([OptionStatus.EXPIRED, OptionStatus.CLOSED]),
        )
        .all()
    )

    option_trades = []
    for opt in closed_options:
        if opt.realized_pnl is None:
            continue
        closed_at = opt.closed_at or opt.expiration_date
        opened_at = opt.opened_at
        duration = (closed_at - opened_at).days if closed_at and opened_at else None
        # Filtrar por período
        if closed_at and closed_at.replace(tzinfo=None) < start_date:
            continue
        option_trades.append({
            "type": "option",
            "strategy": opt.strategy.value if opt.strategy else "OPTION",
            "ticker": opt.ticker,
            "pnl": opt.realized_pnl,
            "duration_days": max(1, duration) if duration is not None else None,
            "opened_at": opened_at,
            "closed_at": closed_at,
        })

    # ── Trades de acciones vendidas (con costo base histórico real) ──────────
    all_stock_txns = (
        db.query(Transaction)
        .join(Stock)
        .filter(
            Stock.user_id == current_user.id,
            Transaction.transaction_type.in_([TransactionType.BUY_STOCK, TransactionType.SELL_STOCK])
        )
        .order_by(Transaction.transaction_date)
        .all()
    )

    running_qty: dict = defaultdict(float)
    running_cost: dict = defaultdict(float)
    buy_dates: dict = defaultdict(list)   # ticker → list of (date, qty, price_per_share)
    stock_trades = []

    for txn in all_stock_txns:
        ticker = txn.ticker
        if txn.transaction_type == TransactionType.BUY_STOCK:
            qty = txn.quantity or 0
            cost = abs(txn.total_amount or 0)
            running_cost[ticker] += cost
            running_qty[ticker] += qty
            buy_dates[ticker].append((txn.transaction_date, qty))
        elif txn.transaction_type == TransactionType.SELL_STOCK:
            # Skip if outside period
            if txn.transaction_date.replace(tzinfo=None) < start_date:
                # Still need to apply the sell for cost basis tracking
                qty = txn.quantity or 0
                if running_qty[ticker] > 0:
                    avg = running_cost[ticker] / running_qty[ticker]
                    sell_qty = min(qty, running_qty[ticker])
                    running_qty[ticker] = max(0.0, running_qty[ticker] - sell_qty)
                    running_cost[ticker] = max(0.0, running_cost[ticker] - avg * sell_qty)
                continue
            qty = txn.quantity or 0
            proceeds = abs(txn.total_amount or 0)
            commission = abs(txn.commission or 0)
            if running_qty[ticker] > 0:
                avg_cost = running_cost[ticker] / running_qty[ticker]
                cost_basis = avg_cost * min(qty, running_qty[ticker])
                pnl = (proceeds - commission) - cost_basis
                # Estimate duration: days since first buy still in portfolio
                opened_at = buy_dates[ticker][0][0] if buy_dates[ticker] else txn.transaction_date
                duration = max(1, (txn.transaction_date - opened_at).days)
                stock_trades.append({
                    "type": "stock",
                    "strategy": "STOCK_SELL",
                    "ticker": ticker,
                    "pnl": round(pnl, 2),
                    "duration_days": duration,
                    "opened_at": opened_at,
                    "closed_at": txn.transaction_date,
                })
                running_qty[ticker] = max(0.0, running_qty[ticker] - qty)
                running_cost[ticker] = max(0.0, running_cost[ticker] - avg_cost * qty)
                if running_qty[ticker] == 0:
                    buy_dates[ticker] = []

    all_trades = option_trades + stock_trades

    if not all_trades:
        return {
            "error": "No hay trades cerrados en este período",
            "period_days": days,
            "total_trades": 0,
        }

    pnls = [t["pnl"] for t in all_trades]
    wins  = [t for t in all_trades if t["pnl"] > 0]
    losses = [t for t in all_trades if t["pnl"] < 0]
    breakevens = [t for t in all_trades if t["pnl"] == 0]

    win_rate    = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_win     = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss    = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    total_win   = sum(t["pnl"] for t in wins) if wins else 0
    total_loss  = abs(sum(t["pnl"] for t in losses)) if losses else 0
    profit_factor = (total_win / total_loss) if total_loss > 0 else None

    best_trade  = max(all_trades, key=lambda t: t["pnl"]) if all_trades else None
    worst_trade = min(all_trades, key=lambda t: t["pnl"]) if all_trades else None

    durations = [t["duration_days"] for t in all_trades if t["duration_days"] is not None]
    avg_duration = sum(durations) / len(durations) if durations else None

    # Expectancy: average $ per trade
    expectancy = sum(pnls) / len(pnls) if pnls else 0

    # Breakdown por tipo
    option_pnl = sum(t["pnl"] for t in option_trades)
    stock_pnl  = sum(t["pnl"] for t in stock_trades)

    # Consecutive wins/losses
    sorted_trades = sorted(all_trades, key=lambda t: t["closed_at"])
    max_consec_wins = max_consec_losses = 0
    cur_wins = cur_losses = 0
    for t in sorted_trades:
        if t["pnl"] > 0:
            cur_wins += 1; cur_losses = 0
            max_consec_wins = max(max_consec_wins, cur_wins)
        elif t["pnl"] < 0:
            cur_losses += 1; cur_wins = 0
            max_consec_losses = max(max_consec_losses, cur_losses)
        else:
            cur_wins = cur_losses = 0

    return {
        "period_days": days,
        # trade counts
        "total_trades": len(all_trades),
        "option_trades": len(option_trades),
        "stock_trades": len(stock_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "breakeven_trades": len(breakevens),
        # rates & averages
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        # totals
        "total_realized_pnl": round(sum(pnls), 2),
        "option_pnl": round(option_pnl, 2),
        "stock_pnl": round(stock_pnl, 2),
        # best / worst
        "best_trade": {
            "ticker": best_trade["ticker"],
            "pnl": best_trade["pnl"],
            "type": best_trade["strategy"],
        } if best_trade else None,
        "worst_trade": {
            "ticker": worst_trade["ticker"],
            "pnl": worst_trade["pnl"],
            "type": worst_trade["strategy"],
        } if worst_trade else None,
        # duration
        "avg_duration_days": round(avg_duration, 1) if avg_duration is not None else None,
        # streaks
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        # legacy
        "risk_free_rate": 4.0,
        "error": None,
    }

@router.get("/covered-call-cycles")
async def get_covered_call_cycles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Historial de ciclos de covered calls con rendimiento anualizado por prima.
    Captura cada ciclo (apertura → cierre/roll) y calcula su rentabilidad anualizada.
    """
    options = db.query(Option).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.strategy == OptionStrategy.COVERED_CALL
    ).order_by(Option.opened_at.asc()).all()

    cycles = []
    for idx, opt in enumerate(options, start=1):
        capital = opt.strike_price * opt.contracts * 100

        if opt.status == OptionStatus.OPEN:
            closing_cost = 0.0
            net_premium = opt.total_premium
            opened_date = opt.opened_at.date() if hasattr(opt.opened_at, 'date') else opt.opened_at
            exp_date = opt.expiration_date.date() if hasattr(opt.expiration_date, 'date') else opt.expiration_date
            duration_days = max(1, (exp_date - opened_date).days)
            end_date_str = exp_date.isoformat()
            label = f"Ciclo {idx} ★"
        else:
            closing_cost = round((opt.closing_premium or 0.0) * opt.contracts * 100, 2)
            net_premium = opt.total_premium - closing_cost
            opened_date = opt.opened_at.date() if hasattr(opt.opened_at, 'date') else opt.opened_at
            if opt.closed_at:
                end_date = opt.closed_at.date() if hasattr(opt.closed_at, 'date') else opt.closed_at
            else:
                end_date = opt.expiration_date.date() if hasattr(opt.expiration_date, 'date') else opt.expiration_date
            duration_days = max(1, (end_date - opened_date).days)
            end_date_str = end_date.isoformat()
            label = f"Ciclo {idx}"

        net_yield = (net_premium / capital * 100) if capital > 0 else 0
        annualized = round(net_yield * (365 / duration_days), 2)

        cycles.append({
            "cycle_num": idx,
            "ticker": opt.ticker,
            "label": label,
            "opened_at": opt.opened_at.date().isoformat() if hasattr(opt.opened_at, 'date') else str(opt.opened_at),
            "end_date": end_date_str,
            "expiration_date": opt.expiration_date.date().isoformat() if hasattr(opt.expiration_date, 'date') else str(opt.expiration_date),
            "strike_price": opt.strike_price,
            "contracts": opt.contracts,
            "capital": round(capital, 2),
            "total_premium": round(opt.total_premium, 2),
            "closing_cost": round(closing_cost, 2),
            "net_premium": round(net_premium, 2),
            "duration_days": duration_days,
            "net_yield": round(net_yield, 4),
            "annualized_return": annualized,
            "status": opt.status.value,
            "notes": opt.notes or ""
        })

    # ── Detectar rolls: mismo ticker, apertura del siguiente == cierre del anterior ──
    roll_group_id = 0
    for i, c in enumerate(cycles):
        if i == 0:
            c["roll_group"] = roll_group_id
            c["is_roll"] = False
        else:
            prev = cycles[i - 1]
            if c["ticker"] == prev["ticker"] and c["opened_at"] == prev["end_date"]:
                c["roll_group"] = prev["roll_group"]
                c["is_roll"] = True
            else:
                roll_group_id += 1
                c["roll_group"] = roll_group_id
                c["is_roll"] = False

    # ── Construir roll_groups (una entrada por cadena) ────────────────────────
    groups_map: dict = {}
    for c in cycles:
        groups_map.setdefault(c["roll_group"], []).append(c)

    roll_groups = []
    for gid, gc in groups_map.items():
        first = gc[0]
        last  = gc[-1]
        is_open = any(c["status"] == "OPEN" for c in gc)
        total_net = round(sum(c["net_premium"] for c in gc), 2)
        base_capital = first["capital"]
        first_opened = first["opened_at"]
        last_end = last["end_date"]
        total_days = max(1, (
            datetime.fromisoformat(last_end) - datetime.fromisoformat(first_opened)
        ).days)
        net_yield = round(total_net / base_capital * 100, 4) if base_capital > 0 else 0
        annualized = round(net_yield * 365 / total_days, 2)
        roll_groups.append({
            "group_id": gid,
            "ticker": first["ticker"],
            "cycle_nums": [c["cycle_num"] for c in gc],
            "is_roll_chain": len(gc) > 1,
            "status": "OPEN" if is_open else "CLOSED",
            "first_opened": first_opened,
            "last_end": last_end,
            "total_days": total_days,
            "base_capital": base_capital,
            "total_net_premium": total_net,
            "net_yield": net_yield,
            "annualized_return": annualized,
            "n_rolls": len(gc) - 1,
            "last_strike": last["strike_price"],
            "last_expiration": last["expiration_date"],
        })

    if cycles:
        closed_cycles = [c for c in cycles if c["status"] != "OPEN"]
        open_cycles_list = [c for c in cycles if c["status"] == "OPEN"]
        all_annualized = [c["annualized_return"] for c in cycles]
        closed_annualized = [c["annualized_return"] for c in closed_cycles]
        total_net_premium = sum(c["net_premium"] for c in cycles)
        avg_annualized = round(sum(all_annualized) / len(all_annualized), 2)
        avg_closed = round(sum(closed_annualized) / len(closed_annualized), 2) if closed_annualized else 0
        capital_deployed = round(sum(c["capital"] for c in open_cycles_list), 2)
        open_rg = [rg for rg in roll_groups if rg["status"] == "OPEN"]
        summary = {
            "total_cycles": len(cycles),
            "closed_cycles": len(closed_cycles),
            "avg_annualized_return": avg_annualized,
            "avg_closed_annualized": avg_closed,
            "total_net_premium": round(total_net_premium, 2),
            "capital_deployed": capital_deployed,
            "open_cycles": [
                {"ticker": c["ticker"], "annualized": c["annualized_return"], "capital": c["capital"]}
                for c in open_cycles_list
            ],
            "current_cycle_annualized": open_cycles_list[-1]["annualized_return"] if open_cycles_list else None,
        }
    else:
        summary = {
            "total_cycles": 0,
            "closed_cycles": 0,
            "avg_annualized_return": 0,
            "avg_closed_annualized": 0,
            "total_net_premium": 0,
            "capital_deployed": 0,
            "current_cycle_annualized": None,
        }

    return {"cycles": cycles, "summary": summary, "roll_groups": roll_groups}


@router.get("/realized-pnl-stocks")
async def get_realized_pnl_stocks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """P&L realizado de venta de acciones (SELL_STOCK), usando costo promedio histórico."""
    from collections import defaultdict

    # Reconstruir costo promedio ponderado en orden cronológico
    all_stock_txs = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([TransactionType.BUY_STOCK, TransactionType.SELL_STOCK])
    ).order_by(Transaction.transaction_date).all()

    _running_shares: dict = defaultdict(float)
    _running_cost: dict = defaultdict(float)
    sell_cost_basis: dict[int, float] = {}  # tx.id -> avg cost at time of sale
    for _tx in all_stock_txs:
        if _tx.transaction_type == TransactionType.BUY_STOCK:
            _running_shares[_tx.ticker] += _tx.quantity
            _running_cost[_tx.ticker] += _tx.total_amount
        elif _tx.transaction_type == TransactionType.SELL_STOCK:
            _shares = _running_shares[_tx.ticker]
            _avg = (_running_cost[_tx.ticker] / _shares) if _shares > 0 else 0.0
            sell_cost_basis[_tx.id] = _avg
            _running_shares[_tx.ticker] = max(0.0, _running_shares[_tx.ticker] - _tx.quantity)
            _running_cost[_tx.ticker] = max(0.0, _running_cost[_tx.ticker] - _tx.quantity * _avg)

    sell_txs = [t for t in all_stock_txs if t.transaction_type == TransactionType.SELL_STOCK]

    by_ticker: dict[str, dict] = {}
    for tx in sell_txs:
        cost_basis = sell_cost_basis.get(tx.id, 0.0)
        pnl = tx.total_amount - (tx.quantity * cost_basis)

        if tx.ticker not in by_ticker:
            by_ticker[tx.ticker] = {
                "ticker": tx.ticker,
                "shares_sold": 0.0,
                "proceeds": 0.0,
                "cost": 0.0,
                "pnl": 0.0,
                "n_trades": 0,
            }
        by_ticker[tx.ticker]["shares_sold"] += tx.quantity
        by_ticker[tx.ticker]["proceeds"] += tx.total_amount
        by_ticker[tx.ticker]["cost"] += tx.quantity * cost_basis
        by_ticker[tx.ticker]["pnl"] += pnl
        by_ticker[tx.ticker]["n_trades"] += 1

    result = sorted(by_ticker.values(), key=lambda x: x["pnl"], reverse=True)
    for r in result:
        r["shares_sold"] = round(r["shares_sold"], 2)
        r["proceeds"] = round(r["proceeds"], 2)
        r["cost"] = round(r["cost"], 2)
        r["pnl"] = round(r["pnl"], 2)

    return {
        "by_ticker": result,
        "total_pnl": round(sum(r["pnl"] for r in result), 2),
        "total_proceeds": round(sum(r["proceeds"] for r in result), 2),
    }


@router.get("/yearly-summary")
async def get_yearly_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resumen de rendimiento por año fiscal (2025, 2026…)."""
    from collections import defaultdict

    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id
    ).order_by(Transaction.transaction_date).all()

    # ── Pre-compute historical weighted-average cost basis per sell ──────────
    # Process all transactions chronologically to reconstruct cost basis at the
    # exact moment each SELL_STOCK occurred (avoids using today's average_cost).
    running_shares: dict[str, float] = defaultdict(float)
    running_cost: dict[str, float] = defaultdict(float)
    sell_cost_basis: dict[int, float] = {}  # tx.id -> avg cost at time of sale

    for tx in transactions:
        if tx.transaction_type == TransactionType.BUY_STOCK:
            running_shares[tx.ticker] += tx.quantity
            running_cost[tx.ticker] += tx.total_amount
        elif tx.transaction_type == TransactionType.SELL_STOCK:
            shares = running_shares[tx.ticker]
            avg = (running_cost[tx.ticker] / shares) if shares > 0 else 0.0
            sell_cost_basis[tx.id] = avg
            # Reduce running position proportionally
            cost_removed = tx.quantity * avg
            running_shares[tx.ticker] = max(0.0, running_shares[tx.ticker] - tx.quantity)
            running_cost[tx.ticker] = max(0.0, running_cost[tx.ticker] - cost_removed)

    # ── Aggregate by year ────────────────────────────────────────────────────
    years: dict[int, dict] = {}
    for tx in transactions:
        yr = tx.transaction_date.year
        if yr not in years:
            years[yr] = {
                "year": yr,
                "invested": 0.0,
                "sold": 0.0,
                "premium_income": 0.0,
                "dividends": 0.0,
                "commissions": 0.0,
                "realized_stock_pnl": 0.0,
                "n_buys": 0,
                "n_sells": 0,
                "n_options": 0,
            }

        years[yr]["commissions"] += tx.commission or 0

        if tx.transaction_type == TransactionType.BUY_STOCK:
            years[yr]["invested"] += tx.total_amount
            years[yr]["n_buys"] += 1
        elif tx.transaction_type == TransactionType.SELL_STOCK:
            years[yr]["sold"] += tx.total_amount
            years[yr]["n_sells"] += 1
            avg_cost = sell_cost_basis.get(tx.id, 0.0)
            years[yr]["realized_stock_pnl"] += tx.total_amount - (tx.quantity * avg_cost)
        elif tx.transaction_type in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            years[yr]["premium_income"] += tx.total_amount
            years[yr]["n_options"] += 1
        elif tx.transaction_type in (TransactionType.BUY_CALL, TransactionType.BUY_PUT):
            years[yr]["premium_income"] -= tx.total_amount  # cierre resta prima
            years[yr]["n_options"] += 1
        elif tx.transaction_type == TransactionType.DIVIDEND:
            years[yr]["dividends"] += tx.total_amount

    result = []
    for d in sorted(years.values(), key=lambda x: x["year"]):
        d["invested"] = round(d["invested"], 2)
        d["sold"] = round(d["sold"], 2)
        d["premium_income"] = round(d["premium_income"], 2)
        d["dividends"] = round(d["dividends"], 2)
        d["commissions"] = round(d["commissions"], 2)
        d["realized_stock_pnl"] = round(d["realized_stock_pnl"], 2)
        # total_income = all realized gains minus commissions paid
        d["total_income"] = round(
            d["premium_income"] + d["dividends"] + d["realized_stock_pnl"] - d["commissions"], 2
        )
        result.append(d)

    return result


@router.get("/cc-by-ticker")
async def get_cc_by_ticker(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resumen de covered calls / opciones vendidas por ticker (desde transacciones importadas)."""
    txs = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([TransactionType.SELL_CALL, TransactionType.BUY_CALL,
                                          TransactionType.SELL_PUT, TransactionType.BUY_PUT])
    ).order_by(Transaction.transaction_date).all()

    all_stocks = {
        s.ticker: s
        for s in db.query(Stock).filter(Stock.user_id == current_user.id).all()
    }

    by_ticker: dict[str, dict] = {}
    for tx in txs:
        ticker = tx.ticker
        if ticker not in by_ticker:
            by_ticker[ticker] = {
                "ticker": ticker,
                "primas_cobradas": 0.0,
                "cierres": 0.0,
                "n_ventas": 0,
                "n_cierres": 0,
            }
        if tx.transaction_type in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            by_ticker[ticker]["primas_cobradas"] += tx.total_amount
            by_ticker[ticker]["n_ventas"] += 1
        else:
            by_ticker[ticker]["cierres"] += tx.total_amount
            by_ticker[ticker]["n_cierres"] += 1

    result = []
    for d in by_ticker.values():
        stk = all_stocks.get(d["ticker"])
        capital = (stk.shares * stk.average_cost) if stk and stk.shares > 0 else 0.0
        prima_neta = d["primas_cobradas"] - d["cierres"]

        result.append({
            "ticker": d["ticker"],
            "primas_cobradas": round(d["primas_cobradas"], 2),
            "cierres": round(d["cierres"], 2),
            "prima_neta": round(prima_neta, 2),
            "n_ventas": d["n_ventas"],
            "n_cierres": d["n_cierres"],
            "shares": stk.shares if stk else 0,
            "avg_cost": round(stk.average_cost, 2) if stk else 0,
            "capital": round(capital, 2),
            "yield_pct": round((prima_neta / capital * 100), 2) if capital > 0 else 0,
        })

    result.sort(key=lambda x: x["prima_neta"], reverse=True)

    return {
        "by_ticker": result,
        "total_primas_cobradas": round(sum(d["primas_cobradas"] for d in result), 2),
        "total_cierres": round(sum(d["cierres"] for d in result), 2),
        "total_prima_neta": round(sum(d["prima_neta"] for d in result), 2),
    }


@router.get("/portfolio-growth")
async def get_portfolio_growth(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Curva de crecimiento histórico del portafolio desde la primera transacción.
    Calcula en cada fecha de evento:
      - cumulative_invested: todo el dinero comprado en acciones acumulado
      - total_realized_net: P&L realizado (acciones + primas + dividendos - comisiones)
      - roi_realized_pct: total_realized_net / cumulative_invested * 100
    Agrega al final el P&L no realizado actual para la métrica total.
    """
    from collections import defaultdict

    all_txs = db.query(Transaction).filter(
        Transaction.user_id == current_user.id
    ).order_by(Transaction.transaction_date).all()

    if not all_txs:
        return {"events": [], "current_unrealized": 0, "total_pnl": 0, "roi_total_pct": 0, "cumulative_invested": 0}

    # P&L no realizado actual
    active_stocks = db.query(Stock).filter(
        Stock.user_id == current_user.id, Stock.is_active == True
    ).all()
    tickers = [s.ticker for s in active_stocks]
    prices = MarketDataService.get_multiple_prices(tickers) if tickers else {}
    # P&L no realizado puro (precio actual vs costo de compra promedio, sin premiums)
    # Premiums se contabilizan por separado en cumulative_premiums
    current_unrealized = sum(
        (prices[s.ticker] * s.shares - s.total_invested)
        for s in active_stocks
        if prices.get(s.ticker)
    )

    # ── Procesar transacciones cronológicamente, agrupar por fecha ─────────
    running_shares: dict = defaultdict(float)
    running_cost: dict = defaultdict(float)
    cumulative_invested = 0.0
    cumulative_sells = 0.0
    cumulative_realized_pnl = 0.0
    cumulative_premiums = 0.0
    cumulative_dividends = 0.0
    cumulative_commissions = 0.0

    events_by_date: dict = {}

    for tx in all_txs:
        d = tx.transaction_date.strftime("%Y-%m-%d")
        cumulative_commissions += tx.commission or 0.0

        if tx.transaction_type == TransactionType.BUY_STOCK:
            cumulative_invested += tx.total_amount
            running_shares[tx.ticker] += tx.quantity
            running_cost[tx.ticker] += tx.total_amount

        elif tx.transaction_type == TransactionType.SELL_STOCK:
            cumulative_sells += tx.total_amount
            shares = running_shares[tx.ticker]
            avg = (running_cost[tx.ticker] / shares) if shares > 0 else 0.0
            pnl = tx.total_amount - (tx.quantity * avg)
            cumulative_realized_pnl += pnl
            running_shares[tx.ticker] = max(0.0, running_shares[tx.ticker] - tx.quantity)
            running_cost[tx.ticker] = max(0.0, running_cost[tx.ticker] - tx.quantity * avg)

        elif tx.transaction_type in (TransactionType.SELL_CALL, TransactionType.SELL_PUT):
            cumulative_premiums += tx.total_amount

        elif tx.transaction_type in (TransactionType.BUY_CALL, TransactionType.BUY_PUT):
            cumulative_premiums -= tx.total_amount

        elif tx.transaction_type == TransactionType.DIVIDEND:
            cumulative_dividends += tx.total_amount

        total_realized_net = cumulative_realized_pnl + cumulative_premiums + cumulative_dividends - cumulative_commissions
        net_cash = max(0.0, cumulative_invested - cumulative_sells)
        roi_pct = (total_realized_net / cumulative_invested * 100) if cumulative_invested > 0 else 0.0
        roi_net_pct = (total_realized_net / net_cash * 100) if net_cash > 0 else 0.0

        events_by_date[d] = {
            "date": d,
            "cumulative_invested": round(cumulative_invested, 2),
            "cumulative_sells": round(cumulative_sells, 2),
            "net_cash_deployed": round(net_cash, 2),
            "cumulative_realized_pnl": round(cumulative_realized_pnl, 2),
            "cumulative_premiums": round(cumulative_premiums, 2),
            "total_realized_net": round(total_realized_net, 2),
            "roi_realized_pct": round(roi_pct, 2),
            "roi_net_cash_pct": round(roi_net_pct, 2),
        }

    events = sorted(events_by_date.values(), key=lambda x: x["date"])

    # Punto final: agregar último evento con unrealized incluido
    last = events[-1]
    total_pnl = last["total_realized_net"] + current_unrealized
    roi_total_pct = (total_pnl / last["cumulative_invested"] * 100) if last["cumulative_invested"] > 0 else 0.0
    net_cash_final = last["net_cash_deployed"]
    roi_net_cash_total_pct = (total_pnl / net_cash_final * 100) if net_cash_final > 0 else 0.0

    return {
        "events": events,
        "current_unrealized": round(current_unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "roi_total_pct": round(roi_total_pct, 2),
        "roi_net_cash_total_pct": round(roi_net_cash_total_pct, 2),
        "cumulative_invested": round(last["cumulative_invested"], 2),
        "net_cash_deployed": round(net_cash_final, 2),
    }


@router.get("/twr")
async def get_twr(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Time-Weighted Return (TWR) — misma metodología que IBKR Performance chart.
    Divide el período en sub-períodos en cada flujo de caja (transacción), calcula
    la rentabilidad de cada sub-período usando precios históricos reales de yfinance,
    y encadena los retornos. Incluye comparativa con NASDAQ (^IXIC).
    """
    import yfinance as yf
    import pandas as pd
    from collections import defaultdict

    stock_txs = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([TransactionType.BUY_STOCK, TransactionType.SELL_STOCK])
    ).order_by(Transaction.transaction_date).all()

    if not stock_txs:
        return {"twr_series": [], "twr_final": 0.0, "benchmark_series": [], "error": None}

    first_date = stock_txs[0].transaction_date.date()
    today = date.today()
    start_str = first_date.strftime("%Y-%m-%d")
    end_str   = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    all_tickers = list(set(tx.ticker for tx in stock_txs))

    # ── Descargar precios históricos ────────────────────────────────────────
    price_map: dict[str, pd.Series] = {}
    try:
        raw = yf.download(
            all_tickers, start=start_str, end=end_str,
            auto_adjust=True, progress=False, threads=True
        )
        if not raw.empty:
            if len(all_tickers) == 1:
                close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
                price_map[all_tickers[0]] = close.ffill()
            else:
                close = raw["Close"] if "Close" in raw.columns else raw.xs("Close", axis=1, level=0)
                for t in all_tickers:
                    if t in close.columns:
                        price_map[t] = close[t].ffill()
    except Exception as e:
        return {"twr_series": [], "twr_final": 0.0, "benchmark_series": [], "error": str(e)}

    # ── Descargar benchmarks NASDAQ + S&P 500 ──────────────────────────────
    benchmark_series: list[dict] = []
    sp500_series: list[dict] = []
    try:
        bm_raw = yf.download(["^IXIC", "^GSPC"], start=start_str, end=end_str,
                             auto_adjust=True, progress=False, threads=True)
        bm_close = bm_raw["Close"] if "Close" in bm_raw.columns else bm_raw.xs("Close", axis=1, level=0)

        if "^IXIC" in bm_close.columns:
            nq = bm_close["^IXIC"].ffill().dropna()
            if not nq.empty:
                nq_base = float(nq.iloc[0])
                for dt, val in nq.items():
                    benchmark_series.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "pct": round((float(val) / nq_base - 1.0) * 100, 2)
                    })

        if "^GSPC" in bm_close.columns:
            sp = bm_close["^GSPC"].ffill().dropna()
            if not sp.empty:
                sp_base = float(sp.iloc[0])
                for dt, val in sp.items():
                    sp500_series.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "pct": round((float(val) / sp_base - 1.0) * 100, 2)
                    })
    except Exception:
        pass

    # ── Helper: valor del portafolio en una fecha ───────────────────────────
    def get_price(ticker: str, for_date: date) -> float:
        if ticker not in price_map:
            return 0.0
        s = price_map[ticker]
        ts = pd.Timestamp(for_date)
        available = s[s.index <= ts].dropna()
        return float(available.iloc[-1]) if not available.empty else 0.0

    def portfolio_value(positions: dict, for_date: date) -> float:
        return sum(shares * get_price(t, for_date) for t, shares in positions.items() if shares > 0)

    # ── TWR: procesar día a día ────────────────────────────────────────────
    # Construir mapa de transacciones por fecha
    tx_by_date: dict[date, list] = defaultdict(list)
    for tx in stock_txs:
        tx_by_date[tx.transaction_date.date()].append(tx)

    positions: dict[str, float] = defaultdict(float)
    twr_cumulative = 1.0
    prev_value_after_cf = 0.0   # V justo después del último flujo de caja
    first_buy_done = False
    twr_series: list[dict] = []

    current = first_date
    while current <= today:
        day_txs = tx_by_date.get(current, [])

        if day_txs:
            # Valor ANTES de aplicar transacciones de hoy
            v_before = portfolio_value(positions, current)

            # Sub-período: desde el último flujo hasta justo antes de este
            if first_buy_done and prev_value_after_cf > 0:
                r = v_before / prev_value_after_cf - 1.0
                twr_cumulative *= (1.0 + r)

            # Aplicar transacciones
            for tx in day_txs:
                if tx.transaction_type == TransactionType.BUY_STOCK:
                    positions[tx.ticker] += tx.quantity
                    first_buy_done = True
                elif tx.transaction_type == TransactionType.SELL_STOCK:
                    positions[tx.ticker] = max(0.0, positions[tx.ticker] - tx.quantity)

            # Valor DESPUÉS de transacciones (nuevo punto de partida del siguiente sub-período)
            v_after = portfolio_value(positions, current)
            prev_value_after_cf = v_after

        elif first_buy_done:
            # Día sin transacción: calcular valor actual y actualizar TWR corriente
            v_today = portfolio_value(positions, current)
            if prev_value_after_cf > 0:
                r = v_today / prev_value_after_cf - 1.0
                twr_cumulative *= (1.0 + r)
            prev_value_after_cf = v_today

        if first_buy_done:
            twr_series.append({
                "date": current.strftime("%Y-%m-%d"),
                "twr_pct": round((twr_cumulative - 1.0) * 100, 2),
            })

        current += timedelta(days=1)

    return {
        "twr_series": twr_series,
        "twr_final": round((twr_cumulative - 1.0) * 100, 2),
        "benchmark_series": benchmark_series,
        "sp500_series": sp500_series,
        "error": None,
    }