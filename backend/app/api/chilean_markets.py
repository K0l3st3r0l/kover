import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

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

MACRO_INDICATORS = {
    "tpm":            {"label": "TPM Banco Central",   "unit": "%",    "freq": "diaria"},
    "ipc":            {"label": "IPC (var. mensual)",  "unit": "%",    "freq": "mensual"},
    "libra_cobre":    {"label": "Cobre (USD/lb)",      "unit": "USD",  "freq": "diaria"},
    "uf":             {"label": "UF",                  "unit": "CLP",  "freq": "diaria"},
    "tasa_desempleo": {"label": "Tasa de Desempleo",   "unit": "%",    "freq": "trimestral"},
    "imacec":         {"label": "IMACEC",              "unit": "%",    "freq": "mensual"},
}


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
    return sorted(
        [{"date": k, "value": v} for k, v in records.items()],
        key=lambda x: x["date"],
    )


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
