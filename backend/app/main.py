from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base
from .api import stocks, options, dashboard, market, auth, transactions, analytics, exports, watchlist, calculator

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
