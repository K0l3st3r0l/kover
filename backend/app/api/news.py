import os
import json
import time
import requests
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.stock import Stock
from ..models.user import User
from ..utils.auth import get_current_user
from ..market import MarketDataService
from ..market.macro_data import MacroDataService

router = APIRouter()

MARKET_TICKERS = ["SPY", "QQQ", "^VIX", "GLD", "^GSPC"]

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# { cache_key: (result_dict, timestamp) }
_analysis_cache: dict = {}
ANALYSIS_CACHE_TTL = 3600  # 1 hour — market context doesn't change that fast


def _dedupe_sorted(news_list):
    seen = set()
    result = []
    for item in news_list:
        key = item.get("id") or item.get("link") or item.get("title")
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    result.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return result


@router.get("/portfolio")
def get_portfolio_news(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stocks = (
        db.query(Stock)
        .filter(Stock.user_id == current_user.id, Stock.is_active == True)
        .all()
    )
    tickers = list({s.ticker for s in stocks})
    all_news = []
    for ticker in tickers:
        all_news.extend(MarketDataService.get_ticker_news(ticker, limit=8))
    return {"news": _dedupe_sorted(all_news)[:40], "tickers": tickers}


@router.get("/market")
def get_market_news():
    all_news = []
    for ticker in MARKET_TICKERS:
        all_news.extend(MarketDataService.get_ticker_news(ticker, limit=6))
    return {"news": _dedupe_sorted(all_news)[:25]}


@router.get("/chile")
def get_chile_news():
    return {"news": MarketDataService.get_chile_market_news()}


@router.get("/ticker/{ticker}")
def get_single_ticker_news(
    ticker: str,
    current_user: User = Depends(get_current_user),
):
    news = MarketDataService.get_ticker_news(ticker.upper(), limit=20)
    return {"news": news, "ticker": ticker.upper()}


@router.get("/macro")
def get_macro_indicators():
    """
    Indicadores macro actuales para alimentar la IA y mostrar en /noticias.
    Combina Chile (mindicador.cl) + internacionales (DXY, yields, VIX, commodities).
    """
    try:
        data = MacroDataService.get_indicators()
        return data
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error cargando macro: {e}")


@router.get("/macro-calendar")
def get_macro_calendar(
    days: int = Query(default=14, ge=1, le=60),
    days_back: int = Query(default=0, ge=0, le=180),
):
    """Calendario económico curado: próximos `days` días, más opcionalmente
    `days_back` días de histórico con el resultado real publicado."""
    try:
        return MacroDataService.get_calendar(days_ahead=days, days_back=days_back)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error cargando calendario: {e}")


@router.get("/analysis")
def get_news_analysis(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze today's news with DeepSeek AI, focused on the user's portfolio and strategy."""
    if not DEEPSEEK_KEY:
        raise HTTPException(status_code=503, detail="DeepSeek API key no configurado")

    # Get portfolio tickers
    stocks = (
        db.query(Stock)
        .filter(Stock.user_id == current_user.id, Stock.is_active == True)
        .all()
    )
    tickers = sorted({s.ticker for s in stocks})
    tickers_str = ", ".join(tickers) if tickers else "sin posiciones activas"

    # Cache key: date + tickers (analysis is per-day per-portfolio)
    cache_key = f"{date.today()}:{tickers_str}"
    cached = _analysis_cache.get(cache_key)
    if cached:
        result, ts = cached
        if time.time() - ts < ANALYSIS_CACHE_TTL:
            return {**result, "cached": True, "cached_at": result.get("generated_at")}

    # Collect news: portfolio tickers + market indices
    all_news: list = []
    for ticker in tickers[:8]:
        all_news.extend(MarketDataService.get_ticker_news(ticker, limit=5))
    for ticker in MARKET_TICKERS[:3]:
        all_news.extend(MarketDataService.get_ticker_news(ticker, limit=5))

    # Deduplicate, keep top 25 most recent with a title
    seen: set = set()
    news_for_ai: list = []
    for item in sorted(all_news, key=lambda x: x.get("published_at", ""), reverse=True):
        key = item.get("id") or item.get("title")
        if key and key not in seen and item.get("title"):
            seen.add(key)
            news_for_ai.append(item)
        if len(news_for_ai) >= 25:
            break

    if not news_for_ai:
        raise HTTPException(status_code=404, detail="No hay noticias disponibles para analizar")

    news_lines = "\n".join(
        f"- [{item['ticker']}] {item['title']}"
        + (f" — {item['publisher']}" if item.get("publisher") else "")
        for item in news_for_ai
    )

    # Macro context (international indicators + economic calendar).
    # Best-effort: if the macro service fails, we still proceed with news only.
    macro_block = ""
    try:
        macro_block = MacroDataService.build_ai_context()
    except Exception as e:
        print(f"[news.analysis] macro context unavailable: {e}")

    macro_section = (
        f"\n{macro_block}\n"
        if macro_block
        else "\n(Indicadores macro internacionales no disponibles en este momento.)\n"
    )

    today_str = date.today().strftime("%d/%m/%Y")
    prompt = f"""Eres un analista financiero experto en opciones sobre acciones y dividendos, orientado a inversores particulares con estrategia de ingresos pasivos.

**Fecha de hoy:** {today_str}
**Portfolio del usuario:** {tickers_str}

**Estrategia del usuario:**
- Compra y mantiene acciones de dividendo (ej. Ford)
- Vende covered calls mensualmente para capturar primas
- Cobra dividendos trimestrales/semestrales
- Objetivo: maximizar rendimiento total = dividendos + primas + apreciación

**Noticias del día:**
{news_lines}
{macro_section}

Analiza estas noticias y responde ÚNICAMENTE con JSON válido (sin texto extra, sin markdown, sin ```), con esta estructura exacta:

{{
  "market_summary": "2-3 oraciones sobre el clima general del mercado hoy",
  "market_sentiment": "bullish|neutral|bearish",
  "portfolio_impact": [
    {{"ticker": "TICKER", "sentiment": "positive|neutral|negative", "text": "análisis conciso de la noticia y su impacto"}}
  ],
  "covered_calls": {{
    "text": "análisis sobre si conviene vender primas ahora, volatilidad implícita, riesgo de asignación",
    "recommendation": "sell|wait|caution"
  }},
  "dividends": "impacto en dividendos de las posiciones actuales, o 'Sin novedades relevantes' si no hay",
  "outlook": {{
    "text": "perspectiva breve y accionable para los próximos 2-5 días",
    "direction": "up|flat|down"
  }}
}}

Incluye en portfolio_impact solo los tickers del portfolio que tengan noticias relevantes. Sé conciso y práctico."""

    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 1200,
            },
            timeout=45,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if model wraps the JSON anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            analysis_data = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="La IA devolvió una respuesta inesperada. Intentá de nuevo.")

        result = {
            **analysis_data,
            "tickers": tickers,
            "news_count": len(news_for_ai),
            "generated_at": date.today().isoformat(),
            "cached": False,
        }
        _analysis_cache[cache_key] = (result, time.time())
        return result

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="DeepSeek tardó demasiado. Intentá de nuevo.")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Error DeepSeek: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al consultar DeepSeek: {str(e)}")
