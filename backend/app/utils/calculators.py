from typing import Dict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SANTIAGO_TZ = ZoneInfo('America/Santiago')

class OptionsCalculator:
    """Calculadora para métricas de opciones"""
    
    @staticmethod
    def calculate_covered_call_return(
        stock_price: float,
        strike_price: float,
        premium_received: float,
        shares: int = 100
    ) -> Dict[str, float]:
        """
        Calcula el retorno de un covered call
        """
        total_premium = premium_received * shares
        max_profit = (strike_price - stock_price) * shares + total_premium
        max_profit_pct = (max_profit / (stock_price * shares)) * 100
        
        # Precio de break-even (considerando que vendiste el call)
        break_even = stock_price - premium_received
        
        return {
            "total_premium": round(total_premium, 2),
            "max_profit": round(max_profit, 2),
            "max_profit_pct": round(max_profit_pct, 2),
            "break_even_price": round(break_even, 2),
        }
    
    @staticmethod
    def calculate_csp_return(
        strike_price: float,
        premium_received: float,
        shares: int = 100
    ) -> Dict[str, float]:
        """
        Calcula el retorno de un cash secured put
        """
        total_premium = premium_received * shares
        capital_required = strike_price * shares
        return_on_capital = (total_premium / capital_required) * 100
        
        # Precio efectivo de compra si te asignan
        effective_buy_price = strike_price - premium_received
        
        return {
            "total_premium": round(total_premium, 2),
            "capital_required": round(capital_required, 2),
            "return_on_capital": round(return_on_capital, 2),
            "effective_buy_price": round(effective_buy_price, 2),
        }
    
    @staticmethod
    def calculate_annualized_return(
        return_pct: float,
        days_to_expiration: int
    ) -> float:
        """Calcula el retorno anualizado"""
        if days_to_expiration == 0:
            return 0
        annual_return = (return_pct / days_to_expiration) * 365
        return round(annual_return, 2)
    
    @staticmethod
    def adjust_cost_basis(
        current_cost_basis: float,
        premium_earned: float,
        shares: int
    ) -> float:
        """
        Ajusta el costo base de las acciones después de ganar premium
        """
        premium_per_share = premium_earned / shares
        new_cost_basis = current_cost_basis - premium_per_share
        return round(new_cost_basis, 2)
    
    @staticmethod
    def calculate_days_to_expiration(expiration_date: datetime) -> int:
        """Calcula los días hasta la expiración según horario de Santiago de Chile.
        La fecha de expiración se trata como fecha calendario (sin conversión TZ).
        """
        # Normalize to UTC-aware if naive
        if expiration_date.tzinfo is None:
            expiration_date = expiration_date.replace(tzinfo=timezone.utc)
        # "Hoy" según Santiago de Chile
        today = datetime.now(SANTIAGO_TZ).date()
        # La fecha de expiración se toma como fecha calendario directa (sin convertir TZ)
        # porque fue guardada como medianoche UTC representando una fecha, no un instante
        exp_date = expiration_date.date()
        return max(0, (exp_date - today).days)
    
    @staticmethod
    def calculate_position_pnl(
        shares: float,
        average_cost: float,
        current_price: float
    ) -> Dict[str, float]:
        """Calcula el P&L de una posición de acciones"""
        total_cost = shares * average_cost
        current_value = shares * current_price
        unrealized_pnl = current_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost) * 100 if total_cost > 0 else 0
        
        return {
            "total_cost": round(total_cost, 2),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
        }
