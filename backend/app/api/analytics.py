from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List
from datetime import datetime, timedelta, date
import math
from ..database import get_db
from ..models import Stock, Option, Transaction, TransactionType, User, OptionStatus
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
    Obtener el historial del valor del portafolio
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Obtener todas las transacciones del usuario en el período
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date >= start_date
    ).order_by(Transaction.transaction_date).all()
    
    # Construir el historial día por día
    history = []
    current_date = start_date
    cumulative_invested = 0
    cumulative_value = 0
    
    while current_date <= end_date:
        # Transacciones del día
        day_transactions = [t for t in transactions if t.transaction_date.date() == current_date.date()]
        
        for t in day_transactions:
            if t.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
                cumulative_invested += abs(t.total_amount)
            elif t.transaction_type in [TransactionType.SELL_CALL, TransactionType.SELL_PUT]:
                cumulative_value += abs(t.total_amount)
        
        # Calcular valor actual del portafolio en ese día
        # (simplificado - en producción querrías precios históricos reales)
        stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
        portfolio_value = cumulative_invested
        
        for stock in stocks:
            current_price = MarketDataService.get_current_price(stock.ticker)
            if current_price:
                portfolio_value += (current_price - stock.adjusted_cost_basis) * stock.shares
        
        # Agregar premiums ganados
        portfolio_value += cumulative_value
        
        history.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "portfolio_value": round(portfolio_value, 2),
            "invested": round(cumulative_invested, 2),
            "pnl": round(portfolio_value - cumulative_invested, 2)
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
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    options = db.query(Option).join(Stock).filter(Stock.user_id == current_user.id).all()
    
    total_invested = sum(stock.total_invested for stock in stocks)
    current_portfolio_value = 0
    
    # Calcular valor actual
    for stock in stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        if current_price:
            current_portfolio_value += current_price * stock.shares
        else:
            current_portfolio_value += stock.total_invested
    
    # Premium ganado
    total_premium = sum(opt.total_premium for opt in options)
    
    # Calcular ROI
    total_pnl = (current_portfolio_value + total_premium) - total_invested
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    
    # Mejor y peor posición
    best_stock = None
    worst_stock = None
    best_pnl_pct = -float('inf')
    worst_pnl_pct = float('inf')
    
    for stock in stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        if current_price:
            pnl_pct = ((current_price - stock.adjusted_cost_basis) / stock.adjusted_cost_basis) * 100
            if pnl_pct > best_pnl_pct:
                best_pnl_pct = pnl_pct
                best_stock = {
                    "ticker": stock.ticker,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl": round((current_price - stock.adjusted_cost_basis) * stock.shares, 2)
                }
            if pnl_pct < worst_pnl_pct:
                worst_pnl_pct = pnl_pct
                worst_stock = {
                    "ticker": stock.ticker,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl": round((current_price - stock.adjusted_cost_basis) * stock.shares, 2)
                }
    
    return {
        "total_invested": round(total_invested, 2),
        "current_value": round(current_portfolio_value, 2),
        "total_premium": round(total_premium, 2),
        "total_pnl": round(total_pnl, 2),
        "roi": round(roi, 2),
        "best_position": best_stock,
        "worst_position": worst_stock,
        "total_positions": len(stocks),
        "active_options": len([o for o in options if o.status == OptionStatus.OPEN])
    }

@router.get("/allocation")
async def get_portfolio_allocation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Distribución del portafolio por ticker
    """
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    
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
    
    # Obtener transacciones de premiums
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([TransactionType.SELL_CALL, TransactionType.SELL_PUT]),
        Transaction.transaction_date >= start_date
    ).order_by(Transaction.transaction_date).all()
    
    # Agrupar por mes
    monthly_premium = {}
    
    for t in transactions:
        month_key = t.transaction_date.strftime("%Y-%m")
        if month_key not in monthly_premium:
            monthly_premium[month_key] = {
                "month": t.transaction_date.strftime("%b %Y"),
                "calls": 0,
                "puts": 0,
                "total": 0
            }
        
        amount = abs(t.total_amount)
        if t.transaction_type == TransactionType.SELL_CALL:
            monthly_premium[month_key]["calls"] += amount
        else:
            monthly_premium[month_key]["puts"] += amount
        
        monthly_premium[month_key]["total"] += amount
    
    # Convertir a lista y ordenar
    timeline = list(monthly_premium.values())
    
    # Redondear valores
    for item in timeline:
        item["calls"] = round(item["calls"], 2)
        item["puts"] = round(item["puts"], 2)
        item["total"] = round(item["total"], 2)
    
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
    
    while current_date <= end_date:
        # Transacciones del día
        day_transactions = [t for t in transactions if t.transaction_date.date() == current_date.date()]
        
        for t in day_transactions:
            if t.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
                cumulative_invested += abs(t.total_amount)
                sp500_value += abs(t.total_amount)
        
        # Calcular valor del portafolio
        stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
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
    Calcular métricas avanzadas de portafolio:
    - Sharpe Ratio
    - Sortino Ratio
    - Max Drawdown
    - Volatility (anualizada)
    - Win Rate
    - Average Win/Loss
    - Profit Factor
    - Calmar Ratio
    """
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Obtener transacciones
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date >= start_date
    ).order_by(Transaction.transaction_date).all()
    
    if not transactions:
        return {
            "error": "No hay suficientes datos para calcular métricas",
            "min_days_required": 30
        }
    
    # Calcular retornos diarios
    daily_returns = []
    daily_values = []
    current_date = start_date
    prev_value = None
    
    # Inversión inicial
    initial_invested = 0
    pre_transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date < start_date
    ).all()
    
    for t in pre_transactions:
        if t.transaction_type in [TransactionType.BUY_STOCK, TransactionType.BUY_CALL, TransactionType.BUY_PUT]:
            initial_invested += abs(t.total_amount)
    
    cumulative_invested = initial_invested if initial_invested > 0 else 10000
    
    while current_date <= end_date:
        # Calcular valor del portafolio
        stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
        portfolio_value = 0
        
        for stock in stocks:
            current_price = MarketDataService.get_current_price(stock.ticker)
            if current_price:
                portfolio_value += current_price * stock.shares
        
        # Agregar premiums hasta esta fecha
        premiums = sum(abs(t.total_amount) for t in transactions 
                      if t.transaction_type in [TransactionType.SELL_CALL, TransactionType.SELL_PUT] 
                      and t.transaction_date.date() <= current_date.date())
        portfolio_value += premiums
        
        if portfolio_value == 0:
            portfolio_value = cumulative_invested
        
        daily_values.append(portfolio_value)
        
        # Calcular retorno diario
        if prev_value is not None and prev_value > 0:
            daily_return = (portfolio_value - prev_value) / prev_value
            daily_returns.append(daily_return)
        
        prev_value = portfolio_value
        current_date += timedelta(days=1)
    
    if len(daily_returns) < 30:
        return {
            "error": "No hay suficientes datos para calcular métricas",
            "days_available": len(daily_returns),
            "min_days_required": 30
        }
    
    # ===== CÁLCULOS DE MÉTRICAS =====
    
    # 1. Volatility (anualizada)
    returns_mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - returns_mean) ** 2 for r in daily_returns) / len(daily_returns)
    daily_volatility = math.sqrt(variance)
    annual_volatility = daily_volatility * math.sqrt(252)  # 252 trading days
    
    # 2. Sharpe Ratio (asumiendo risk-free rate de 4% anual)
    risk_free_rate = 0.04
    daily_risk_free = risk_free_rate / 252
    excess_returns = [r - daily_risk_free for r in daily_returns]
    avg_excess_return = sum(excess_returns) / len(excess_returns)
    
    if daily_volatility > 0:
        sharpe_ratio = (avg_excess_return / daily_volatility) * math.sqrt(252)
    else:
        sharpe_ratio = 0
    
    # 3. Sortino Ratio (solo volatilidad negativa)
    downside_returns = [r for r in daily_returns if r < 0]
    if len(downside_returns) > 0:
        downside_variance = sum((r - 0) ** 2 for r in downside_returns) / len(downside_returns)
        downside_volatility = math.sqrt(downside_variance)
        if downside_volatility > 0:
            sortino_ratio = (avg_excess_return / downside_volatility) * math.sqrt(252)
        else:
            sortino_ratio = 0
    else:
        sortino_ratio = 0
    
    # 4. Max Drawdown
    peak = daily_values[0]
    max_drawdown = 0
    max_drawdown_pct = 0
    
    for value in daily_values:
        if value > peak:
            peak = value
        drawdown = peak - value
        drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
        
        if drawdown_pct > max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
            max_drawdown = drawdown
    
    # 5. Calmar Ratio (annual return / max drawdown)
    total_return = (daily_values[-1] - daily_values[0]) / daily_values[0] if daily_values[0] > 0 else 0
    annual_return = (1 + total_return) ** (365 / days) - 1
    
    if max_drawdown_pct > 0:
        calmar_ratio = (annual_return * 100) / max_drawdown_pct
    else:
        calmar_ratio = 0
    
    # 6. Win Rate y Average Win/Loss (basado en transacciones cerradas)
    closed_trades = []
    
    # Analizar opciones cerradas
    closed_options = db.query(Option).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status.in_([OptionStatus.EXPIRED, OptionStatus.CLOSED])
    ).all()
    
    for opt in closed_options:
        if opt.realized_pnl is not None:
            closed_trades.append(opt.realized_pnl)
    
    wins = [t for t in closed_trades if t > 0]
    losses = [t for t in closed_trades if t < 0]
    
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0
    avg_win = (sum(wins) / len(wins)) if wins else 0
    avg_loss = (sum(losses) / len(losses)) if losses else 0
    
    # 7. Profit Factor
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    profit_factor = (total_wins / total_losses) if total_losses > 0 else 0
    
    # 8. Total Return
    total_return_pct = total_return * 100
    
    return {
        "period_days": days,
        "total_return": round(total_return_pct, 2),
        "annual_return": round(annual_return * 100, 2),
        "volatility": round(annual_volatility * 100, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "risk_free_rate": risk_free_rate * 100
    }
