from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from ..database import get_db
from ..models import Watchlist, User
from ..utils.auth import get_current_user
from ..market.market_data import MarketDataService

router = APIRouter()

# Schemas
class WatchlistCreate(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    target_price: Optional[float] = None
    notes: Optional[str] = None

class WatchlistUpdate(BaseModel):
    company_name: Optional[str] = None
    target_price: Optional[float] = None
    notes: Optional[str] = None

class WatchlistResponse(BaseModel):
    id: int
    ticker: str
    company_name: Optional[str]
    target_price: Optional[float]
    notes: Optional[str]
    current_price: Optional[float]
    price_change: Optional[float]
    price_change_pct: Optional[float]
    distance_to_target: Optional[float]
    distance_to_target_pct: Optional[float]
    added_at: datetime
    
    class Config:
        from_attributes = True

@router.get("/", response_model=List[WatchlistResponse])
async def get_watchlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener todos los tickers en watchlist del usuario
    """
    watchlist_items = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id
    ).order_by(Watchlist.added_at.desc()).all()
    
    # Enriquecer con datos de mercado
    response = []
    for item in watchlist_items:
        current_price = MarketDataService.get_current_price(item.ticker)
        
        item_dict = {
            "id": item.id,
            "ticker": item.ticker,
            "company_name": item.company_name,
            "target_price": item.target_price,
            "notes": item.notes,
            "added_at": item.added_at,
            "current_price": current_price,
            "price_change": None,
            "price_change_pct": None,
            "distance_to_target": None,
            "distance_to_target_pct": None
        }
        
        # Calcular distancia al precio objetivo
        if current_price and item.target_price:
            item_dict["distance_to_target"] = item.target_price - current_price
            item_dict["distance_to_target_pct"] = ((item.target_price - current_price) / current_price) * 100
        
        response.append(WatchlistResponse(**item_dict))
    
    return response

@router.get("/search")
async def search_tickers(
    q: str,
    current_user: User = Depends(get_current_user)
):
    """
    Buscar instrumentos por nombre o ticker usando Yahoo Finance
    """
    import requests as req
    import yfinance as yf
    if not q or len(q.strip()) < 1:
        return []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    try:
        # Step 1: search symbols
        resp = req.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": q.strip(), "quotesCount": 8, "newsCount": 0, "enableFuzzyQuery": "true", "enableCb": "false"},
            headers=headers,
            timeout=6,
        )
        resp.raise_for_status()
        quotes_raw = [item for item in resp.json().get("quotes", []) if item.get("symbol")]
        if not quotes_raw:
            return []

        # Step 2: batch price lookup via yfinance
        symbols = [item["symbol"] for item in quotes_raw]
        prices: dict = {}
        try:
            batch = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    p = getattr(batch.tickers[sym].fast_info, "last_price", None)
                    if p is not None:
                        prices[sym] = round(float(p), 4)
                except Exception:
                    pass
        except Exception:
            pass

        return [
            {
                "symbol": item["symbol"],
                "name": item.get("longname") or item.get("shortname") or item["symbol"],
                "exchange": item.get("exchange", ""),
                "type": item.get("quoteType", ""),
                "price": prices.get(item["symbol"]),
            }
            for item in quotes_raw
        ]
    except Exception:
        return []


@router.post("/", response_model=WatchlistResponse)
async def add_to_watchlist(
    watchlist_item: WatchlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Agregar un ticker a la watchlist
    """
    # Validar que el ticker no esté ya en la watchlist
    existing = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id,
        Watchlist.ticker == watchlist_item.ticker.upper()
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Ticker already in watchlist")
    
    # Obtener información del ticker si no se proporciona
    company_name = watchlist_item.company_name
    if not company_name:
        # Intentar obtener el nombre de la empresa del servicio de mercado
        company_name = watchlist_item.ticker.upper()
    
    new_item = Watchlist(
        user_id=current_user.id,
        ticker=watchlist_item.ticker.upper(),
        company_name=company_name,
        target_price=watchlist_item.target_price,
        notes=watchlist_item.notes
    )
    
    try:
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ticker already in watchlist")
    
    # Obtener precio actual
    current_price = MarketDataService.get_current_price(new_item.ticker)
    
    response_dict = {
        "id": new_item.id,
        "ticker": new_item.ticker,
        "company_name": new_item.company_name,
        "target_price": new_item.target_price,
        "notes": new_item.notes,
        "added_at": new_item.added_at,
        "current_price": current_price,
        "price_change": None,
        "price_change_pct": None,
        "distance_to_target": None,
        "distance_to_target_pct": None
    }
    
    if current_price and new_item.target_price:
        response_dict["distance_to_target"] = new_item.target_price - current_price
        response_dict["distance_to_target_pct"] = ((new_item.target_price - current_price) / current_price) * 100
    
    return WatchlistResponse(**response_dict)

@router.put("/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist_item(
    watchlist_id: int,
    update_data: WatchlistUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualizar un item de la watchlist
    """
    item = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    # Actualizar campos
    if update_data.company_name is not None:
        item.company_name = update_data.company_name
    if update_data.target_price is not None:
        item.target_price = update_data.target_price
    if update_data.notes is not None:
        item.notes = update_data.notes
    
    item.updated_at = datetime.now()
    
    db.commit()
    db.refresh(item)
    
    # Obtener precio actual
    current_price = MarketDataService.get_current_price(item.ticker)
    
    response_dict = {
        "id": item.id,
        "ticker": item.ticker,
        "company_name": item.company_name,
        "target_price": item.target_price,
        "notes": item.notes,
        "added_at": item.added_at,
        "current_price": current_price,
        "price_change": None,
        "price_change_pct": None,
        "distance_to_target": None,
        "distance_to_target_pct": None
    }
    
    if current_price and item.target_price:
        response_dict["distance_to_target"] = item.target_price - current_price
        response_dict["distance_to_target_pct"] = ((item.target_price - current_price) / current_price) * 100
    
    return WatchlistResponse(**response_dict)

@router.delete("/{watchlist_id}")
async def remove_from_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Eliminar un ticker de la watchlist
    """
    item = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == current_user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    db.delete(item)
    db.commit()
    
    return {"message": "Ticker removed from watchlist"}

@router.get("/check/{ticker}")
async def check_ticker_in_watchlist(
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verificar si un ticker está en la watchlist
    """
    item = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id,
        Watchlist.ticker == ticker.upper()
    ).first()
    
    return {
        "in_watchlist": item is not None,
        "item_id": item.id if item else None
    }
