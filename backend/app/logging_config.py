"""Logging estructurado en JSON.

Los jobs del scanner corren desatendidos: un `print` no sirve para saber por qué
una corrida quedó a medias. Cada línea lleva el contexto de la operación
(`job_id`, `scanner_run_id`, `provider`, `ticker`, `duration_ms`, `status`).

Nunca se loggean tokens ni API keys. `redact()` es la red de seguridad para el
caso en que un mensaje de error de un proveedor traiga la URL completa con el
token adentro — pasa con IBKR Flex, cuyo endpoint recibe el token por query
string.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})

# Valores que jamás deben aparecer en un log, tomados del entorno en caliente
# para que rotar una key no exija reiniciar el proceso.
_SECRET_ENV_KEYS = (
    "IBKR_FLEX_TOKEN",
    "ALPHA_VANTAGE_KEY",
    "FRED_API_KEY",
    "DEEPSEEK_API_KEY",
    "AI_API_KEY",
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
)

_QUERY_SECRET_RE = re.compile(r"(?i)\b(t|token|apikey|api_key|key)=([^&\s\"']+)")


def redact(text: str) -> str:
    if not text:
        return text
    for env_key in _SECRET_ENV_KEYS:
        value = os.getenv(env_key)
        if value and len(value) >= 8 and value in text:
            text = text.replace(value, f"<{env_key}>")
    return _QUERY_SECRET_RE.sub(r"\1=<redacted>", text)


class LogContext:
    """Agrega campos a todas las líneas emitidas dentro del bloque.

    with LogContext(job_id="scanner-123", provider="yfinance"):
        logger.info("chain fetched", extra={"ticker": "SMR", "duration_ms": 812})
    """

    def __init__(self, **fields: Any):
        self._fields = {k: v for k, v in fields.items() if v is not None}
        self._token = None

    def __enter__(self) -> "LogContext":
        self._token = _context.set({**_context.get(), **self._fields})
        return self

    def __exit__(self, *exc_info) -> None:
        if self._token is not None:
            _context.reset(self._token)


_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        payload.update(_context.get())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        try:
            return json.dumps(payload, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(
                {"ts": payload["ts"], "level": "ERROR", "logger": record.name,
                 "message": "log payload no serializable"}
            )


_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
    # uvicorn trae sus propios handlers con formato propio; se dejan propagar al root.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
