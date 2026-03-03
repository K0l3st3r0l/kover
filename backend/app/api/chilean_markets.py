import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# -- Superintendencia de Pensiones de Chile (public) --------------------------
SP_XLS_URL = "https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFPxls.php"
SP_REFERER = "https://www.spensiones.cl/apps/valoresCuotaFondo/vcfAFP.php"

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
    try:
        resp = requests.get(SP_XLS_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Error fetching fund {fund}: {e}")
        return []

    try:
        text = resp.content.decode("latin-1")
    except Exception:
        text = resp.text

    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) < 3:
            continue

        # Date field must be YYYY-MM-DD
        date_str = parts[0].strip()
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue  # skip header / metadata rows

        # Collect "Valor Cuota" columns (indices 1, 3, 5, ... – every 2nd from 1)
        cuotas = []
        for i in range(1, len(parts), 2):
            val = _parse_cl_number(parts[i])
            if val is not None and val > 0:
                cuotas.append(val)

        if cuotas:
            records.append({
                "date": date,
                "date_str": date.strftime("%Y-%m-%d"),
                "avg_value": sum(cuotas) / len(cuotas),
            })

    records.sort(key=lambda x: x["date"])
    # Deduplicate: keep last entry per day
    seen = {}
    for r in records:
        seen[r["date_str"]] = r
    return sorted(seen.values(), key=lambda x: x["date"])


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

    for fund_letter in requested:
        raw = _fetch_fund_data(fund_letter, year_start, year_end)
        if not raw:
            errors.append(fund_letter)
            continue

        filtered = _filter_by_period(raw, days)
        if not filtered:
            errors.append(fund_letter)
            continue

        normalized = _normalize_series(filtered)

        result[fund_letter] = {
            "color": FUND_COLORS[fund_letter],
            "risk_label": FUND_RISK[fund_letter],
            "data": [
                {
                    "date": r["date_str"],
                    "value": r["normalized"],
                    "raw_value": round(r["avg_value"], 2),
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
            "source": "Superintendencia de Pensiones de Chile",
        }
    )
