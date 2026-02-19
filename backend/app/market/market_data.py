"""
MarketDataService — multi-source stock data with automatic fallback

Source priority (each tried in order until one succeeds):
  1. yfinance          — Yahoo Finance Python lib (primary)
  2. Yahoo v8 HTTP     — Direct Yahoo Finance JSON endpoint (no key)
  3. Stooq             — stooq.com CSV feed, ~15 min delay (no key)
  4. Alpha Vantage     — Optional; set ALPHA_VANTAGE_KEY env var (free: 25 req/day)
  5. Finnhub           — Optional; set FINNHUB_KEY env var (free: 60 req/min)
"""

import os
import re
import time
import requests
import yfinance as yf
import pandas as pd
from typing import Dict, Optional, List
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Config & helpers
# ---------------------------------------------------------------------------

VALID_TICKER_PATTERN = re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$')

ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
FINNHUB_KEY       = os.getenv("FINNHUB_KEY", "")

# Simple in-memory price cache: { ticker: (price, timestamp) }
_price_cache: Dict[str, tuple] = {}
CACHE_TTL = 300  # 5 min

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _cached_price(ticker: str) -> Optional[float]:
    entry = _price_cache.get(ticker)
    if entry:
        price, ts = entry
        if time.time() - ts < CACHE_TTL:
            return price
    return None


def _set_cache(ticker: str, price: float):
    _price_cache[ticker] = (price, time.time())


def _empty_info(ticker: str) -> Dict:
    """Fallback dict when no source can provide full info."""
    return {
        "ticker": ticker.upper(),
        "company_name": ticker.upper(),
        "current_price": None,
        "previous_close": None,
        "open": None,
        "day_high": None,
        "day_low": None,
        "volume": None,
        "market_cap": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "pe_ratio": None,
        "dividend_yield": None,
        "sector": None,
        "industry": None,
    }


# ---------------------------------------------------------------------------
# Source 1 — yfinance
# ---------------------------------------------------------------------------

def _price_yfinance(ticker: str) -> Optional[float]:
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception as e:
        print(f"[yfinance] price error for {ticker}: {e}")
    return None


def _info_yfinance(ticker: str) -> Optional[Dict]:
    try:
        info = yf.Ticker(ticker).info
        company_name = info.get("longName") or info.get("shortName") or ticker.upper()
        return {
            "ticker": ticker.upper(),
            "company_name": company_name,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose"),
            "open": info.get("open"),
            "day_high": info.get("dayHigh"),
            "day_low": info.get("dayLow"),
            "volume": info.get("volume"),
            "market_cap": info.get("marketCap"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "pe_ratio": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception as e:
        print(f"[yfinance] info error for {ticker}: {e}")
    return None


# ---------------------------------------------------------------------------
# Source 2 — Yahoo Finance v8 / v7 direct HTTP
# ---------------------------------------------------------------------------

def _price_yahoo_v8(ticker: str) -> Optional[float]:
    """Direct call to Yahoo Finance chart API v8. ~15 min delay."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        return float(price) if price else None
    except Exception as e:
        print(f"[yahoo_v8] price error for {ticker}: {e}")
    return None


def _info_yahoo_v7(ticker: str) -> Optional[Dict]:
    try:
        url = (
            f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
            f"&fields=longName,shortName,regularMarketPrice,regularMarketPreviousClose,"
            f"regularMarketOpen,regularMarketDayHigh,regularMarketDayLow,"
            f"regularMarketVolume,marketCap,fiftyTwoWeekHigh,fiftyTwoWeekLow,"
            f"trailingPE,dividendYield,sector,industry"
        )
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        result = resp.json()["quoteResponse"]["result"]
        if not result:
            return None
        q = result[0]
        return {
            "ticker": ticker.upper(),
            "company_name": q.get("longName") or q.get("shortName") or ticker.upper(),
            "current_price": q.get("regularMarketPrice"),
            "previous_close": q.get("regularMarketPreviousClose"),
            "open": q.get("regularMarketOpen"),
            "day_high": q.get("regularMarketDayHigh"),
            "day_low": q.get("regularMarketDayLow"),
            "volume": q.get("regularMarketVolume"),
            "market_cap": q.get("marketCap"),
            "fifty_two_week_high": q.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": q.get("fiftyTwoWeekLow"),
            "pe_ratio": q.get("trailingPE"),
            "dividend_yield": q.get("dividendYield"),
            "sector": q.get("sector"),
            "industry": q.get("industry"),
        }
    except Exception as e:
        print(f"[yahoo_v7] info error for {ticker}: {e}")
    return None


# ---------------------------------------------------------------------------
# Source 3 — Stooq (free, no key, ~15 min delay)
# ---------------------------------------------------------------------------

def _price_stooq(ticker: str) -> Optional[float]:
    """
    Stooq provides delayed prices for most US equities.
    CSV format: Symbol,Date,Time,Open,High,Low,Close,Volume
    """
    try:
        stooq_symbol = ticker.lower() + ".us"
        url = f"https://stooq.com/q/l/?s={stooq_symbol}&f=sd2t2ohlcv&h&e=csv"
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split(",")
        # index 6 = Close
        if len(parts) < 7 or parts[6] in ("N/D", ""):
            return None
        return float(parts[6])
    except Exception as e:
        print(f"[stooq] error for {ticker}: {e}")
    return None


# ---------------------------------------------------------------------------
# Source 4 — Alpha Vantage (optional free key via ALPHA_VANTAGE_KEY env var)
# ---------------------------------------------------------------------------

def _price_alpha_vantage(ticker: str) -> Optional[float]:
    if not ALPHA_VANTAGE_KEY:
        return None
    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=GLOBAL_QUOTE&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}"
        )
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        price_str = resp.json().get("Global Quote", {}).get("05. price")
        return float(price_str) if price_str else None
    except Exception as e:
        print(f"[alpha_vantage] error for {ticker}: {e}")
    return None


# ---------------------------------------------------------------------------
# Source 5 — Finnhub (optional free key via FINNHUB_KEY env var)
# ---------------------------------------------------------------------------

def _price_finnhub(ticker: str) -> Optional[float]:
    if not FINNHUB_KEY:
        return None
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        price = resp.json().get("c")  # current price
        return float(price) if price and float(price) > 0 else None
    except Exception as e:
        print(f"[finnhub] error for {ticker}: {e}")
    return None


# ---------------------------------------------------------------------------
# Public Service
# ---------------------------------------------------------------------------

class MarketDataService:
    """Multi-source market data service with automatic fallback chain."""

    # --- Current price (with cache) ----------------------------------------

    @staticmethod
    def get_current_price(ticker: str) -> Optional[float]:
        ticker = ticker.upper()
        cached = _cached_price(ticker)
        if cached is not None:
            return cached

        sources = [
            ("yfinance",      _price_yfinance),
            ("yahoo_v8",      _price_yahoo_v8),
            ("stooq",         _price_stooq),
            ("alpha_vantage", _price_alpha_vantage),
            ("finnhub",       _price_finnhub),
        ]

        for name, fn in sources:
            price = fn(ticker)
            if price is not None and price > 0:
                print(f"[market] {ticker} price={price:.2f} via {name}")
                _set_cache(ticker, price)
                return price

        print(f"[market] {ticker} — all price sources failed")
        return None

    # --- Full stock info ----------------------------------------------------

    @staticmethod
    def get_stock_info(ticker: str) -> Optional[Dict]:
        ticker = ticker.upper()

        if not VALID_TICKER_PATTERN.match(ticker):
            return None

        for name, fn in [("yfinance", _info_yfinance), ("yahoo_v7", _info_yahoo_v7)]:
            info = fn(ticker)
            if info is not None:
                print(f"[market] {ticker} info via {name}")
                if not info.get("current_price"):
                    price = MarketDataService.get_current_price(ticker)
                    if price:
                        info["current_price"] = price
                return info

        # All info sources failed — still try to get a price
        price = MarketDataService.get_current_price(ticker)
        result = _empty_info(ticker)
        if price:
            result["current_price"] = price
        print(f"[market] {ticker} — info unavailable, using empty fallback")
        return result

    # --- Multiple prices at once -------------------------------------------

    @staticmethod
    def get_multiple_prices(tickers: List[str]) -> Dict[str, Optional[float]]:
        prices: Dict[str, Optional[float]] = {}

        # Batch yfinance first (most efficient)
        try:
            tickers_str = " ".join(tickers)
            data = yf.download(tickers_str, period="1d", group_by="ticker", progress=False, auto_adjust=True)
            for ticker in tickers:
                try:
                    val = float(data["Close"].iloc[-1]) if len(tickers) == 1 else float(data[ticker]["Close"].iloc[-1])
                    if val > 0:
                        prices[ticker] = val
                        _set_cache(ticker, val)
                except Exception:
                    pass
        except Exception as e:
            print(f"[market] batch yfinance error: {e}")

        # Fall back individually for any missing
        for ticker in [t for t in tickers if t not in prices]:
            prices[ticker] = MarketDataService.get_current_price(ticker)

        return prices

    # --- Historical data ----------------------------------------------------

    @staticmethod
    def get_historical_data(ticker: str, period: str = "1mo") -> Optional[pd.DataFrame]:
        # Source 1: yfinance
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if not hist.empty:
                return hist
        except Exception as e:
            print(f"[yfinance] historical error for {ticker}: {e}")

        # Source 2: Yahoo v8 chart
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=1d&range={period}"
            )
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code == 200:
                chart = resp.json()["chart"]["result"][0]
                ohlcv = chart["indicators"]["quote"][0]
                df = pd.DataFrame({
                    "Open":   ohlcv.get("open", []),
                    "High":   ohlcv.get("high", []),
                    "Low":    ohlcv.get("low", []),
                    "Close":  ohlcv.get("close", []),
                    "Volume": ohlcv.get("volume", []),
                }, index=pd.to_datetime(chart["timestamp"], unit="s", utc=True))
                if not df.empty:
                    return df
        except Exception as e:
            print(f"[yahoo_v8] historical error for {ticker}: {e}")

        return None

    # --- Options chain (yfinance only) -------------------------------------

    @staticmethod
    def get_options_chain(ticker: str, expiration_date: str = None) -> Optional[Dict]:
        try:
            stock = yf.Ticker(ticker)
            if not expiration_date:
                expirations = stock.options
                if not expirations:
                    return None
                expiration_date = expirations[0]
            opt = stock.option_chain(expiration_date)
            return {
                "ticker": ticker,
                "expiration_date": expiration_date,
                "calls": opt.calls.to_dict("records"),
                "puts": opt.puts.to_dict("records"),
            }
        except Exception as e:
            print(f"[yfinance] options chain error for {ticker}: {e}")
        return None

    @staticmethod
    def get_available_expirations(ticker: str) -> List[str]:
        try:
            return list(yf.Ticker(ticker).options)
        except Exception as e:
            print(f"[yfinance] expirations error for {ticker}: {e}")
        return []
