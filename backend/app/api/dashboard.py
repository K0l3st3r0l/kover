from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Stock, Option, Transaction, TransactionType, OptionStatus
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService
from ..utils import OptionsCalculator

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
    
    # Opciones abiertas del usuario
    open_options = db.query(Option).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status == OptionStatus.OPEN
    ).count()
    
    # P&L realizado de ventas de acciones usando costo promedio histórico
    from collections import defaultdict
    all_txs_ordered = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_type.in_([TransactionType.BUY_STOCK, TransactionType.SELL_STOCK])
    ).order_by(Transaction.transaction_date).all()
    _running_shares: dict = defaultdict(float)
    _running_cost: dict = defaultdict(float)
    _sell_avg_cost: dict = {}
    for _tx in all_txs_ordered:
        if _tx.transaction_type == TransactionType.BUY_STOCK:
            _running_shares[_tx.ticker] += _tx.quantity
            _running_cost[_tx.ticker] += _tx.total_amount
        elif _tx.transaction_type == TransactionType.SELL_STOCK:
            _shares = _running_shares[_tx.ticker]
            _avg = (_running_cost[_tx.ticker] / _shares) if _shares > 0 else 0.0
            _sell_avg_cost[_tx.id] = _avg
            _running_shares[_tx.ticker] = max(0.0, _running_shares[_tx.ticker] - _tx.quantity)
            _running_cost[_tx.ticker] = max(0.0, _running_cost[_tx.ticker] - _tx.quantity * _avg)
    realized_stock_pnl = sum(
        tx.total_amount - tx.quantity * _sell_avg_cost.get(tx.id, 0.0)
        for tx in all_txs_ordered
        if tx.transaction_type == TransactionType.SELL_STOCK
    )

    # Capital total desplegado históricamente (suma de todos los BUY_STOCK)
    total_capital_deployed = sum(
        tx.total_amount for tx in all_txs_ordered
        if tx.transaction_type == TransactionType.BUY_STOCK
    )

    # P&L realizado de opciones: usamos total_premium_earned del modelo Stock
    # (neto de todas las primas cobradas - buybacks, open + closed)
    # Incluimos TODOS los stocks (activos e inactivos) para capturar primas históricas
    all_stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    total_premium_earned = sum(s.total_premium_earned or 0.0 for s in all_stocks)  # net options P&L

    # P&L total = precio puro + todas las primas netas + realizado acciones
    total_pnl = total_unrealized_pnl + total_premium_earned + realized_stock_pnl

    # ROI histórico: P&L total / capital históricamente desplegado
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
        "open_options": open_options,
        "realized_pnl": round(total_premium_earned, 2),  # alias: net option premiums
        "realized_stock_pnl": round(realized_stock_pnl, 2),
        "unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
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
    
    positions = []
    for stock in stocks:
        current_price = prices.get(stock.ticker)
        
        position_data = {
            "id": stock.id,
            "ticker": stock.ticker,
            "company_name": stock.company_name,
            "shares": stock.shares,
            "average_cost": stock.average_cost,
            "adjusted_cost_basis": stock.adjusted_cost_basis,
            "total_invested": stock.total_invested,
            "total_premium_earned": stock.total_premium_earned,
            "current_price": current_price,
        }
        
        if current_price:
            pnl = OptionsCalculator.calculate_position_pnl(
                stock.shares,
                stock.adjusted_cost_basis,
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
