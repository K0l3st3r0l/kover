from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, date
from io import StringIO
import csv
from ..database import get_db
from ..models import Stock, Option, Transaction, User, OptionStatus
from ..utils.auth import get_current_user

router = APIRouter()

@router.get("/transactions/csv")
async def export_transactions_csv(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exportar transacciones a CSV
    """
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    
    if start_date:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(Transaction.transaction_date <= end_date)
    
    transactions = query.order_by(Transaction.transaction_date.desc()).all()
    
    # Crear CSV en memoria
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        'Date',
        'Ticker',
        'Type',
        'Quantity',
        'Price',
        'Total Amount',
        'Commission',
        'Notes'
    ])
    
    # Datos
    for t in transactions:
        writer.writerow([
            t.transaction_date.strftime('%Y-%m-%d %H:%M:%S'),
            t.ticker,
            t.transaction_type.value,
            t.quantity,
            f"{t.price:.2f}",
            f"{t.total_amount:.2f}",
            f"{t.commission:.2f}",
            t.notes or ''
        ])
    
    output.seek(0)
    
    filename = f"kover_transactions_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/stocks/csv")
async def export_stocks_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exportar posiciones de stocks a CSV
    """
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        'Ticker',
        'Company Name',
        'Shares',
        'Average Cost',
        'Total Invested',
        'Adjusted Cost Basis',
        'Total Premium Earned',
        'Active',
        'Created At',
        'Notes'
    ])
    
    # Datos
    for stock in stocks:
        writer.writerow([
            stock.ticker,
            stock.company_name or '',
            stock.shares,
            f"{stock.average_cost:.2f}",
            f"{stock.total_invested:.2f}",
            f"{stock.adjusted_cost_basis:.2f}",
            f"{stock.total_premium_earned:.2f}",
            'Yes' if stock.is_active else 'No',
            stock.created_at.strftime('%Y-%m-%d') if stock.created_at else '',
            stock.notes or ''
        ])
    
    output.seek(0)
    
    filename = f"kover_stocks_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/options/csv")
async def export_options_csv(
    status: Optional[OptionStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exportar opciones a CSV
    """
    query = (
        db.query(Option)
        .join(Stock, Option.stock_id == Stock.id)
        .filter(Stock.user_id == current_user.id)
    )
    
    if status:
        query = query.filter(Option.status == status)
    
    options = query.order_by(Option.expiration_date).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        'Ticker',
        'Strategy',
        'Strike Price',
        'Expiration Date',
        'Contracts',
        'Premium per Contract',
        'Total Premium',
        'Status',
        'Opened At',
        'Closed At',
        'Realized P&L',
        'Notes'
    ])
    
    # Datos
    for opt in options:
        # Obtener el ticker del stock
        stock = db.query(Stock).filter(Stock.id == opt.stock_id).first()
        ticker = stock.ticker if stock else 'N/A'
        
        writer.writerow([
            ticker,
            opt.strategy.value if opt.strategy else '',
            f"{opt.strike_price:.2f}",
            opt.expiration_date.strftime('%Y-%m-%d'),
            opt.contracts,
            f"{opt.premium_per_contract:.2f}",
            f"{opt.total_premium:.2f}",
            opt.status.value,
            opt.opened_at.strftime('%Y-%m-%d') if opt.opened_at else '',
            opt.closed_at.strftime('%Y-%m-%d') if opt.closed_at else '',
            f"{opt.realized_pnl:.2f}" if opt.realized_pnl else '0.00',
            opt.notes or ''
        ])
    
    output.seek(0)
    
    filename = f"kover_options_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/portfolio/csv")
async def export_portfolio_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exportar resumen completo del portfolio a CSV
    """
    from ..market.market_data import MarketDataService
    
    stocks = db.query(Stock).filter(Stock.user_id == current_user.id).all()
    options = (
        db.query(Option)
        .join(Stock, Option.stock_id == Stock.id)
        .filter(
            Stock.user_id == current_user.id,
            Option.status == OptionStatus.OPEN
        )
        .all()
    )
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Sección: Stocks
    writer.writerow(['STOCK POSITIONS'])
    writer.writerow([
        'Ticker',
        'Shares',
        'Avg Cost',
        'Current Price',
        'Market Value',
        'Total Cost',
        'Unrealized P&L',
        'Unrealized P&L %'
    ])
    
    total_invested = 0
    total_market_value = 0
    
    for stock in stocks:
        current_price = MarketDataService.get_current_price(stock.ticker)
        market_value = (current_price * stock.shares) if current_price else stock.total_invested
        unrealized_pnl = market_value - stock.total_invested
        unrealized_pnl_pct = (unrealized_pnl / stock.total_invested * 100) if stock.total_invested > 0 else 0
        
        total_invested += stock.total_invested
        total_market_value += market_value
        
        writer.writerow([
            stock.ticker,
            stock.shares,
            f"{stock.adjusted_cost_basis:.2f}",
            f"{current_price:.2f}" if current_price else 'N/A',
            f"{market_value:.2f}",
            f"{stock.total_invested:.2f}",
            f"{unrealized_pnl:.2f}",
            f"{unrealized_pnl_pct:.2f}%"
        ])
    
    writer.writerow([])
    writer.writerow(['Total Invested', f"{total_invested:.2f}"])
    writer.writerow(['Total Market Value', f"{total_market_value:.2f}"])
    writer.writerow(['Total Unrealized P&L', f"{total_market_value - total_invested:.2f}"])
    
    # Sección: Options
    writer.writerow([])
    writer.writerow(['OPEN OPTIONS'])
    writer.writerow([
        'Ticker',
        'Strategy',
        'Strike',
        'Expiration',
        'Contracts',
        'Premium',
        'Days to Expiration'
    ])
    
    total_premium = 0
    
    for opt in options:
        stock = db.query(Stock).filter(Stock.id == opt.stock_id).first()
        ticker = stock.ticker if stock else 'N/A'
        days_to_exp = (opt.expiration_date - datetime.now().date()).days
        
        total_premium += opt.total_premium
        
        writer.writerow([
            ticker,
            opt.strategy.value if opt.strategy else '',
            f"{opt.strike_price:.2f}",
            opt.expiration_date.strftime('%Y-%m-%d'),
            opt.contracts,
            f"{opt.total_premium:.2f}",
            days_to_exp
        ])
    
    writer.writerow([])
    writer.writerow(['Total Premium Collected', f"{total_premium:.2f}"])
    
    output.seek(0)
    
    filename = f"kover_portfolio_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/tax-report/csv")
async def export_tax_report_csv(
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exportar reporte fiscal por año
    """
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31, 23, 59, 59)
    
    transactions = db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.transaction_date >= start_date,
        Transaction.transaction_date <= end_date
    ).order_by(Transaction.transaction_date).all()
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([f'TAX REPORT FOR YEAR {year}'])
    writer.writerow([f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'])
    writer.writerow([])
    
    # Resumen
    writer.writerow(['SUMMARY'])
    
    stock_purchases = sum(abs(t.total_amount) for t in transactions if t.transaction_type.value == 'BUY_STOCK')
    stock_sales = sum(abs(t.total_amount) for t in transactions if t.transaction_type.value == 'SELL_STOCK')
    premium_income = sum(abs(t.total_amount) for t in transactions if t.transaction_type.value in ['SELL_CALL', 'SELL_PUT'])
    dividends = sum(abs(t.total_amount) for t in transactions if t.transaction_type.value == 'DIVIDEND')
    total_commissions = sum(t.commission for t in transactions)
    
    writer.writerow(['Stock Purchases', f"${stock_purchases:.2f}"])
    writer.writerow(['Stock Sales', f"${stock_sales:.2f}"])
    writer.writerow(['Premium Income', f"${premium_income:.2f}"])
    writer.writerow(['Dividends', f"${dividends:.2f}"])
    writer.writerow(['Total Commissions', f"${total_commissions:.2f}"])
    
    writer.writerow([])
    writer.writerow(['DETAILED TRANSACTIONS'])
    writer.writerow([
        'Date',
        'Type',
        'Ticker',
        'Quantity',
        'Price',
        'Amount',
        'Commission'
    ])
    
    for t in transactions:
        writer.writerow([
            t.transaction_date.strftime('%Y-%m-%d'),
            t.transaction_type.value,
            t.ticker,
            t.quantity,
            f"${t.price:.2f}",
            f"${t.total_amount:.2f}",
            f"${t.commission:.2f}"
        ])
    
    output.seek(0)
    
    filename = f"kover_tax_report_{year}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
