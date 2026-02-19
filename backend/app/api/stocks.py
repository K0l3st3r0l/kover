from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from ..database import get_db
from ..models import Stock, Transaction, TransactionType
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService
from ..utils import OptionsCalculator

router = APIRouter()

# Schemas
class StockCreate(BaseModel):
    ticker: str
    shares: float
    purchase_price: float
    purchase_date: datetime
    notes: Optional[str] = None

class StockResponse(BaseModel):
    id: int
    ticker: str
    company_name: str
    shares: float
    average_cost: float
    total_invested: float
    total_premium_earned: float
    adjusted_cost_basis: float
    current_price: Optional[float] = None
    current_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

@router.post("/", response_model=StockResponse)
def create_stock(
    stock: StockCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Crear una nueva posición de acciones"""
    
    # Verificar si el ticker ya existe para este usuario
    existing = db.query(Stock).filter(
        Stock.ticker == stock.ticker.upper(),
        Stock.user_id == current_user.id
    ).first()
    if existing and existing.is_active:
        raise HTTPException(status_code=400, detail="Stock already exists")
    
    # Obtener info del mercado
    market_data = MarketDataService.get_stock_info(stock.ticker)
    if not market_data:
        raise HTTPException(status_code=404, detail="Invalid ticker symbol")
    
    # Crear la posición
    total_invested = stock.shares * stock.purchase_price
    new_stock = Stock(
        ticker=stock.ticker.upper(),
        company_name=market_data["company_name"],
        shares=stock.shares,
        average_cost=stock.purchase_price,
        total_invested=total_invested,
        adjusted_cost_basis=stock.purchase_price,
        notes=stock.notes,
        user_id=current_user.id
    )
    
    db.add(new_stock)
    db.flush()
    
    # Registrar la transacción
    transaction = Transaction(
        user_id=current_user.id,
        stock_id=new_stock.id,
        ticker=new_stock.ticker,
        transaction_type=TransactionType.BUY_STOCK,
        quantity=stock.shares,
        price=stock.purchase_price,
        total_amount=total_invested,
        transaction_date=stock.purchase_date
    )
    
    db.add(transaction)
    db.commit()
    db.refresh(new_stock)
    
    # Agregar precio actual
    response = StockResponse.from_orm(new_stock)
    current_price = MarketDataService.get_current_price(new_stock.ticker)
    if current_price:
        response.current_price = current_price
        pnl = OptionsCalculator.calculate_position_pnl(
            new_stock.shares,
            new_stock.adjusted_cost_basis,
            current_price
        )
        response.current_value = pnl["current_value"]
        response.unrealized_pnl = pnl["unrealized_pnl"]
        response.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
    
    return response

@router.get("/", response_model=List[StockResponse])
def get_stocks(
    include_inactive: bool = False, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener todas las posiciones de acciones"""
    query = db.query(Stock).filter(Stock.user_id == current_user.id)
    if not include_inactive:
        query = query.filter(Stock.is_active == True)
    
    stocks = query.all()
    
    # Obtener precios actuales para todas las acciones
    tickers = [s.ticker for s in stocks]
    prices = MarketDataService.get_multiple_prices(tickers)
    
    results = []
    for stock in stocks:
        response = StockResponse.from_orm(stock)
        current_price = prices.get(stock.ticker)
        
        if current_price:
            response.current_price = current_price
            pnl = OptionsCalculator.calculate_position_pnl(
                stock.shares,
                stock.adjusted_cost_basis,
                current_price
            )
            response.current_value = pnl["current_value"]
            response.unrealized_pnl = pnl["unrealized_pnl"]
            response.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
        
        results.append(response)
    
    return results

@router.get("/{stock_id}", response_model=StockResponse)
def get_stock(
    stock_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener una posición específica"""
    stock = db.query(Stock).filter(
        Stock.id == stock_id,
        Stock.user_id == current_user.id
    ).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    response = StockResponse.from_orm(stock)
    current_price = MarketDataService.get_current_price(stock.ticker)
    
    if current_price:
        response.current_price = current_price
        pnl = OptionsCalculator.calculate_position_pnl(
            stock.shares,
            stock.adjusted_cost_basis,
            current_price
        )
        response.current_value = pnl["current_value"]
        response.unrealized_pnl = pnl["unrealized_pnl"]
        response.unrealized_pnl_pct = pnl["unrealized_pnl_pct"]
    
    return response

@router.delete("/{stock_id}")
def delete_stock(
    stock_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Eliminar (desactivar) una posición"""
    stock = db.query(Stock).filter(
        Stock.id == stock_id,
        Stock.user_id == current_user.id
    ).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    
    stock.is_active = False
    db.commit()
    
    return {"message": "Stock deactivated successfully"}

@router.get("/search/advanced", response_model=List[StockResponse])
def search_stocks_advanced(
    ticker: Optional[str] = Query(None, description="Filter by ticker symbol (partial match)"),
    min_price: Optional[float] = Query(None, description="Minimum current price"),
    max_price: Optional[float] = Query(None, description="Maximum current price"),
    min_shares: Optional[float] = Query(None, description="Minimum shares owned"),
    max_shares: Optional[float] = Query(None, description="Maximum shares owned"),
    min_pnl_pct: Optional[float] = Query(None, description="Minimum P&L percentage"),
    max_pnl_pct: Optional[float] = Query(None, description="Maximum P&L percentage"),
    profitable_only: Optional[bool] = Query(None, description="Show only profitable positions"),
    losing_only: Optional[bool] = Query(None, description="Show only losing positions"),
    sort_by: Optional[str] = Query("ticker", description="Sort field: ticker, shares, current_price, pnl_pct"),
    sort_order: Optional[str] = Query("asc", description="Sort order: asc or desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Búsqueda avanzada de stocks con múltiples filtros"""
    
    # Base query
    query = db.query(Stock).filter(
        Stock.user_id == current_user.id,
        Stock.is_active == True
    )
    
    # Aplicar filtro de ticker
    if ticker:
        query = query.filter(Stock.ticker.ilike(f"%{ticker.upper()}%"))
    
    # Aplicar filtro de shares
    if min_shares is not None:
        query = query.filter(Stock.shares >= min_shares)
    if max_shares is not None:
        query = query.filter(Stock.shares <= max_shares)
    
    stocks = query.all()
    
    # Obtener precios actuales
    tickers = [s.ticker for s in stocks]
    prices = MarketDataService.get_multiple_prices(tickers)
    
    results = []
    for stock in stocks:
        current_price = prices.get(stock.ticker)
        
        # Si no hay precio, omitir filtros basados en precio
        if current_price:
            # Filtros de precio
            if min_price is not None and current_price < min_price:
                continue
            if max_price is not None and current_price > max_price:
                continue
            
            # Calcular P&L
            pnl = OptionsCalculator.calculate_position_pnl(
                stock.shares,
                stock.adjusted_cost_basis,
                current_price
            )
            
            pnl_pct = pnl["unrealized_pnl_pct"]
            
            # Filtros de P&L
            if min_pnl_pct is not None and pnl_pct < min_pnl_pct:
                continue
            if max_pnl_pct is not None and pnl_pct > max_pnl_pct:
                continue
            if profitable_only and pnl_pct <= 0:
                continue
            if losing_only and pnl_pct >= 0:
                continue
            
            response = StockResponse.from_orm(stock)
            response.current_price = current_price
            response.current_value = pnl["current_value"]
            response.unrealized_pnl = pnl["unrealized_pnl"]
            response.unrealized_pnl_pct = pnl_pct
            
            results.append(response)
        else:
            # Sin precio, agregar sin filtros de precio/pnl
            if not (min_price or max_price or min_pnl_pct or max_pnl_pct or profitable_only or losing_only):
                response = StockResponse.from_orm(stock)
                results.append(response)
    
    # Ordenamiento
    reverse = sort_order.lower() == "desc"
    
    if sort_by == "ticker":
        results.sort(key=lambda x: x.ticker, reverse=reverse)
    elif sort_by == "shares":
        results.sort(key=lambda x: x.shares, reverse=reverse)
    elif sort_by == "current_price":
        results.sort(key=lambda x: x.current_price or 0, reverse=reverse)
    elif sort_by == "pnl_pct":
        results.sort(key=lambda x: x.unrealized_pnl_pct or 0, reverse=reverse)
    
    return results
