from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from ..database import get_db
from ..models import Stock, User
from ..utils.auth import get_current_user
from ..market.market_data import MarketDataService
import math

router = APIRouter()

class StrategyRecommendation(BaseModel):
    strategy_type: str
    strike_price: float
    premium_estimate: float
    probability_profit: float
    max_profit: float
    max_loss: float
    breakeven_price: float
    days_to_expiration: int
    annualized_return: float
    recommendation_score: float
    notes: str

@router.get("/covered-call")
async def calculate_covered_call_strategy(
    ticker: str = Query(..., description="Stock ticker symbol"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Calcular estrategia óptima de Covered Call
    """
    # Verificar si el usuario tiene el stock
    stock = db.query(Stock).filter(
        Stock.user_id == current_user.id,
        Stock.ticker == ticker.upper()
    ).first()
    
    if not stock:
        return {
            "error": "You don't own this stock",
            "recommendations": []
        }
    
    # Obtener precio actual
    current_price = MarketDataService.get_current_price(ticker)
    if not current_price:
        return {
            "error": "Unable to fetch current price",
            "recommendations": []
        }
    
    recommendations = []
    
    # Calcular strikes sugeridos (5%, 10%, 15% OTM)
    strike_multipliers = [1.05, 1.10, 1.15, 1.20]
    expirations = [30, 45, 60]  # días
    
    for multiplier in strike_multipliers:
        for dte in expirations:
            strike = round(current_price * multiplier, 2)
            
            # Estimar premium (simplificado - en producción usar datos reales de opciones)
            # Premium = 2-4% del precio del stock para OTM
            distance_pct = (multiplier - 1) * 100
            premium_pct = max(0.5, 4 - distance_pct/5)  # Menos premium mientras más OTM
            premium_per_share = current_price * (premium_pct / 100)
            total_premium = premium_per_share * 100  # Por contrato
            
            # Calcular métricas
            max_profit = total_premium + ((strike - current_price) * 100)
            max_loss = (stock.adjusted_cost_basis - strike) * 100  # Si el precio cae
            breakeven = stock.adjusted_cost_basis - (premium_per_share)
            
            # Probabilidad de profit (simplificada)
            otm_pct = ((strike - current_price) / current_price) * 100
            probability = min(95, 50 + otm_pct * 2)  # Más OTM = más probable que expire sin valor
            
            # ROI anualizado
            roi_per_trade = (total_premium / (current_price * 100)) * 100
            annualized_roi = (roi_per_trade * 365 / dte)
            
            # Score de recomendación (balance entre premium y probabilidad)
            score = (probability / 100) * annualized_roi
            
            notes = []
            if otm_pct < 3:
                notes.append("⚠️ Very close to current price - high assignment risk")
            elif otm_pct > 15:
                notes.append("✅ Safe distance - low assignment risk")
            
            if annualized_roi > 25:
                notes.append("💰 Excellent annualized return")
            elif annualized_roi > 15:
                notes.append("👍 Good return")
            
            if dte <= 30:
                notes.append("⏱️ Quick expiration - theta decay accelerates")
            
            recommendations.append(StrategyRecommendation(
                strategy_type="Covered Call",
                strike_price=strike,
                premium_estimate=round(total_premium, 2),
                probability_profit=round(probability, 1),
                max_profit=round(max_profit, 2),
                max_loss=round(max_loss, 2) if max_loss > 0 else 0,
                breakeven_price=round(breakeven, 2),
                days_to_expiration=dte,
                annualized_return=round(annualized_roi, 2),
                recommendation_score=round(score, 2),
                notes=" | ".join(notes) if notes else "Standard covered call position"
            ))
    
    # Ordenar por score
    recommendations.sort(key=lambda x: x.recommendation_score, reverse=True)
    
    return {
        "ticker": ticker.upper(),
        "current_price": current_price,
        "shares_owned": stock.shares,
        "cost_basis": stock.adjusted_cost_basis,
        "recommendations": recommendations[:6]  # Top 6
    }

@router.get("/cash-secured-put")
async def calculate_cash_secured_put_strategy(
    ticker: str = Query(..., description="Stock ticker symbol"),
    capital_available: float = Query(10000, description="Capital available for assignment"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Calcular estrategia óptima de Cash-Secured Put
    """
    # Obtener precio actual
    current_price = MarketDataService.get_current_price(ticker)
    if not current_price:
        return {
            "error": "Unable to fetch current price",
            "recommendations": []
        }
    
    # Verificar que tenga capital suficiente
    required_capital = current_price * 100  # Por contrato
    max_contracts = int(capital_available / required_capital)
    
    if max_contracts < 1:
        return {
            "error": f"Insufficient capital. Need ${required_capital:.2f} per contract",
            "recommendations": []
        }
    
    recommendations = []
    
    # Calcular strikes sugeridos (5%, 10%, 15% ITM/ATM/OTM)
    strike_multipliers = [0.85, 0.90, 0.95, 1.00]
    expirations = [30, 45, 60]
    
    for multiplier in strike_multipliers:
        for dte in expirations:
            strike = round(current_price * multiplier, 2)
            
            # Estimar premium
            distance_pct = abs((multiplier - 1) * 100)
            if multiplier < 1:  # OTM puts tienen mejor premium
                premium_pct = 2 + distance_pct/3
            else:
                premium_pct = 1.5
            
            premium_per_share = strike * (premium_pct / 100)
            total_premium = premium_per_share * 100
            
            # Métricas
            effective_buy_price = strike - premium_per_share
            max_profit = total_premium
            max_loss = (effective_buy_price * 100) - total_premium  # Si el stock va a cero
            
            # ROI
            roi_per_trade = (total_premium / required_capital) * 100
            annualized_roi = (roi_per_trade * 365 / dte)
            
            # Probabilidad (OTM tiene más probabilidad de expirar sin valor)
            otm_pct = ((current_price - strike) / current_price) * 100
            probability = min(95, 40 + otm_pct * 3)
            
            # Score
            score = (probability / 100) * annualized_roi
            
            notes = []
            if multiplier >= 1:
                notes.append("⚠️ At or above current price - likely assignment")
            elif otm_pct > 10:
                notes.append("✅ Good safety margin")
            
            if annualized_roi > 20:
                notes.append("💰 Excellent return if assigned")
            
            notes.append(f"🎯 Effective buy price: ${effective_buy_price:.2f}")
            
            recommendations.append(StrategyRecommendation(
                strategy_type="Cash-Secured Put",
                strike_price=strike,
                premium_estimate=round(total_premium, 2),
                probability_profit=round(probability, 1),
                max_profit=round(max_profit, 2),
                max_loss=round(max_loss, 2),
                breakeven_price=round(strike - premium_per_share, 2),
                days_to_expiration=dte,
                annualized_return=round(annualized_roi, 2),
                recommendation_score=round(score, 2),
                notes=" | ".join(notes)
            ))
    
    recommendations.sort(key=lambda x: x.recommendation_score, reverse=True)
    
    return {
        "ticker": ticker.upper(),
        "current_price": current_price,
        "capital_available": capital_available,
        "max_contracts": max_contracts,
        "required_capital_per_contract": required_capital,
        "recommendations": recommendations[:6]
    }

@router.get("/wheel-strategy")
async def calculate_wheel_strategy(
    ticker: str = Query(..., description="Stock ticker symbol"),
    capital: float = Query(10000, description="Starting capital"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Calcular proyección de Wheel Strategy (CSP + Covered Calls)
    """
    current_price = MarketDataService.get_current_price(ticker)
    if not current_price:
        return {"error": "Unable to fetch current price"}
    
    # Simular 12 meses de wheel strategy
    monthly_return_low = 2.5  # 2.5% mensual conservador
    monthly_return_high = 4.0  # 4% mensual agresivo
    
    projection_conservative = []
    projection_aggressive = []
    
    capital_conservative = capital
    capital_aggressive = capital
    
    for month in range(1, 13):
        # Conservador
        monthly_gain_cons = capital_conservative * (monthly_return_low / 100)
        capital_conservative += monthly_gain_cons
        projection_conservative.append({
            "month": month,
            "capital": round(capital_conservative, 2),
            "monthly_gain": round(monthly_gain_cons, 2),
            "total_gain": round(capital_conservative - capital, 2)
        })
        
        # Agresivo
        monthly_gain_agg = capital_aggressive * (monthly_return_high / 100)
        capital_aggressive += monthly_gain_agg
        projection_aggressive.append({
            "month": month,
            "capital": round(capital_aggressive, 2),
            "monthly_gain": round(monthly_gain_agg, 2),
            "total_gain": round(capital_aggressive - capital, 2)
        })
    
    return {
        "ticker": ticker.upper(),
        "current_price": current_price,
        "starting_capital": capital,
        "conservative_scenario": {
            "monthly_return": monthly_return_low,
            "projected_annual_return": round((capital_conservative / capital - 1) * 100, 2),
            "final_capital": round(capital_conservative, 2),
            "total_profit": round(capital_conservative - capital, 2),
            "projection": projection_conservative
        },
        "aggressive_scenario": {
            "monthly_return": monthly_return_high,
            "projected_annual_return": round((capital_aggressive / capital - 1) * 100, 2),
            "final_capital": round(capital_aggressive, 2),
            "total_profit": round(capital_aggressive - capital, 2),
            "projection": projection_aggressive
        },
        "notes": [
            "Conservative: Safe strikes, lower premiums",
            "Aggressive: Closer strikes, higher premiums but more assignment risk",
            "Actual results depend on market conditions and strike selection",
            "Wheel strategy combines CSP (to acquire stock) + Covered Calls (once assigned)"
        ]
    }
