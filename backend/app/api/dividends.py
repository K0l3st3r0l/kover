from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.stock import Stock
from ..models.transaction import Transaction, TransactionType
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService

router = APIRouter()


@router.get("/portfolio")
def get_portfolio_dividends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stocks = (
        db.query(Stock)
        .filter(Stock.user_id == current_user.id, Stock.is_active == True)
        .all()
    )

    positions = []
    total_annual_income = 0.0

    for stock in stocks:
        info = MarketDataService.get_dividend_info(stock.ticker)
        if not info:
            info = {
                "ticker": stock.ticker,
                "company_name": stock.company_name or stock.ticker,
                "dividend_yield": None,
                "dividend_rate": None,
                "ex_dividend_date": None,
                "payout_ratio": None,
                "five_year_avg_yield": None,
                "trailing_annual_dividend_yield": None,
                "trailing_annual_dividend_rate": None,
                "recent_dividends": [],
                "pays_dividend": False,
            }

        rate = info.get("dividend_rate") or info.get("trailing_annual_dividend_rate") or 0.0
        annual_income = round(rate * stock.shares, 2) if rate else 0.0
        total_annual_income += annual_income

        positions.append({
            **info,
            "shares": stock.shares,
            "annual_income_projection": annual_income,
            "stock_id": stock.id,
        })

    # Sort: dividend payers first, then by annual income desc
    positions.sort(key=lambda x: (not x["pays_dividend"], -x["annual_income_projection"]))

    return {
        "positions": positions,
        "total_annual_income": round(total_annual_income, 2),
        "payers_count": sum(1 for p in positions if p["pays_dividend"]),
    }


@router.get("/history")
def get_dividend_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    txs = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.transaction_type == TransactionType.DIVIDEND,
        )
        .order_by(Transaction.transaction_date.desc())
        .all()
    )

    history = [
        {
            "id": tx.id,
            "ticker": tx.ticker,
            "amount": round(float(tx.total_amount), 2),
            "shares": float(tx.quantity),
            "price_per_share": round(float(tx.price), 4),
            "date": tx.transaction_date.isoformat(),
            "notes": tx.notes,
        }
        for tx in txs
    ]

    total_received = round(sum(h["amount"] for h in history), 2)

    # Group by ticker
    by_ticker: dict = {}
    for h in history:
        by_ticker.setdefault(h["ticker"], 0.0)
        by_ticker[h["ticker"]] += h["amount"]
    by_ticker_list = [
        {"ticker": k, "total": round(v, 2)}
        for k, v in sorted(by_ticker.items(), key=lambda x: -x[1])
    ]

    # Group by year
    by_year: dict = {}
    for h in history:
        year = h["date"][:4]
        by_year.setdefault(year, 0.0)
        by_year[year] += h["amount"]
    by_year_list = [
        {"year": k, "total": round(v, 2)}
        for k, v in sorted(by_year.items())
    ]

    # Group by month (last 24 months)
    by_month: dict = {}
    for h in history:
        month = h["date"][:7]
        by_month.setdefault(month, 0.0)
        by_month[month] += h["amount"]
    by_month_list = [
        {"month": k, "total": round(v, 2)}
        for k, v in sorted(by_month.items())
    ][-24:]

    return {
        "history": history,
        "total_received": total_received,
        "by_ticker": by_ticker_list,
        "by_year": by_year_list,
        "by_month": by_month_list,
    }
