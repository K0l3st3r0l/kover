import html
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ..market.macro_data import MacroDataService

logger = logging.getLogger(__name__)

router = APIRouter()

# -- Superintendencia de Pensiones de Chile (public) --------------------------
SP_XLS_URL = "https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFPxls.php"
SP_REFERER = "https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFP.php"

AFP_CACHE_DIR = Path(os.getenv("AFP_CACHE_DIR", "/app/cache/afp"))

FUND_TYPES = ["A", "B", "C", "D", "E"]

FUND_COLORS = {
    "A": "#ef4444",   # red
    "B": "#f97316",   # orange
    "C": "#3b82f6",   # blue
    "D": "#22c55e",   # green
    "E": "#a855f7",   # purple
}

FUND_RISK = {
    "A": "Más Riesgoso",
    "B": "Riesgoso",
    "C": "Moderado",
    "D": "Conservador",
    "E": "Más Conservador",
}

# Límite legal de inversión en renta variable por tipo de fondo (D.L. 3500 /
# normativa de la Superintendencia de Pensiones). El resto del portafolio es
# renta fija (nacional + extranjera). E no invierte en renta variable.
FUND_EQUITY_LIMITS = {
    "A": "40%-80%",
    "B": "25%-60%",
    "C": "15%-40%",
    "D": "5%-20%",
    "E": "0%-5%",
}

# -- Composición real de cartera por fondo (Superintendencia de Pensiones) -----
# Endpoint público "cartera agregada": devuelve una tabla HTML con la
# distribución efectiva renta variable/fija, nacional vs extranjera, de cada
# fondo. Reemplaza el límite legal (FUND_EQUITY_LIMITS) por el dato real en el
# contexto de IA cuando está disponible.
SP_CARTERA_URL = "https://www.spensiones.cl/apps/carteras/genera_xsl.php"
SP_CARTERA_REFERER = "https://www.spensiones.cl/apps/carteras/menuItem.php"

# Promedio simple del %Fondo entre 4 AFP grandes, para no sesgar por la política
# de inversión de una sola administradora. No se pondera por patrimonio.
CARTERA_AFPS = ["UNO", "HABITAT", "PROVIDA", "CAPITAL"]
CARTERA_CACHE_DIR = Path(os.getenv("CARTERA_CACHE_DIR", "/app/cache/cartera"))
CARTERA_REQUEST_DELAY = 1.5    # seg entre requests (sitio gubernamental, conservador)
CARTERA_MAX_MONTHS_BACK = 4    # la publicación tiene rezago de ~1-2 meses

# -- Comité de IA multi-modelo (OpenCode Zen gateway, cuota OpenCode Go) ------
AI_API_URL = os.getenv("AI_API_URL", "https://opencode.ai/zen/go")
AI_API_KEY = os.getenv("AI_API_KEY", "")

# Modelos que usan endpoint Anthropic (/messages) en vez de OpenAI (/chat/completions)
AI_ANTHROPIC_PREFIXES = ["minimax", "qwen"]

AI_ANALYST_MODELS = ["deepseek-v4-pro", "minimax-m3"]
AI_ARBITER_MODEL = "glm-5.1"
AI_INVESTMENT_HORIZON_YEARS = 15
AI_COMMITTEE_CACHE_PATH = Path(os.getenv("AI_COMMITTEE_CACHE_DIR", "/app/cache")) / "ai_committee.json"
AI_COMMITTEE_TTL_SECONDS = 24 * 60 * 60

_ai_committee_lock = threading.Lock()
_ai_committee_generating = False


def _parse_cl_number(s: str) -> Optional[float]:
    """Parse Chilean number format: '70.735,03' -> 70735.03"""
    try:
        return float(s.strip().replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _cache_path(fund: str) -> Path:
    return AFP_CACHE_DIR / f"fund_{fund}.json"


def _save_afp_cache(fund: str, records: list) -> None:
    try:
        AFP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        serializable = [
            {**{k: v for k, v in r.items() if k != "date"}, "date": r["date"].isoformat()}
            for r in records
        ]
        _cache_path(fund).write_text(json.dumps(serializable), encoding="utf-8")
    except Exception as e:
        logger.warning(f"AFP cache write failed for {fund}: {e}")


def _load_afp_cache(fund: str) -> list:
    try:
        path = _cache_path(fund)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        for r in data:
            r["date"] = datetime.fromisoformat(r["date"])
        return data
    except Exception as e:
        logger.warning(f"AFP cache read failed for {fund}: {e}")
        return []


def _fetch_fund_data(fund: str, year_start: int, year_end: int) -> list:
    """
    Fetch CSV from SP and return list of {date, avg_value} sorted ascending.
    The CSV has columns: Date; [AFP1 Cuota; AFP1 Patrimonio; AFP2 Cuota; ...]
    We average the Valor Cuota across all AFPs (every 2nd column from col 1).
    """
    today = datetime.today()
    fecconf = today.strftime("%Y%m%d")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Referer": f"{SP_REFERER}?tf={fund}",
    }
    params = {
        "aaaaini": str(year_start),
        "aaaafin": str(year_end),
        "tf": fund,
        "fecconf": fecconf,
    }
    fetch_ok = False
    records = []

    try:
        resp = requests.get(SP_XLS_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        fetch_ok = True
    except Exception as e:
        logger.warning(f"Error fetching fund {fund}: {e}")

    if fetch_ok:
        try:
            text = resp.content.decode("latin-1")
        except Exception:
            text = resp.text

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(";")
            if len(parts) < 3:
                continue

            date_str = parts[0].strip()
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            cuotas = []
            patrimonios = []
            for i in range(1, len(parts), 2):
                val = _parse_cl_number(parts[i])
                if val is not None and val > 0:
                    cuotas.append(val)
                if i + 1 < len(parts):
                    pat = _parse_cl_number(parts[i + 1])
                    if pat is not None and pat > 0:
                        patrimonios.append(pat)

            if cuotas:
                records.append({
                    "date": date,
                    "date_str": date.strftime("%Y-%m-%d"),
                    "avg_value": sum(cuotas) / len(cuotas),
                    "total_patrimonio": sum(patrimonios) if patrimonios else 0.0,
                })

        records.sort(key=lambda x: x["date"])
        seen = {}
        for r in records:
            seen[r["date_str"]] = r
        records = sorted(seen.values(), key=lambda x: x["date"])

        if records:
            _save_afp_cache(fund, records)
            return records, False

    cached = _load_afp_cache(fund)
    if cached:
        logger.info(f"Serving fund {fund} from disk cache (source unavailable)")
        return cached, True

    return [], False


# -- Composición real de cartera por fondo ------------------------------------

def _parse_cartera_html(text: str) -> Optional[dict]:
    """
    Parsea la tabla HTML de cartera agregada de un fondo. Devuelve los % del
    fondo por categoría, o None si la página no trae datos (mes no publicado).

    La tabla tiene filas `<td>etiqueta</td><td>MMUS$</td><td>%Fondo</td>`,
    agrupadas en secciones INVERSIÓN NACIONAL TOTAL / INVERSIÓN EXTRANJERA TOTAL
    (con "RENTA VARIABLE"/"RENTA FIJA" repetidas dentro de cada una) y subtotales
    SUBTOTAL RENTA VARIABLE / SUBTOTAL RENTA FIJA al final.
    """
    out: dict = {}
    section: Optional[str] = None
    has_total = False

    for row in re.findall(r"<tr>(.*?)</tr>", text, re.S):
        tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in tds]
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue

        label = cells[0].upper()
        pct = _parse_cl_number(cells[-1])

        if "INVERSIÓN NACIONAL TOTAL" in label:
            section = "nacional"
            out["nacional_total"] = pct
        elif "INVERSIÓN EXTRANJERA TOTAL" in label:
            section = "extranjera"
            out["extranjera_total"] = pct
        elif label == "RENTA VARIABLE" and section and f"rv_{section}" not in out:
            out[f"rv_{section}"] = pct
        elif label.startswith("RENTA FIJA") and section and f"rf_{section}" not in out:
            out[f"rf_{section}"] = pct
        elif "SUBTOTAL RENTA VARIABLE" in label:
            out["renta_variable_total"] = pct
        elif "SUBTOTAL RENTA FIJA" in label:
            out["renta_fija_total"] = pct
        elif "TOTAL ACTIVOS" in label:
            has_total = True

    if not has_total or out.get("renta_variable_total") is None:
        return None
    return out


def _fetch_cartera_raw(fund: str, afp: str, fecpro: str) -> Optional[dict]:
    """Descarga y parsea la cartera de un fondo/AFP, con backoff exponencial."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Referer": SP_CARTERA_REFERER,
    }
    params = {"fecpro": fecpro, "listado": "2", "tipofondo": fund, "nomafp": afp}

    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(SP_CARTERA_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            try:
                text = resp.content.decode("utf-8")
            except UnicodeDecodeError:
                text = resp.content.decode("latin-1")
            return _parse_cartera_html(text)
        except Exception as e:
            last_err = e
            time.sleep(CARTERA_REQUEST_DELAY * (2 ** attempt))
    logger.warning(f"Cartera fetch falló fondo {fund} AFP {afp} ({fecpro}): {last_err}")
    return None


def _cartera_cache_path(fecpro: str) -> Path:
    return CARTERA_CACHE_DIR / f"cartera_{fecpro}.json"


def _save_cartera_cache(fecpro: str, data: dict) -> None:
    try:
        CARTERA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cartera_cache_path(fecpro).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cartera cache write failed {fecpro}: {e}")


def _load_cartera_cache(fecpro: str) -> Optional[dict]:
    try:
        path = _cartera_cache_path(fecpro)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Cartera cache read failed {fecpro}: {e}")
    return None


def _resolve_cartera_fecpro() -> Optional[str]:
    """
    Encuentra el mes (YYYYMM) más reciente con datos publicados. Por el rezago
    de publicación, prueba desde el mes actual hacia atrás hasta
    CARTERA_MAX_MONTHS_BACK, sondeando con fondo A / primera AFP.
    """
    today = datetime.today()
    for back in range(CARTERA_MAX_MONTHS_BACK + 1):
        month, year = today.month - back, today.year
        while month <= 0:
            month += 12
            year -= 1
        fecpro = f"{year}{month:02d}"
        if _load_cartera_cache(fecpro):
            return fecpro
        probe = _fetch_cartera_raw("A", CARTERA_AFPS[0], fecpro)
        time.sleep(CARTERA_REQUEST_DELAY)
        if probe:
            return fecpro
    return None


def _fetch_cartera_composition() -> Optional[dict]:
    """
    Composición real promedio por fondo (A-E), promediando CARTERA_AFPS. Cachea
    el resultado por mes. Devuelve None si no hay datos publicados disponibles.
    """
    fecpro = _resolve_cartera_fecpro()
    if not fecpro:
        logger.warning("Cartera: no se encontró mes con datos publicados")
        return None

    cached = _load_cartera_cache(fecpro)
    if cached:
        return cached

    metrics = [
        "rv_nacional", "rv_extranjera", "rf_nacional", "rf_extranjera",
        "renta_variable_total", "renta_fija_total",
        "nacional_total", "extranjera_total",
    ]
    by_fund: dict = {}
    for fund in FUND_TYPES:
        acc = {m: [] for m in metrics}
        for afp in CARTERA_AFPS:
            data = _fetch_cartera_raw(fund, afp, fecpro)
            time.sleep(CARTERA_REQUEST_DELAY)
            if not data:
                continue
            for m in metrics:
                if data.get(m) is not None:
                    acc[m].append(data[m])
        averaged = {m: round(sum(v) / len(v), 2) for m, v in acc.items() if v}
        if averaged:
            by_fund[fund] = averaged

    if not by_fund:
        return None

    result = {"fecpro": fecpro, "afps": CARTERA_AFPS, "funds": by_fund}
    _save_cartera_cache(fecpro, result)
    return result


def _normalize_series(records: list) -> list:
    """Normalise values to base 100 at the first data point."""
    if not records:
        return []
    base = records[0]["avg_value"]
    if base == 0:
        return records
    return [
        {**r, "normalized": round((r["avg_value"] / base) * 100, 4)}
        for r in records
    ]


def _filter_by_period(records: list, days: int) -> list:
    """Keep only the last `days` calendar days."""
    if not records or days <= 0:
        return records
    cutoff = records[-1]["date"] - timedelta(days=days)
    return [r for r in records if r["date"] >= cutoff]


def _compute_obv(records: list) -> list:
    """
    On-Balance Volume using total_patrimonio as proxy for volume.
    OBV rises when cuota closes higher, falls when it closes lower.
    """
    if not records:
        return records
    result = []
    obv = 0.0
    prev_value = None
    for r in records:
        pat = r.get("total_patrimonio", 0.0)
        if prev_value is not None:
            if r["avg_value"] > prev_value:
                obv += pat
            elif r["avg_value"] < prev_value:
                obv -= pat
        prev_value = r["avg_value"]
        result.append({**r, "obv": round(obv, 0)})
    return result


# -- mindicador.cl (public, no auth) ------------------------------------------
MINDICADOR_BASE = "https://mindicador.cl/api"
MINDICADOR_CACHE_DIR = Path(os.getenv("MINDICADOR_CACHE_DIR", "/app/cache/mindicador"))

MACRO_INDICATORS = {
    "tpm":            {"label": "TPM Banco Central",   "unit": "%",    "freq": "diaria"},
    "ipc":            {"label": "IPC (var. mensual)",  "unit": "%",    "freq": "mensual"},
    "libra_cobre":    {"label": "Cobre (USD/lb)",      "unit": "USD",  "freq": "diaria"},
    "uf":             {"label": "UF",                  "unit": "CLP",  "freq": "diaria"},
    "tasa_desempleo": {"label": "Tasa de Desempleo",   "unit": "%",    "freq": "trimestral"},
    "imacec":         {"label": "IMACEC",              "unit": "%",    "freq": "mensual"},
}


def _save_mindicador_cache(indicator: str, series: list) -> None:
    try:
        MINDICADOR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (MINDICADOR_CACHE_DIR / f"{indicator}.json").write_text(json.dumps(series), encoding="utf-8")
    except Exception as e:
        logger.warning(f"mindicador cache write {indicator}: {e}")


def _load_mindicador_cache(indicator: str) -> list:
    try:
        path = MINDICADOR_CACHE_DIR / f"{indicator}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"mindicador cache read {indicator}: {e}")
    return []


def _fetch_mindicador(indicator: str, years: list[int]) -> list:
    records: dict[str, float] = {}
    for year in years:
        try:
            r = requests.get(f"{MINDICADOR_BASE}/{indicator}/{year}", timeout=10)
            r.raise_for_status()
            for item in r.json().get("serie", []):
                date_str = item["fecha"][:10]
                records[date_str] = item["valor"]
        except Exception as e:
            logger.warning(f"mindicador {indicator}/{year}: {e}")

    series = sorted(
        [{"date": k, "value": v} for k, v in records.items()],
        key=lambda x: x["date"],
    )
    if series:
        _save_mindicador_cache(indicator, series)
        return series

    # Fuente caída: servir el último dato bueno persistido en disco.
    cached = _load_mindicador_cache(indicator)
    if cached:
        logger.info(f"mindicador {indicator}: sirviendo desde caché en disco (fuente caída)")
    return cached


@router.get("/macro-cl")
def get_macro_chile():
    """
    Returns macro indicators for Chile: TPM, IPC, copper price.
    Data sourced from mindicador.cl (public API, no auth required).
    """
    today = datetime.today()
    years = [today.year - 3, today.year - 2, today.year - 1, today.year]

    result = {}
    for key, meta in MACRO_INDICATORS.items():
        data = _fetch_mindicador(key, years)
        latest = data[-1] if data else None
        prev   = data[-2] if len(data) >= 2 else None
        result[key] = {
            "label":   meta["label"],
            "unit":    meta["unit"],
            "freq":    meta["freq"],
            "data":    data,
            "latest":  latest,
            "change":  round(latest["value"] - prev["value"], 4) if latest and prev else None,
        }

    return JSONResponse(content={"indicators": result, "source": "mindicador.cl"})


@router.get("/afp-funds")
def get_afp_funds(
    days: int = Query(
        default=365, ge=30, le=5000,
        description="Number of calendar days of history to return",
    ),
    funds: str = Query(
        default="A,B,C,D,E",
        description="Comma-separated fund letters (A-E)",
    ),
):
    """
    Returns normalised historical performance (base 100) for AFP fund types A-E.
    Data sourced from Superintendencia de Pensiones de Chile (public data).
    """
    requested = [
        f.strip().upper()
        for f in funds.split(",")
        if f.strip().upper() in FUND_TYPES
    ]
    if not requested:
        raise HTTPException(status_code=400, detail="No valid fund types specified")

    today = datetime.today()
    year_end = today.year
    # Add a 2-year buffer so normalisation anchor predates the requested period
    year_start = max(2002, year_end - (days // 365) - 2)

    result = {}
    errors = []
    any_from_cache = False

    for fund_letter in requested:
        raw, from_cache = _fetch_fund_data(fund_letter, year_start, year_end)
        if not raw:
            errors.append(fund_letter)
            continue

        if from_cache:
            any_from_cache = True

        filtered = _filter_by_period(raw, days)
        if not filtered:
            errors.append(fund_letter)
            continue

        with_obv = _compute_obv(filtered)
        normalized = _normalize_series(with_obv)

        result[fund_letter] = {
            "color": FUND_COLORS[fund_letter],
            "risk_label": FUND_RISK[fund_letter],
            "data": [
                {
                    "date": r["date_str"],
                    "value": r["normalized"],
                    "raw_value": round(r["avg_value"], 2),
                    "patrimonio": round(r.get("total_patrimonio", 0.0), 0),
                    "obv": r.get("obv", 0.0),
                }
                for r in normalized
            ],
        }

    if not result:
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch AFP fund data. Failed: {errors}",
        )

    return JSONResponse(
        content={
            "funds": result,
            "period_days": days,
            "errors": errors,
            "from_cache": any_from_cache,
            "source": "Superintendencia de Pensiones de Chile",
        }
    )


# -- Comité de IA multi-modelo -------------------------------------------------
# Dos analistas (deepseek-v4-pro, minimax-m3) analizan los mismos datos en
# paralelo y un árbitro independiente (glm-5.1) contrasta ambos veredictos y
# emite una decisión final. Restricción dura: máximo 2 fondos, igual que la
# distribución sugerida basada en reglas del frontend.

def _ai_fund_signal(fund: str, year_start: int, year_end: int, days: int) -> Optional[dict]:
    raw, _ = _fetch_fund_data(fund, year_start, year_end)
    if not raw:
        return None
    filtered = _filter_by_period(raw, days)
    if len(filtered) < 30:
        return None
    with_obv = _compute_obv(filtered)
    normalized = _normalize_series(with_obv)

    last = normalized[-1]
    p30 = normalized[max(0, len(normalized) - 30)]
    mom30d = last["normalized"] - p30["normalized"]

    obv_values = [r["obv"] for r in normalized]
    obv_min, obv_max = min(obv_values), max(obv_values)
    obv_range = obv_max - obv_min
    if obv_range > 0:
        pct = (last["obv"] - obv_min) / obv_range
        obv_pos = "alto" if pct > 0.7 else ("bajo" if pct < 0.3 else "medio")
    else:
        obv_pos = "medio"

    max_val = max(r["normalized"] for r in normalized)
    drawdown = ((last["normalized"] - max_val) / max_val) * 100 if max_val else 0.0

    return {
        "fund": fund,
        "mom30d": round(mom30d, 2),
        "drawdown": round(drawdown, 2),
        "obv_pos": obv_pos,
        "spread_vs_first": round(last["normalized"] - normalized[0]["normalized"], 2),
    }


def _build_ai_market_context(days: int = 200) -> dict:
    today = datetime.today()
    year_end = today.year
    year_start = max(2002, year_end - (days // 365) - 2)

    funds = {f: _ai_fund_signal(f, year_start, year_end, days) for f in FUND_TYPES}
    if any(v is None for v in funds.values()):
        raise RuntimeError("No se pudo construir el contexto de mercado (datos de fondos AFP no disponibles)")

    try:
        cartera = _fetch_cartera_composition()
    except Exception as e:
        logger.warning(f"Cartera composition no disponible, se usa límite legal: {e}")
        cartera = None

    # Contexto macro internacional + calendario económico, reutilizando el mismo
    # bloque que alimenta el análisis de /noticias (DXY, oro, WTI, US 10Y, VIX,
    # FOMC/NFP/CPI...). Los fondos A/B tienen 65-83% de renta variable extranjera,
    # así que estos indicadores son los que realmente mueven su desempeño.
    try:
        macro_global = MacroDataService.build_ai_context()
    except Exception as e:
        logger.warning(f"Contexto macro global no disponible: {e}")
        macro_global = ""

    years = [today.year - 1, today.year]
    tpm_series = _fetch_mindicador("tpm", years)
    ipc_series = _fetch_mindicador("ipc", years)
    imacec_series = _fetch_mindicador("imacec", years)
    cobre_series = _fetch_mindicador("libra_cobre", years)
    dolar_series = _fetch_mindicador("dolar", years)

    tpm_last = tpm_series[-1]["value"] if tpm_series else None
    tpm_3m_ago = tpm_series[max(0, len(tpm_series) - 90)]["value"] if tpm_series else None
    tpm_trend = round(tpm_last - tpm_3m_ago, 2) if tpm_last is not None and tpm_3m_ago is not None else None

    ipc_avg_3m = round(sum(d["value"] for d in ipc_series[-3:]) / len(ipc_series[-3:]), 2) if len(ipc_series) >= 1 else None
    imacec_last = imacec_series[-1]["value"] if imacec_series else None

    cobre_last = cobre_series[-1]["value"] if cobre_series else None
    cobre_p30 = cobre_series[max(0, len(cobre_series) - 30)]["value"] if cobre_series else None
    cobre_mom30d = round(((cobre_last - cobre_p30) / cobre_p30) * 100, 2) if cobre_last and cobre_p30 else None

    dolar_recent = [d["value"] for d in dolar_series[-60:]] if dolar_series else []
    dolar_last = dolar_recent[-1] if dolar_recent else None
    dolar_range = (round(min(dolar_recent)), round(max(dolar_recent))) if dolar_recent else None

    return {
        "funds": funds,
        "tpm_last": tpm_last,
        "tpm_trend_3m": tpm_trend,
        "ipc_avg_3m": ipc_avg_3m,
        "imacec_last": imacec_last,
        "cobre_mom30d": cobre_mom30d,
        "dolar_last": dolar_last,
        "dolar_range_60d": dolar_range,
        "cartera": cartera,
        "macro_global": macro_global,
        "horizon_years": AI_INVESTMENT_HORIZON_YEARS,
    }


def _ai_context_to_text(ctx: dict) -> str:
    funds = ctx["funds"]
    lines = [
        f"- TPM Banco Central: {ctx['tpm_last']}% (variación últimos 3 meses: {ctx['tpm_trend_3m']:+.2f}pp)" if ctx["tpm_last"] is not None else "- TPM: sin datos",
        f"- IPC mensual (promedio últimos 3 meses): {ctx['ipc_avg_3m']}%" if ctx["ipc_avg_3m"] is not None else "- IPC: sin datos",
        f"- Imacec (var. % interanual último dato): {ctx['imacec_last']}%" if ctx["imacec_last"] is not None else "- Imacec: sin datos",
        f"- Cobre, momentum 30d: {ctx['cobre_mom30d']:+.2f}%" if ctx["cobre_mom30d"] is not None else "- Cobre: sin datos",
        f"- USD/CLP: {ctx['dolar_last']} (rango últimos 60 días: {ctx['dolar_range_60d'][0]}-{ctx['dolar_range_60d'][1]})" if ctx["dolar_range_60d"] else "- USD/CLP: sin datos",
    ]
    cartera = ctx.get("cartera") or {}
    cartera_funds = cartera.get("funds", {})
    cartera_fecpro = cartera.get("fecpro")
    for f in FUND_TYPES:
        s = funds[f]
        comp = cartera_funds.get(f)
        if comp:
            composicion = (
                f"composición real al mes {cartera_fecpro}: renta variable "
                f"{comp.get('renta_variable_total', 0):.1f}% del portafolio "
                f"(nacional {comp.get('rv_nacional', 0):.1f}% + extranjera {comp.get('rv_extranjera', 0):.1f}%), "
                f"renta fija {comp.get('renta_fija_total', 0):.1f}%, "
                f"exposición extranjera total {comp.get('extranjera_total', 0):.1f}%"
            )
        else:
            composicion = (
                f"límite legal renta variable {FUND_EQUITY_LIMITS[f]} del portafolio, "
                f"resto renta fija nacional/extranjera"
            )
        lines.append(
            f"- Fondo {f} ({FUND_RISK[f]}, {composicion}): momentum 30d {s['mom30d']:+.2f}%, "
            f"posición OBV '{s['obv_pos']}' (zona del rango del período), "
            f"drawdown desde máximo del período {s['drawdown']:.2f}%"
        )
    lines.append(
        f"- Spread acumulado A vs E en el período: "
        f"{funds['A']['spread_vs_first'] - funds['E']['spread_vs_first']:.2f} puntos"
    )
    lines.append(f"- Horizonte de inversión del usuario: {ctx['horizon_years']} años")

    macro_global = ctx.get("macro_global")
    if macro_global:
        lines.append(
            "\nContexto macro internacional y calendario económico "
            "(clave para los fondos con alta exposición a renta variable extranjera):\n"
            f"{macro_global}"
        )
    return "\n".join(lines)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _ai_call_openai(model: str, system: str, user: str, reasoning_effort: Optional[str] = None) -> str:
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": 8000,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    resp = requests.post(
        f"{AI_API_URL}/v1/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {AI_API_KEY}"},
        json=body,
        timeout=240,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"].get("content") or ""


def _ai_call_anthropic(model: str, system: str, user: str) -> str:
    resp = requests.post(
        f"{AI_API_URL}/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": AI_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": 8000,
        },
        timeout=240,
    )
    resp.raise_for_status()
    data = resp.json()
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block.get("text") or ""
    return ""


def _ai_run_model(model: str, system: str, user: str) -> dict:
    is_anthropic = any(model.lower().startswith(p) for p in AI_ANTHROPIC_PREFIXES)
    raw = (
        _ai_call_anthropic(model, system, user)
        if is_anthropic
        else _ai_call_openai(model, system, user, reasoning_effort="high" if "deepseek" in model else None)
    )
    try:
        return {"model": model, "parsed": json.loads(_strip_json_fences(raw)), "raw": raw}
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"AI committee: no se pudo parsear JSON de {model}")
        return {"model": model, "parsed": None, "raw": raw}


_URGENCY_FIELDS_SPEC = (
    "Además evalúa la urgencia de mercado en general (no conoces la posición de ningún usuario "
    "particular, este veredicto es único y se reutiliza para todos): "
    "'urgencia_reducir_riesgo' (alta/media/baja) — qué tan urgente sería, según las señales actuales, "
    "reducir exposición en fondos riesgosos (A/B) si alguien estuviera sobreexpuesto ahí; "
    "'confirmacion_entrada_riesgo' (confirmada/parcial/no_confirmada) — si hay confirmación técnica "
    "suficiente (momentum + OBV) para aumentar exposición en A/B si alguien estuviera subexpuesto; "
    "'urgencia_motivo' — explicación breve (1-2 frases) de ambos juicios."
)

_ANALYST_SYSTEM_PROMPT = (
    "Eres un analista de inversiones experto en el sistema de AFP chileno. Analizas señales técnicas y "
    "macroeconómicas de los 5 fondos disponibles (A, más riesgoso/renta variable, hasta E, más "
    "conservador/renta fija) para sugerir la distribución de portafolio más adecuada dado el escenario "
    "actual y el horizonte de inversión. Los datos incluyen el límite legal de renta variable de cada "
    "fondo — úsalo para razonar cómo factores como el cobre, el USD/CLP o los mercados bursátiles "
    "(nacional e internacional) impactan de forma distinta a cada fondo según su composición. "
    "Restricción dura: la AFP solo permite distribuir entre máximo 2 "
    "fondos simultáneamente, nunca 3 o más — elige la combinación de hasta 2 fondos (de los 5 disponibles) "
    "que mejor se ajuste. " + _URGENCY_FIELDS_SPEC
)

_ANALYST_OUTPUT_SCHEMA = (
    'Responde SOLO con JSON: {"regimen":"...","analisis":"...",'
    '"distribucion":[{"fondo":"X","pct":N}],"riesgos_a_vigilar":["..."],'
    '"urgencia_reducir_riesgo":"alta|media|baja",'
    '"confirmacion_entrada_riesgo":"confirmada|parcial|no_confirmada",'
    '"urgencia_motivo":"..."}'
)

_ARBITER_SYSTEM_PROMPT = (
    "Eres el árbitro final de un comité de inversión para el sistema de AFP chileno. Recibes dos análisis "
    "independientes de otros analistas senior sobre la misma situación de mercado, cada uno evaluando los "
    "5 fondos disponibles (A a E) con su propia distribución sugerida. Tu trabajo es: (1) identificar en "
    "qué coinciden y en qué difieren, (2) evaluar críticamente los argumentos de cada uno (no asumas que "
    "uno es automáticamente correcto), y (3) emitir una decisión final fundamentada. Restricción dura: "
    "máximo 2 fondos en la distribución final, nunca 3 o más. " + _URGENCY_FIELDS_SPEC
)

_ARBITER_OUTPUT_SCHEMA = (
    'Responde SOLO con JSON: {"coincidencias":["..."],"diferencias":["..."],'
    '"evaluacion_critica":"...","decision_final":{"regimen":"...",'
    '"distribucion":[{"fondo":"X","pct":N}],"justificacion":"...",'
    '"urgencia_reducir_riesgo":"alta|media|baja",'
    '"confirmacion_entrada_riesgo":"confirmada|parcial|no_confirmada",'
    '"urgencia_motivo":"..."},'
    '"riesgos_a_vigilar":["..."]}'
)


def generate_ai_committee() -> dict:
    ctx = _build_ai_market_context()
    data_text = _ai_context_to_text(ctx)
    analyst_user = f"Datos actuales:\n{data_text}\n\nEntrega tu análisis y la distribución sugerida. {_ANALYST_OUTPUT_SCHEMA}"

    with ThreadPoolExecutor(max_workers=len(AI_ANALYST_MODELS)) as pool:
        analyst_results = list(pool.map(
            lambda m: _ai_run_model(m, _ANALYST_SYSTEM_PROMPT, analyst_user),
            AI_ANALYST_MODELS,
        ))

    analyses_text = "\n\n".join(
        f"Análisis del Analista ({r['model']}):\n{r['raw']}" for r in analyst_results
    )
    arbiter_user = (
        f"{analyses_text}\n\nAmbos analistas vieron los mismos datos de mercado. Evalúa ambas posturas y "
        f"entrega tu veredicto final. {_ARBITER_OUTPUT_SCHEMA}"
    )
    arbiter_result = _ai_run_model(AI_ARBITER_MODEL, _ARBITER_SYSTEM_PROMPT, arbiter_user)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "context": ctx,
        "analysts": analyst_results,
        "arbiter": arbiter_result,
    }


def _load_ai_committee_cache() -> Optional[dict]:
    try:
        if not AI_COMMITTEE_CACHE_PATH.exists():
            return None
        return json.loads(AI_COMMITTEE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"AI committee cache read failed: {e}")
        return None


def _save_ai_committee_cache(data: dict) -> None:
    AI_COMMITTEE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_COMMITTEE_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _ai_committee_is_stale(cached: dict) -> bool:
    try:
        generated_at = datetime.fromisoformat(cached["generated_at"].replace("Z", ""))
        return (datetime.utcnow() - generated_at).total_seconds() > AI_COMMITTEE_TTL_SECONDS
    except Exception:
        return True


def _regenerate_ai_committee_async() -> None:
    global _ai_committee_generating
    with _ai_committee_lock:
        if _ai_committee_generating:
            return
        _ai_committee_generating = True

    def _run():
        global _ai_committee_generating
        try:
            result = generate_ai_committee()
            _save_ai_committee_cache(result)
            logger.info("AI committee: caché regenerada correctamente")
        except Exception as e:
            logger.error(f"AI committee: error regenerando: {e}")
        finally:
            with _ai_committee_lock:
                _ai_committee_generating = False

    threading.Thread(target=_run, daemon=True).start()


def ai_committee_background_loop() -> None:
    """Loop de fondo iniciado en el startup de la app: revisa cada hora y
    regenera el comité de IA si el caché tiene más de 24 horas."""
    while True:
        try:
            cached = _load_ai_committee_cache()
            if cached is None or _ai_committee_is_stale(cached):
                _regenerate_ai_committee_async()
        except Exception as e:
            logger.error(f"AI committee background loop error: {e}")
        time.sleep(60 * 60)


@router.get("/ai-committee")
def get_ai_committee():
    """
    Devuelve el último veredicto del comité de IA (2 analistas + árbitro) sobre
    la distribución sugerida de fondos AFP. Se regenera 1 vez al día en
    background; este endpoint solo lee el caché, nunca bloquea esperando a la IA.
    """
    cached = _load_ai_committee_cache()
    if cached is None:
        _regenerate_ai_committee_async()
        return JSONResponse(content={"status": "generating", "generated_at": None})

    if _ai_committee_is_stale(cached):
        _regenerate_ai_committee_async()

    return JSONResponse(content={"status": "ready", **cached})
