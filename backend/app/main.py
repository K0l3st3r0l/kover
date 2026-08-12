import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base
from .logging_config import configure_logging, get_logger
from .api import stocks, options, dashboard, market, auth, transactions, analytics, exports, watchlist, calculator, fiscal, import_ib, chilean_markets, news, dividends, campaigns, data_health, fundamentals, scanner
from .jobs.scheduler import shutdown_scheduler, start_scheduler

configure_logging()
logger = get_logger(__name__)

# Crear las tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Kover API",
    description="Options Trading Portfolio Manager",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especifica tu dominio
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["stocks"])
app.include_router(options.router, prefix="/api/options", tags=["options"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["transactions"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(calculator.router, prefix="/api/calculator", tags=["calculator"])
app.include_router(fiscal.router, prefix="/api/fiscal", tags=["fiscal"])
app.include_router(import_ib.router, prefix="/api/import-ib", tags=["import-ib"])
app.include_router(chilean_markets.router, prefix="/api/market", tags=["chilean-markets"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(dividends.router, prefix="/api/dividends", tags=["dividends"])
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["campaigns"])
app.include_router(data_health.router, prefix="/api/data-health", tags=["data-health"])
app.include_router(fundamentals.router, prefix="/api/instruments", tags=["fundamentals"])
app.include_router(scanner.router, prefix="/api/scanner", tags=["scanner"])

@app.on_event("startup")
def _start_ai_committee_loop():
    if chilean_markets.AI_API_KEY:
        threading.Thread(target=chilean_markets.ai_committee_background_loop, daemon=True).start()


@app.on_event("startup")
def _start_scheduler():
    start_scheduler()


@app.on_event("shutdown")
def _stop_scheduler():
    shutdown_scheduler()

@app.get("/")
async def root():
    return {
        "app": "Kover API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
