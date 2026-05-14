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

# News cache: { ticker: ([items], timestamp) }
_news_cache: Dict[str, tuple] = {}
NEWS_CACHE_TTL = 900  # 15 min

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
# News helpers
# ---------------------------------------------------------------------------

def _parse_yf_news(item: Dict, ticker: str) -> Optional[Dict]:
    """Normalize a yfinance news item; handles old and new API formats."""
    try:
        if "content" in item:
            content = item.get("content") or {}
            thumb = None
            if content.get("thumbnail"):
                resolutions = (content["thumbnail"] or {}).get("resolutions") or []
                if resolutions:
                    thumb = resolutions[0].get("url")
            return {
                "id": item.get("id", ""),
                "title": content.get("title", ""),
                "summary": content.get("summary", ""),
                "publisher": (content.get("provider") or {}).get("displayName", ""),
                "link": (content.get("canonicalUrl") or {}).get("url", ""),
                "published_at": content.get("pubDate", ""),
                "thumbnail": thumb,
                "ticker": ticker,
            }
        else:
            pub_ts = item.get("providerPublishTime")
            published_at = ""
            if pub_ts:
                try:
                    published_at = datetime.fromtimestamp(int(pub_ts)).isoformat()
                except Exception:
                    pass
            thumb = None
            if item.get("thumbnail"):
                resolutions = (item["thumbnail"] or {}).get("resolutions") or []
                if resolutions:
                    thumb = resolutions[0].get("url")
            return {
                "id": item.get("uuid", ""),
                "title": item.get("title", ""),
                "summary": "",
                "publisher": item.get("publisher", ""),
                "link": item.get("link", ""),
                "published_at": published_at,
                "thumbnail": thumb,
                "ticker": ticker,
            }
    except Exception:
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

    # --- News (with cache) -------------------------------------------------

    @staticmethod
    def get_ticker_news(ticker: str, limit: int = 10) -> List[Dict]:
        ticker = ticker.upper()
        entry = _news_cache.get(ticker)
        if entry:
            items, ts = entry
            if time.time() - ts < NEWS_CACHE_TTL:
                return items[:limit]
        try:
            raw = yf.Ticker(ticker).news or []
            result = []
            for item in raw:
                parsed = _parse_yf_news(item, ticker)
                if parsed:
                    result.append(parsed)
            _news_cache[ticker] = (result, time.time())
            return result[:limit]
        except Exception as e:
            print(f"[yfinance] news error for {ticker}: {e}")
        return []

    @staticmethod
    def get_chile_market_news(limit: int = 25) -> List[Dict]:
        """Fetch Chilean market news from Google News RSS."""
        cache_key = "__chile__"
        entry = _news_cache.get(cache_key)
        if entry:
            items, ts = entry
            if time.time() - ts < NEWS_CACHE_TTL:
                return items[:limit]
        try:
            import xml.etree.ElementTree as ET
            url = (
                "https://news.google.com/rss/search"
                "?q=bolsa+chile+mercado+acciones+economia"
                "&hl=es-419&gl=CL&ceid=CL:es-419"
            )
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is None:
                return []
            items_xml = channel.findall("item")
            result = []
            for item in items_xml:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                source_el = item.find("source")
                publisher = source_el.text if source_el is not None else "Google News"
                result.append({
                    "id": link,
                    "title": title,
                    "summary": "",
                    "publisher": publisher,
                    "link": link,
                    "published_at": pub_date,
                    "thumbnail": None,
                    "ticker": "CL",
                })
            _news_cache[cache_key] = (result, time.time())
            return result[:limit]
        except Exception as e:
            print(f"[chile_news] error: {e}")
        return []

    # --- Dividend info -----------------------------------------------------

    @staticmethod
    def get_dividend_info(ticker: str) -> Optional[Dict]:
        ticker = ticker.upper()
        try:
            t = yf.Ticker(ticker)
            info = t.info

            # ex-dividend date (unix timestamp in yfinance info)
            ex_ts = info.get("exDividendDate")
            ex_date = None
            if ex_ts:
                try:
                    ex_date = datetime.fromtimestamp(int(ex_ts)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Historical dividends — last 8 payments
            recent_dividends: List[Dict] = []
            try:
                hist = t.dividends
                if not hist.empty:
                    for dt, amt in hist.tail(8).items():
                        recent_dividends.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "amount": round(float(amt), 4),
                        })
                    recent_dividends.reverse()
            except Exception:
                pass

            return {
                "ticker": ticker,
                "company_name": info.get("longName") or info.get("shortName") or ticker,
                "dividend_yield": info.get("dividendYield"),
                "dividend_rate": info.get("dividendRate"),
                "ex_dividend_date": ex_date,
                "payout_ratio": info.get("payoutRatio"),
                "five_year_avg_yield": info.get("fiveYearAvgDividendYield"),
                "trailing_annual_dividend_yield": info.get("trailingAnnualDividendYield"),
                "trailing_annual_dividend_rate": info.get("trailingAnnualDividendRate"),
                "recent_dividends": recent_dividends,
                "pays_dividend": bool(
                    info.get("dividendRate") or info.get("trailingAnnualDividendRate")
                ),
            }
        except Exception as e:
            print(f"[yfinance] dividend info error for {ticker}: {e}")
        return None
