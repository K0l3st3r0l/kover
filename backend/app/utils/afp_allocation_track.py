"""Retornos hipotéticos de una distribución AFP (máx. 2 fondos).

Usa valor cuota. Rebalance al cierre del primer día hábil >= cada veredicto.
"""

from __future__ import annotations

from typing import Optional

FUNDS = ("A", "B", "C", "D", "E")


def weights_from_dist(dist) -> dict[str, float]:
    weights = {f: 0.0 for f in FUNDS}
    if not isinstance(dist, list):
        return weights
    for item in dist:
        if not isinstance(item, dict):
            continue
        fund = str(item.get("fondo") or item.get("fund") or "").upper()
        try:
            pct = float(item.get("pct") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        if fund in weights and pct > 0:
            weights[fund] = pct / 100.0
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {f: v / total for f, v in weights.items()}


def first_date_on_or_after(dates: list[str], as_of: str) -> Optional[str]:
    for day in dates:
        if day >= as_of:
            return day
    return None


def hold_return_pct(
    weights: dict[str, float],
    cuotas: dict[str, dict[str, float]],
    start: str,
    end: str,
) -> Optional[float]:
    acc = 0.0
    used = False
    for fund, weight in weights.items():
        if weight <= 0:
            continue
        start_px = cuotas.get(fund, {}).get(start)
        end_px = cuotas.get(fund, {}).get(end)
        if not start_px or not end_px:
            return None
        acc += weight * (end_px / start_px - 1.0)
        used = True
    if not used:
        return None
    return round(acc * 100.0, 2)


def rebase_fund(
    dates: list[str],
    cuotas: dict[str, dict[str, float]],
    fund: str,
    start: str,
) -> list[Optional[float]]:
    anchor = cuotas.get(fund, {}).get(start)
    if not anchor:
        return [None] * len(dates)
    out: list[Optional[float]] = []
    for day in dates:
        px = cuotas.get(fund, {}).get(day)
        out.append(round(100.0 * px / anchor, 4) if px else None)
    return out


def switching_path(
    dates: list[str],
    cuotas: dict[str, dict[str, float]],
    events: list[tuple[str, dict[str, float]]],
) -> list[dict]:
    """events: (as_of_date, weights) ordenados. Valor inicial 100."""
    if not dates or not events:
        return []
    start = first_date_on_or_after(dates, events[0][0])
    if not start:
        return []
    dates = [d for d in dates if d >= start]
    if not dates:
        return []

    event_on_day: dict[str, dict[str, float]] = {}
    for as_of, weights in events:
        day = first_date_on_or_after(dates, as_of)
        if day:
            event_on_day[day] = weights

    weights = event_on_day.get(dates[0], events[0][1])
    value = 100.0
    out = [{"date": dates[0], "value": 100.0}]

    for i in range(1, len(dates)):
        prev, day = dates[i - 1], dates[i]
        growth = 0.0
        ok = True
        for fund, weight in weights.items():
            if weight <= 0:
                continue
            a = cuotas.get(fund, {}).get(prev)
            b = cuotas.get(fund, {}).get(day)
            if not a or not b:
                ok = False
                break
            growth += weight * (b / a)
        if not ok or growth <= 0:
            growth = 1.0
        value *= growth
        out.append({"date": day, "value": round(value, 4)})
        if day in event_on_day:
            weights = event_on_day[day]
    return out
