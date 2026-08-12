"""Registro de jobs con APScheduler.

Los horarios van en America/New_York porque siguen el mercado, no el huso del
usuario. El scheduler es in-process: kover-backend corre un solo worker de
uvicorn, así que no hay riesgo de que N procesos disparen el mismo job. Si algún
día se agrega `--workers`, hay que mover esto a un proceso aparte o tomar un
lock en Postgres — el guard de abajo lo deja explícito.
"""

from __future__ import annotations

import os
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..logging_config import get_logger
from . import tasks

logger = get_logger(__name__)

MARKET_TZ = "America/New_York"

_scheduler: Optional[BackgroundScheduler] = None


def _enabled() -> bool:
    if os.getenv("SCHEDULER_ENABLED", "true").lower() in ("false", "0", "no"):
        return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    workers = os.getenv("UVICORN_WORKERS")
    if workers and workers.isdigit() and int(workers) > 1:
        logger.warning(
            "scheduler deshabilitado: más de un worker duplicaría cada job",
            extra={"workers": workers},
        )
        return False
    return True


def start_scheduler() -> Optional[BackgroundScheduler]:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not _enabled():
        logger.info("scheduler no arranca (deshabilitado por entorno)")
        return None

    scheduler = BackgroundScheduler(timezone=MARKET_TZ)

    # Salud de proveedores: barato y frecuente. Es lo que alimenta /api/data-health.
    scheduler.add_job(
        tasks.refresh_provider_status,
        CronTrigger(minute="*/15", timezone=MARKET_TZ),
        id="provider_status",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # Campañas: derivadas del histórico, así que solo cambian cuando entran
    # transacciones nuevas. Una pasada diaria tras el cierre alcanza.
    scheduler.add_job(
        tasks.rebuild_all_campaigns,
        CronTrigger(hour=17, minute=30, day_of_week="mon-fri", timezone=MARKET_TZ),
        id="rebuild_campaigns",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Fundamentales: los filings se publican a lo largo del día, pero un
    # refresco diario antes de la apertura alcanza. No se recargan durante la
    # sesión: no cambian intradía.
    scheduler.add_job(
        tasks.refresh_fundamentals_for_holdings,
        CronTrigger(hour=6, minute=15, day_of_week="mon-fri", timezone=MARKET_TZ),
        id="fundamentals_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=7200,
    )

    # Universo $10-20 optionable + riesgo de mercado (K3). Antes que
    # fundamentals_refresh: deja el universo fresco por si esa tarea se
    # extiende a cubrirlo más adelante. Puede tardar varios minutos (lote de
    # precios + chequeo de optionabilidad + barras de 6 meses), por eso el
    # misfire_grace_time generoso.
    scheduler.add_job(
        tasks.run_universe_scan,
        CronTrigger(hour=5, minute=45, day_of_week="mon-fri", timezone=MARKET_TZ),
        id="universe_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=7200,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "scheduler arrancado",
        extra={"jobs": [j.id for j in scheduler.get_jobs()], "tz": MARKET_TZ},
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_jobs() -> list[dict]:
    if _scheduler is None:
        return []
    return [
        {
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in _scheduler.get_jobs()
    ]
