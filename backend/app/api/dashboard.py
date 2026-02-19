from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models import Stock, Option, Transaction, OptionStatus
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
    total_premium_earned = sum(s.total_premium_earned for s in stocks)
    
    current_portfolio_value = 0
    total_unrealized_pnl = 0
    
    for stock in stocks:
        current_price = prices.get(stock.ticker)
        if current_price:
            pnl = OptionsCalculator.calculate_position_pnl(
                stock.shares,
                stock.adjusted_cost_basis,
                current_price
            )
            current_portfolio_value += pnl["current_value"]
            total_unrealized_pnl += pnl["unrealized_pnl"]
    
    # Opciones abiertas del usuario
    open_options = db.query(Option).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status == OptionStatus.OPEN
    ).count()
    
    # P&L realizado de opciones cerradas del usuario
    realized_pnl = db.query(func.sum(Option.realized_pnl)).join(Stock).filter(
        Stock.user_id == current_user.id,
        Option.status.in_([OptionStatus.CLOSED, OptionStatus.EXPIRED])
    ).scalar() or 0
    
    # Total P&L (realizado + no realizado)
    total_pnl = realized_pnl + total_unrealized_pnl
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
    
    return {
        "total_stocks": total_stocks,
        "total_invested": round(total_invested, 2),
        "current_portfolio_value": round(current_portfolio_value, 2),
        "total_premium_earned": round(total_premium_earned, 2),
        "open_options": open_options,
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
    }

@router.get("/positions")
def get_positions_overview(db: Session = Depends(get_db)):
    """Obtener vista general de todas las posiciones con precios actuales"""
    
    stocks = db.query(Stock).filter(Stock.is_active == True).all()
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
