"""Redondeo a tick y precios objetivo de take profit.

Nunca asumir tick de $0.01 universal: las opciones bajo $3 suelen cotizar en
incrementos de $0.01, pero sobre ese nivel muchas clases usan $0.05. Un target
que no cae en un tick válido no es un precio que se pueda enviar como orden.
"""

from __future__ import annotations

import math
from typing import Optional

DEFAULT_PROFIT_TARGETS = (70, 75, 80)


def round_to_tick(price: float, min_tick: float, mode: str = "nearest") -> float:
    """Lleva un precio al tick válido más cercano (o hacia arriba/abajo)."""
    if min_tick is None or min_tick <= 0:
        return round(price, 2)
    ratio = price / min_tick
    if mode == "up":
        ticks = math.ceil(ratio - 1e-9)
    elif mode == "down":
        ticks = math.floor(ratio + 1e-9)
    else:
        ticks = round(ratio)
    # El tick puede ser 0.05; el redondeo decimal evita 0.15000000000000002.
    return round(ticks * min_tick, 10)


def calculate_target_price(
    entry_price: float, profit_target: float, min_tick: float = 0.01
) -> Optional[float]:
    """Precio de recompra que realiza `profit_target`% de la prima de entrada.

    entry 0.50 con target 80% → 0.10.

    Se redondea hacia ARRIBA: un target por debajo del tick válido más cercano
    es una orden que no se llena, y de los dos errores posibles conviene el que
    ejecuta y captura algo menos, no el que nunca ejecuta.
    """
    if entry_price is None or entry_price <= 0:
        return None
    if profit_target is None or not (0 < profit_target < 100):
        return None
    raw = entry_price * (1 - profit_target / 100.0)
    target = round_to_tick(raw, min_tick, mode="up")
    # Con primas muy chicas el redondeo hacia arriba puede alcanzar la entrada:
    # ahí no queda ganancia que capturar y el target no es accionable.
    if target >= entry_price:
        return None
    return target


def take_profit_targets(
    entry_price: float, min_tick: float = 0.01, targets: tuple[int, ...] = DEFAULT_PROFIT_TARGETS
) -> dict[int, Optional[float]]:
    return {t: calculate_target_price(entry_price, t, min_tick) for t in targets}


def captured_pct(entry_price: float, current_price: float) -> Optional[float]:
    """Porcentaje de la prima ya capturado si se recomprara a `current_price`.

    `current_price` tiene que ser el ASK: recomprar exige pagar el ask, y usar
    `last` produce señales de take profit que no se pueden ejecutar.
    """
    if entry_price is None or entry_price <= 0 or current_price is None:
        return None
    return round((1 - current_price / entry_price) * 100, 2)
