from fastapi import APIRouter, HTTPException
from ..market import MarketDataService

router = APIRouter()

@router.get("/quote/{ticker}")
def get_quote(ticker: str):
    """Obtener cotización de una acción"""
    data = MarketDataService.get_stock_info(ticker)
    if not data:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return data

@router.get("/price/{ticker}")
def get_price(ticker: str):
    """Obtener solo el precio actual"""
    price = MarketDataService.get_current_price(ticker)
    if not price:
        raise HTTPException(status_code=404, detail="Price not available")
    return {"ticker": ticker, "price": price}

@router.get("/options/{ticker}")
def get_options_chain(ticker: str, expiration: str = None):
    """Obtener cadena de opciones"""
    data = MarketDataService.get_options_chain(ticker, expiration)
    if not data:
        raise HTTPException(status_code=404, detail="Options chain not available")
    return data

@router.get("/expirations/{ticker}")
def get_expirations(ticker: str):
    """Obtener fechas de expiración disponibles"""
    expirations = MarketDataService.get_available_expirations(ticker)
    if not expirations:
        raise HTTPException(status_code=404, detail="No expirations available")
    return {"ticker": ticker, "expirations": expirations}
