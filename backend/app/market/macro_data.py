"""
MacroDataService — Indicadores económicos actuales y calendario de eventos.

Fuentes:
  - mindicador.cl (Banco Central de Chile / INE) — sin auth, JSON público
  - yfinance (DXY, oro, petróleo, 10y, VIX) — sin auth

Calendario:
  - Curado de eventos macro recurrentes high-impact (FOMC, NFP, CPI, IPC CL, etc.)
  - Calcula la próxima fecha de ocurrencia según reglas conocidas.
  - Marca cuáles salen "hoy", "mañana" o "esta semana".
"""

import json
import os
import time
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Config & cache
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

MINDICADOR_BASE = "https://mindicador.cl/api"

# FRED (St. Louis Fed) — fuente principal del "resultado real" de eventos US.
# Gratis, rate limit generoso (120 req/min) y publica el mismo día que la
# fuente oficial (BLS, BEA, Fed). Requiere FRED_API_KEY.
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Alpha Vantage — respaldo si no hay FRED_API_KEY o la serie FRED falla.
# Free: 25 req/día. Sin ninguna de las dos keys, esos campos quedan vacíos
# y el calendario sigue funcionando igual que antes.
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
AV_CACHE_TTL = 24 * 3600  # 24h — estos indicadores se publican como máximo 1 vez/mes

# event_id -> (series_id FRED, formato de valor)
# DFEDTARU = límite superior del rango objetivo Fed Funds — se actualiza el
# mismo día de la decisión FOMC, no con rezago mensual como FEDERAL_FUNDS_RATE.
_FRED_EVENT_SERIES = {
    "fomc":       ("DFEDTARU", "percent"),
    "cpi_us":     ("CPIAUCSL", "index"),
    "nfp":        ("PAYEMS", "index"),
    "pce_us":     ("PCEPI", "index"),
    "ppi_us":     ("PPIACO", "index"),
    "retail_us":  ("RSAFS", "index"),
    "gdp_us":     ("GDPC1", "index"),
}

# event_id -> (función Alpha Vantage, formato de valor) — respaldo de lo de arriba
_AV_EVENT_FUNCTIONS = {
    "fomc":       ("FEDERAL_FUNDS_RATE", "percent"),
    "cpi_us":     ("CPI", "index"),
    "nfp":        ("NONFARM_PAYROLL", "index"),
    "retail_us":  ("RETAIL_SALES", "index"),
    "gdp_us":     ("REAL_GDP", "index"),
}

# event_id (CL) -> key del indicador ya cubierto por mindicador.cl
_CL_EVENT_INDICATOR = {
    "ipc_cl":     "ipc",
    "tpm_cl":     "tpm",
    "imacec_cl":  "imacec",
}

# Indicadores CL desde mindicador
# freq: "daily" -> cambio vs día anterior
#       "monthly" -> cambio vs el valor del mes anterior (ya viene en %)
#       "level" -> cambio vs medición anterior (mes anterior para TPM, etc.)
CL_INDICATORS = [
    {"key": "uf",          "name": "UF",                  "country": "CL", "format": "currency", "freq": "daily"},
    {"key": "utm",         "name": "UTM",                 "country": "CL", "format": "currency", "freq": "monthly"},
    {"key": "ivp",         "name": "IVP",                 "country": "CL", "format": "currency", "freq": "daily"},
    {"key": "ipc",         "name": "IPC (var. % m/m)",    "country": "CL", "format": "percent",  "freq": "monthly"},
    {"key": "tpm",         "name": "TPM",                 "country": "CL", "format": "percent",  "freq": "level"},
    {"key": "imacec",      "name": "Imacec (var. %)",     "country": "CL", "format": "percent",  "freq": "monthly"},
    {"key": "dolar",       "name": "USD/CLP",             "country": "CL", "format": "currency", "freq": "daily"},
    {"key": "euro",        "name": "EUR/CLP",             "country": "CL", "format": "currency", "freq": "daily"},
    {"key": "libra_cobre", "name": "Cobre (USD/lb)",      "country": "CL", "format": "commodity","freq": "daily"},
]

# Indicadores US vía yfinance (ticker, nombre, formato)
US_TICKERS = [
    {"ticker": "DX-Y.NYB", "name": "DXY (USD Index)",  "country": "US", "format": "index"},
    {"ticker": "GC=F",     "name": "Oro (futuro)",     "country": "US", "format": "commodity"},
    {"ticker": "CL=F",     "name": "Petróleo WTI",     "country": "US", "format": "commodity"},
    {"ticker": "^TNX",     "name": "US 10Y Yield (%)", "country": "US", "format": "percent"},
    {"ticker": "^VIX",     "name": "VIX",              "country": "US", "format": "index"},
]

# Respaldo de los indicadores de mercado vía yfinance (ya es dependencia) cuando
# mindicador.cl falla. Solo aplica a los de precio de mercado — TPM/IPC/Imacec no
# tienen equivalente en yfinance y se cubren con el last-known-good en disco.
CL_YF_FALLBACK = {
    "dolar":       "CLP=X",
    "euro":        "EURCLP=X",
    "libra_cobre": "HG=F",
}

# Cache: memoria (TTL corto) + disco (last-known-good, sobrevive reinicios y
# caídas de la fuente).
_macro_cache: Dict[str, tuple] = {}
MACRO_CACHE_TTL = 1800  # 30 min — los indicadores no cambian cada segundo
MACRO_DISK_DIR = Path(os.getenv("MACRO_CACHE_DIR", "/app/cache/macro"))


def _disk_path(key: str) -> Path:
    return MACRO_DISK_DIR / f"{key}.json"


def _save_disk(key: str, data) -> None:
    try:
        MACRO_DISK_DIR.mkdir(parents=True, exist_ok=True)
        _disk_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[macro] disk save {key}: {e}")


def _load_disk(key: str):
    try:
        p = _disk_path(key)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[macro] disk load {key}: {e}")
    return None


def _cached(key: str, ttl: int = MACRO_CACHE_TTL):
    entry = _macro_cache.get(key)
    if entry:
        data, ts = entry
        if time.time() - ts < ttl:
            return data
    return None


def _set_cache(key: str, data):
    _macro_cache[key] = (data, time.time())
    _save_disk(key, data)


def _merge_last_good(fresh: List[Dict], prev: List[Dict]) -> List[Dict]:
    """Completa los indicadores que faltan en `fresh` (fuente caída) con el
    último valor bueno de `prev`, marcándolos como `stale`."""
    by_key = {r["key"]: r for r in fresh if r.get("value") is not None}
    for old in prev:
        k = old.get("key")
        if k and k not in by_key:
            by_key[k] = {**old, "stale": True}
    ordered, seen = [], set()
    for ref in prev + fresh:
        k = ref.get("key")
        if k in by_key and k not in seen:
            ordered.append(by_key[k])
            seen.add(k)
    return ordered


# ---------------------------------------------------------------------------
# Indicadores Chile — mindicador.cl
# ---------------------------------------------------------------------------

def _fetch_cl_indicators() -> List[Dict]:
    """Trae el último valor de cada indicador CL desde mindicador.cl."""
    results: List[Dict] = []
    for ind in CL_INDICATORS:
        try:
            resp = requests.get(
                f"{MINDICADOR_BASE}/{ind['key']}",
                headers=_HEADERS,
                timeout=6,
            )
            resp.raise_for_status()
            data = resp.json()
            serie = data.get("serie") or []
            if not serie:
                continue
            latest = serie[0]
            prev = serie[1] if len(serie) > 1 else None
            valor = latest.get("valor")
            fecha = (latest.get("fecha") or "")[:10]

            freq = ind.get("freq", "daily")
            # Para series mensuales (IPC, Imacec, UTM) y de nivel (TPM),
            # el cambio día-a-día no es significativo: solo lo calculamos
            # para series diarias, y omitimos para las demás.
            if freq == "daily":
                valor_anterior = prev.get("valor") if prev else None
                cambio_pct = None
                if valor is not None and valor_anterior and valor_anterior != 0:
                    cambio_pct = round((valor - valor_anterior) / valor_anterior * 100, 2)
            else:
                valor_anterior = None
                cambio_pct = None

            results.append({
                "key": ind["key"],
                "name": ind["name"],
                "country": ind["country"],
                "format": ind["format"],
                "value": valor,
                "previous": valor_anterior,
                "change_pct": cambio_pct,
                "as_of": fecha,
            })
        except Exception as e:
            print(f"[macro] mindicador {ind['key']} error: {e}")

    # Respaldo: para los indicadores de mercado que mindicador no entregó, tirar
    # de yfinance (USD/CLP, EUR/CLP, cobre). Misma unidad que mindicador.
    got = {r["key"] for r in results if r.get("value") is not None}
    for ind in CL_INDICATORS:
        key = ind["key"]
        if key in got or key not in CL_YF_FALLBACK:
            continue
        yf_data = _yf_latest(CL_YF_FALLBACK[key])
        if not yf_data:
            continue
        latest, prev, as_of = yf_data
        cambio_pct = None
        if prev and prev != 0:
            cambio_pct = round((latest - prev) / prev * 100, 2)
        results.append({
            "key": key,
            "name": ind["name"],
            "country": ind["country"],
            "format": ind["format"],
            "value": round(latest, 4),
            "previous": round(prev, 4) if prev is not None else None,
            "change_pct": cambio_pct,
            "as_of": as_of,
            "source": "yfinance (respaldo)",
        })
    return results


def _yf_latest(ticker: str):
    """Último cierre y cierre previo de un ticker yfinance. None si falla."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            return None
        latest = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
        return latest, prev, hist.index[-1].strftime("%Y-%m-%d")
    except Exception as e:
        print(f"[macro] yfinance fallback {ticker} error: {e}")
        return None


# ---------------------------------------------------------------------------
# Indicadores US — yfinance
# ---------------------------------------------------------------------------

def _fetch_us_indicators() -> List[Dict]:
    """Trae el último valor de los tickers US macro vía yfinance."""
    import yfinance as yf

    results: List[Dict] = []
    for ind in US_TICKERS:
        try:
            t = yf.Ticker(ind["ticker"])
            hist = t.history(period="5d")
            if hist.empty:
                continue
            latest = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else None
            as_of = hist.index[-1].strftime("%Y-%m-%d")
            cambio_pct = None
            if prev and float(prev) != 0:
                cambio_pct = round((float(latest) - float(prev)) / float(prev) * 100, 2)
            results.append({
                "key": ind["ticker"],
                "name": ind["name"],
                "country": ind["country"],
                "format": ind["format"],
                "value": round(float(latest), 4),
                "previous": round(float(prev), 4) if prev is not None else None,
                "change_pct": cambio_pct,
                "as_of": as_of,
            })
        except Exception as e:
            print(f"[macro] yfinance {ind['ticker']} error: {e}")
    return results


# ---------------------------------------------------------------------------
# Resultados reales de eventos US — FRED (principal) + Alpha Vantage (respaldo)
# ---------------------------------------------------------------------------

def _fetch_fred_series(series_id: str) -> Optional[List[Dict]]:
    """Últimas observaciones de una serie FRED (más reciente primero). None
    si falla o no hay key configurada."""
    if not FRED_API_KEY:
        return None
    try:
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 6,
            },
            headers=_HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        obs = resp.json().get("observations") or []
        # FRED marca observaciones faltantes con "."
        clean = [o for o in obs if o.get("value") not in (None, ".", "")]
        return clean or None
    except Exception as e:
        print(f"[macro] fred {series_id} error: {e}")
        return None


def _fetch_av_series(function: str) -> Optional[List[Dict]]:
    """Serie histórica de un indicador económico Alpha Vantage. None si falla
    o no hay key configurada."""
    if not ALPHA_VANTAGE_KEY:
        return None
    try:
        url = f"https://www.alphavantage.co/query?function={function}&apikey={ALPHA_VANTAGE_KEY}"
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        data = resp.json().get("data")
        return data or None
    except Exception as e:
        print(f"[macro] alpha_vantage {function} error: {e}")
        return None


def _fetch_us_event_actuals() -> Dict[str, Dict]:
    """Último resultado publicado por evento US. Intenta FRED primero (mismo
    día que la fuente oficial); si no hay key o la serie falla, cae a Alpha
    Vantage. TTL largo (24h) porque estos indicadores se publican como
    máximo 1 vez al mes."""
    cached = _cached("us_actuals", AV_CACHE_TTL)
    if cached is not None:
        return cached

    result: Dict[str, Dict] = {}
    event_ids = set(_FRED_EVENT_SERIES) | set(_AV_EVENT_FUNCTIONS)

    for event_id in event_ids:
        fred_spec = _FRED_EVENT_SERIES.get(event_id)
        if fred_spec:
            series_id, fmt = fred_spec
            obs = _fetch_fred_series(series_id)
            if obs:
                try:
                    latest = obs[0]
                    prev = obs[1] if len(obs) > 1 else None
                    value = float(latest["value"])
                    value_prev = float(prev["value"]) if prev else None
                    change_pct = None
                    if value_prev and value_prev != 0:
                        change_pct = round((value - value_prev) / value_prev * 100, 2)
                    result[event_id] = {
                        "value": value,
                        "previous": value_prev,
                        "change_pct": change_pct,
                        "as_of": latest.get("date"),
                        "format": fmt,
                        "source": "fred",
                    }
                    continue
                except (KeyError, ValueError, TypeError):
                    pass

        av_spec = _AV_EVENT_FUNCTIONS.get(event_id)
        if av_spec:
            func, fmt = av_spec
            series = _fetch_av_series(func)
            if series:
                try:
                    latest = series[0]
                    prev = series[1] if len(series) > 1 else None
                    value = float(latest["value"])
                    value_prev = float(prev["value"]) if prev else None
                    change_pct = None
                    if value_prev and value_prev != 0:
                        change_pct = round((value - value_prev) / value_prev * 100, 2)
                    result[event_id] = {
                        "value": value,
                        "previous": value_prev,
                        "change_pct": change_pct,
                        "as_of": latest.get("date"),
                        "format": fmt,
                        "source": "alpha_vantage",
                    }
                except (KeyError, ValueError, TypeError):
                    continue

    # Respaldo: completar con el último dato bueno en disco si ambas fuentes
    # fallaron o no hay key (no sobreescribe lo que sí se obtuvo fresco).
    last_good = _load_disk("us_actuals") or {}
    for k, v in last_good.items():
        if k not in result:
            result[k] = {**v, "stale": True}

    _set_cache("us_actuals", result)
    return result


# ---------------------------------------------------------------------------
# Calendario económico curado
# ---------------------------------------------------------------------------
# Reglas: cada evento se repite según un patrón conocido. Calculamos la próxima
# fecha a partir de hoy y marcamos si es hoy / mañana / esta semana.

# (id, nombre, país, importancia 1-3, día_semana regla, día_mes regla, hora_approx CL)
# day_of_week: 0=lun, 4=vie  |  day_of_month: si None, se calcula
# week_of_month: None | "first" | "second" | "third" | "last"

_RECURRING_EVENTS = [
    {
        "id": "fomc",
        "name": "Decisión de Tasas FOMC",
        "country": "US",
        "impact": 3,
        "category": "tasas",
        "week_of_month": "third",
        "day_of_week": 2,  # miércoles
        "hour_cl": "15:00",
    },
    {
        "id": "fomc_minutes",
        "name": "Minutas FOMC",
        "country": "US",
        "impact": 2,
        "category": "tasas",
        "week_of_month": "third",
        "day_of_week": 3,  # jueves siguiente al FOMC
        "hour_cl": "15:00",
    },
    {
        "id": "nfp",
        "name": "Non-Farm Payrolls (NFP)",
        "country": "US",
        "impact": 3,
        "category": "empleo",
        "week_of_month": "first",
        "day_of_week": 4,  # primer viernes
        "hour_cl": "09:30",
    },
    {
        "id": "cpi_us",
        "name": "CPI EE.UU. (inflación)",
        "country": "US",
        "impact": 3,
        "category": "inflacion",
        "week_of_month": "second",
        "day_of_week": 2,  # segundo o tercer martes
        "hour_cl": "09:30",
    },
    {
        "id": "pce_us",
        "name": "PCE Deflator (Fed preferido)",
        "country": "US",
        "impact": 3,
        "category": "inflacion",
        "week_of_month": "last",
        "day_of_week": 4,  # último viernes
        "hour_cl": "09:30",
    },
    {
        "id": "ppi_us",
        "name": "PPI EE.UU.",
        "country": "US",
        "impact": 2,
        "category": "inflacion",
        "week_of_month": "second",
        "day_of_week": 2,  # martes siguiente al CPI
        "hour_cl": "09:30",
    },
    {
        "id": "retail_us",
        "name": "Ventas Minoristas EE.UU.",
        "country": "US",
        "impact": 2,
        "category": "consumo",
        "week_of_month": "second",
        "day_of_week": 3,
        "hour_cl": "09:30",
    },
    {
        "id": "gdp_us",
        "name": "PIB EE.UU. (estimación)",
        "country": "US",
        "impact": 2,
        "category": "crecimiento",
        "week_of_month": "last",
        "day_of_week": 3,  # jueves
        "hour_cl": "09:30",
    },
    {
        "id": "ipc_cl",
        "name": "IPC Chile (inflación)",
        "country": "CL",
        "impact": 3,
        "category": "inflacion",
        "day_of_month": 8,  # aprox día 8 de cada mes
        "hour_cl": "09:00",
    },
    {
        "id": "tpm_cl",
        "name": "TPM — Reunión BCCh",
        "country": "CL",
        "impact": 3,
        "category": "tasas",
        "day_of_month": 26,  # aprox fin de mes
        "hour_cl": "18:00",
    },
    {
        "id": "imacec_cl",
        "name": "Imacec Chile",
        "country": "CL",
        "impact": 2,
        "category": "crecimiento",
        "day_of_month": 6,
        "hour_cl": "09:00",
    },
]


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Devuelve la fecha del n-ésimo weekday del mes (n=1..4 o -1=último)."""
    if n == -1:  # último
        if month == 12:
            last_day = (date(year + 1, 1, 1) - timedelta(days=1)).day
        else:
            last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
        d = date(year, month, last_day)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _next_occurrence(ev: Dict, today: date) -> date:
    """Calcula la próxima fecha del evento a partir de hoy."""
    year, month = today.year, today.month
    candidates: List[date] = []

    if "day_of_month" in ev and ev["day_of_month"] is not None:
        # Regla fija por día del mes
        for ym in [(year, month), (year + (1 if month == 12 else 0), 1 if month == 12 else month + 1)]:
            try:
                d = date(ym[0], ym[1], ev["day_of_month"])
                if d >= today:
                    candidates.append(d)
            except ValueError:
                pass
    else:
        # Regla por nth-weekday
        n_map = {"first": 1, "second": 2, "third": 3, "last": -1}
        n = n_map.get(ev.get("week_of_month", "first"), 1)
        for ym in [(year, month), (year + (1 if month == 12 else 0), 1 if month == 12 else month + 1)]:
            try:
                d = _nth_weekday(ym[0], ym[1], ev["day_of_week"], n)
                if d >= today:
                    candidates.append(d)
            except ValueError:
                pass

    return min(candidates) if candidates else today


def _prev_occurrence(ev: Dict, today: date) -> Optional[date]:
    """Calcula la ocurrencia anterior más reciente (estrictamente antes de hoy),
    para mostrar el resultado de eventos que ya pasaron."""
    year, month = today.year, today.month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    candidates: List[date] = []

    if "day_of_month" in ev and ev["day_of_month"] is not None:
        for ym in [(prev_year, prev_month), (year, month)]:
            try:
                d = date(ym[0], ym[1], ev["day_of_month"])
                if d < today:
                    candidates.append(d)
            except ValueError:
                pass
    else:
        n_map = {"first": 1, "second": 2, "third": 3, "last": -1}
        n = n_map.get(ev.get("week_of_month", "first"), 1)
        for ym in [(prev_year, prev_month), (year, month)]:
            try:
                d = _nth_weekday(ym[0], ym[1], ev["day_of_week"], n)
                if d < today:
                    candidates.append(d)
            except ValueError:
                pass

    return max(candidates) if candidates else None


def _tag_when(d: date, today: date) -> str:
    delta = (d - today).days
    if delta < 0:
        return f"hace {-delta}d"
    if delta == 0:
        return "hoy"
    if delta == 1:
        return "mañana"
    return f"en {delta}d"


# ---------------------------------------------------------------------------
# Public Service
# ---------------------------------------------------------------------------

class MacroDataService:

    @staticmethod
    def get_indicators() -> Dict:
        """Retorna todos los indicadores macro (CL + US) cacheados."""
        cached = _cached("indicators")
        if cached is not None:
            return cached
        cl = _fetch_cl_indicators()
        us = _fetch_us_indicators()

        # Si alguna fuente falló y faltan indicadores, completar con el último
        # valor bueno persistido en disco (marcado como stale).
        last_good = _load_disk("indicators") or {}
        cl = _merge_last_good(cl, last_good.get("cl", []))
        us = _merge_last_good(us, last_good.get("us", []))

        data = {
            "cl": cl,
            "us": us,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        _set_cache("indicators", data)
        return data

    @staticmethod
    def get_calendar(days_ahead: int = 14, days_back: int = 0) -> Dict:
        """Retorna eventos macro de los próximos `days_ahead` días. Si
        `days_back` > 0, también incluye la ocurrencia anterior de cada
        evento (hasta esa cantidad de días atrás) con su resultado real,
        cuando hay fuente disponible (mindicador.cl para CL, Alpha Vantage
        para US)."""
        cache_key = f"calendar_{days_ahead}_{days_back}"
        cached = _cached(cache_key)
        if cached is not None:
            return cached

        today = date.today()
        end = today + timedelta(days=days_ahead)
        us_actuals = MacroDataService._fetch_us_event_actuals_safe()
        cl_indicators = {i["key"]: i for i in MacroDataService.get_indicators().get("cl", [])}

        def build_event(ev: Dict, d: date) -> Dict:
            event = {
                "id": ev["id"],
                "name": ev["name"],
                "country": ev["country"],
                "impact": ev["impact"],
                "category": ev["category"],
                "date": d.isoformat(),
                "hour_cl": ev.get("hour_cl", ""),
                "when": _tag_when(d, today),
            }
            cl_key = _CL_EVENT_INDICATOR.get(ev["id"])
            if cl_key and cl_key in cl_indicators:
                ind = cl_indicators[cl_key]
                event.update({
                    "actual": ind.get("value"),
                    "actual_previous": ind.get("previous"),
                    "actual_change_pct": ind.get("change_pct"),
                    "actual_date": ind.get("as_of"),
                    "actual_format": ind.get("format"),
                    "actual_source": "mindicador.cl",
                })
            elif ev["id"] in us_actuals:
                a = us_actuals[ev["id"]]
                event.update({
                    "actual": a.get("value"),
                    "actual_previous": a.get("previous"),
                    "actual_change_pct": a.get("change_pct"),
                    "actual_date": a.get("as_of"),
                    "actual_format": a.get("format"),
                    "actual_source": a.get("source", "alpha_vantage") + (" (caché)" if a.get("stale") else ""),
                })
            return event

        events: List[Dict] = []
        for ev in _RECURRING_EVENTS:
            next_d = _next_occurrence(ev, today)
            events.append(build_event(ev, next_d))
            if days_back > 0:
                prev_d = _prev_occurrence(ev, today)
                if prev_d and (today - prev_d).days <= days_back:
                    events.append(build_event(ev, prev_d))
        events.sort(key=lambda e: e["date"])

        data = {
            "events": events,
            "from": (today - timedelta(days=days_back)).isoformat(),
            "to": end.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
        _set_cache(cache_key, data)
        return data

    @staticmethod
    def _fetch_us_event_actuals_safe() -> Dict:
        try:
            return _fetch_us_event_actuals()
        except Exception as e:
            print(f"[macro] us_event_actuals error: {e}")
            return {}

    @staticmethod
    def build_ai_context() -> str:
        """Resumen compacto de macro para inyectar al prompt de DeepSeek."""
        try:
            ind = MacroDataService.get_indicators()
            cal = MacroDataService.get_calendar()
        except Exception as e:
            print(f"[macro] build_ai_context error: {e}")
            return ""

        lines: List[str] = []

        # Indicadores clave
        all_ind = ind.get("cl", []) + ind.get("us", [])
        for i in all_ind:
            v = i.get("value")
            if v is None:
                continue
            chg = i.get("change_pct")
            chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
            if i["format"] == "currency":
                v_str = f"${v:,.2f}"
            elif i["format"] == "percent":
                v_str = f"{v:.2f}%"
            elif i["format"] == "commodity":
                v_str = f"${v:,.2f}"
            else:
                v_str = f"{v:,.2f}"
            flag = ""
            if i.get("stale"):
                flag = f" [dato del {i.get('as_of', '?')}, fuente sin conexión]"
            elif i.get("source"):
                flag = f" [{i['source']}]"
            lines.append(f"  - {i['name']} ({i['country']}): {v_str}{chg_str}{flag}")

        ind_block = "\n".join(lines) if lines else "  (no disponible)"

        # Próximos 5 eventos
        upcoming = [e for e in cal.get("events", []) if e["when"] not in ("pasado",)][:5]
        cal_lines: List[str] = []
        for e in upcoming:
            stars = "★" * e["impact"] + "☆" * (3 - e["impact"])
            cal_lines.append(
                f"  - {e['date']} {e['hour_cl']} CL — {e['name']} ({e['country']}) [{stars}]"
            )
        cal_block = "\n".join(cal_lines) if cal_lines else "  (sin eventos próximos)"

        return (
            "**Indicadores económicos actuales:**\n"
            f"{ind_block}\n\n"
            "**Próximos eventos macro relevantes (high-impact):**\n"
            f"{cal_block}"
        )
