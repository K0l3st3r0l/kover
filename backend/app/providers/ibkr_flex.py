"""Proveedor IBKR Flex Web Service — ejecuciones, efectivo y posiciones.

Fuente única: Activity Statement (`IBKR_FLEX_QUERY_ACTIVITY`), no Trade
Confirmation. Confirmado contra la cuenta real (2026-08-12): la query "Kover
Trade Confirmations" (`IBKR_FLEX_QUERY_TRADES`) está configurada con
period="Today" — sirve para el futuro job incremental diario (K7.2), pero no
tiene el historial que este proveedor necesita para reconciliar contra lo ya
importado por CSV. El Activity Statement (period="Last365CalendarDays") sí lo
tiene, y además ya incluye asignaciones (notes="A") y expiraciones
(notes="Ep", transactionType="BookTrade", precio y comisión en cero) dentro
de la misma sección Trades — no existe una sección EAE separada que parsear.

Gap conocido (ver wiki/projects/kover/decisions/ibkr-flex-sync.md): la Flex
Query "Kover Activity" no tiene habilitada la sección de detalle "Transfers"
(Deposits & Withdrawals) — un retiro real de -$1200 del 2026-05-11 solo
aparece como total agregado en CashReport, no como fila individual. Hay que
habilitarla en IBKR Client Portal → Reports → Flex Queries antes de que el
sync capture depósitos o retiros nuevos.

Flujo verificado: SendRequest → ReferenceCode → GetStatement, reintentando en
ErrorCode 1019 ("statement generando"). Un XML vacío o un Status distinto de
Success nunca se interpreta como "sin datos" — ver `_get_statement`: un
preview vacío por fallo silencioso es indistinguible de "ya está todo
sincronizado" para quien lo usa, y acá se trata de dinero real.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from ..logging_config import get_logger, redact
from .base import BrokerCashTransaction, BrokerExecution, BrokerPositionLot, ProviderError

logger = get_logger(__name__)

SEND_REQUEST_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
GET_STATEMENT_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"
FLEX_VERSION = "3"
STATEMENT_GENERATING_ERROR_CODE = "1019"
POLL_BACKOFF_SECONDS = (5, 5, 10, 10, 20, 20)  # ~70s antes de rendirse
STATEMENT_CACHE_TTL_SECONDS = 120  # evita 3 GetStatement por la misma Activity query
# Flex no reporta timezone explícito en ningún campo (ni AccountInformation ni
# FlexStatement). Se asume la hora local de la cuenta, igual que todo el
# historial ya cargado a mano desde el CSV (que tampoco trae offset).
ACCOUNT_TIMEZONE = "America/New_York"


class IbkrFlexBrokerProvider:
    name = "ibkr_flex"

    def __init__(
        self,
        token: Optional[str] = None,
        query_id_activity: Optional[str] = None,
        query_id_trades: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self._token = token if token is not None else os.getenv("IBKR_FLEX_TOKEN", "")
        self._query_id_activity = (
            query_id_activity if query_id_activity is not None else os.getenv("IBKR_FLEX_QUERY_ACTIVITY", "")
        )
        self._query_id_trades = (
            query_id_trades if query_id_trades is not None else os.getenv("IBKR_FLEX_QUERY_TRADES", "")
        )
        self._session = session or requests.Session()
        self._cache_lock = threading.Lock()
        self._cache: dict[str, tuple[float, str]] = {}  # query_id -> (fetched_monotonic, xml_text)

    def _require_config(self) -> None:
        if not self._token:
            raise ProviderError(self.name, "IBKR_FLEX_TOKEN no configurado", retryable=False)
        if not self._query_id_activity:
            raise ProviderError(self.name, "IBKR_FLEX_QUERY_ACTIVITY no configurado", retryable=False)

    # ── Bajo nivel ────────────────────────────────────────────────────────────

    def _send_request(self, query_id: str) -> str:
        try:
            resp = self._session.get(
                SEND_REQUEST_URL,
                params={"t": self._token, "q": query_id, "v": FLEX_VERSION},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"error de red en SendRequest: {redact(str(exc))}") from exc

        try:
            root = ElementTree.fromstring(resp.text)
        except ElementTree.ParseError as exc:
            raise ProviderError(self.name, f"SendRequest devolvió XML inválido: {exc}") from exc

        status = root.findtext("Status")
        if status != "Success":
            error_code = root.findtext("ErrorCode") or "?"
            error_msg = root.findtext("ErrorMessage") or "sin detalle"
            raise ProviderError(
                self.name, f"SendRequest falló: status={status} code={error_code} {error_msg}", retryable=False
            )

        ref_code = root.findtext("ReferenceCode")
        if not ref_code:
            raise ProviderError(self.name, "SendRequest sin ReferenceCode en la respuesta", retryable=False)
        return ref_code

    def _get_statement(self, reference_code: str) -> str:
        last_error_code = None
        for attempt, wait in enumerate((0,) + POLL_BACKOFF_SECONDS):
            if wait:
                time.sleep(wait)
            try:
                resp = self._session.get(
                    GET_STATEMENT_URL,
                    params={"q": reference_code, "t": self._token, "v": FLEX_VERSION},
                    timeout=60,
                )
            except requests.RequestException as exc:
                raise ProviderError(self.name, f"error de red en GetStatement: {redact(str(exc))}") from exc

            text = resp.text
            if "<FlexQueryResponse" in text:
                return text

            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError as exc:
                raise ProviderError(self.name, f"GetStatement devolvió XML inválido: {exc}") from exc

            error_code = root.findtext("ErrorCode")
            last_error_code = error_code
            if error_code == STATEMENT_GENERATING_ERROR_CODE:
                logger.info("statement generando, reintentando", extra={"attempt": attempt + 1})
                continue

            # Cualquier otro código (o Status=Fail) es un fallo real, nunca "sin
            # datos" — ver docstring del módulo.
            error_msg = root.findtext("ErrorMessage") or "sin detalle"
            raise ProviderError(
                self.name, f"GetStatement falló: ErrorCode {error_code} — {error_msg}", retryable=False
            )

        raise ProviderError(
            self.name,
            f"GetStatement no entregó el statement tras {len(POLL_BACKOFF_SECONDS) + 1} intentos "
            f"(último ErrorCode: {last_error_code})",
        )

    def _fetch_statement_xml(self, query_id: str) -> str:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(query_id)
            if cached and (now - cached[0]) < STATEMENT_CACHE_TTL_SECONDS:
                return cached[1]

        self._require_config()
        ref_code = self._send_request(query_id)
        xml_text = self._get_statement(ref_code)

        with self._cache_lock:
            self._cache[query_id] = (time.monotonic(), xml_text)
        return xml_text

    def _fetch_activity_xml(self) -> str:
        return self._fetch_statement_xml(self._query_id_activity)

    # ── Parseo XML → dataclasses ────────────────────────────────────────────

    @staticmethod
    def _parse_flex_datetime(value: str) -> tuple[datetime, str]:
        """'20260227;130913' (o solo '20260227') -> (UTC-aware, timestamp original)."""
        if ";" in value:
            local_naive = datetime.strptime(value, "%Y%m%d;%H%M%S")
        else:
            local_naive = datetime.strptime(value, "%Y%m%d")
        local_aware = local_naive.replace(tzinfo=ZoneInfo(ACCOUNT_TIMEZONE))
        return local_aware.astimezone(timezone.utc), value

    @staticmethod
    def _parse_flex_date(value: str) -> Optional[date]:
        if not value:
            return None
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))

    def _parse_activity_trades(self, xml_text: str) -> list[BrokerExecution]:
        root = ElementTree.fromstring(xml_text)
        executions: list[BrokerExecution] = []
        for el in root.iter("Trade"):
            asset_category = el.get("assetCategory", "")
            if asset_category not in ("STK", "OPT"):
                continue  # Forex, Bonds, etc. — fuera de alcance, igual que parse_ib_csv

            # Filas SYMBOL_SUMMARY/ORDER, si la query alguna vez las incluyera,
            # duplicarían lo que ya cuentan las filas EXECUTION individuales.
            if el.get("levelOfDetail") != "EXECUTION":
                continue

            notes = el.get("notes", "") or ""
            codes = [c.strip() for c in notes.split(";") if c.strip()]
            if "Ca" in codes:
                continue  # cancelación/corrección — igual que parse_ib_csv

            quantity_signed = float(el.get("quantity") or 0)
            executed_at_utc, original_ts = self._parse_flex_datetime(el.get("dateTime", ""))
            strike = el.get("strike")
            multiplier = el.get("multiplier")
            conid = el.get("conid")

            executions.append(
                BrokerExecution(
                    external_id=el.get("transactionID", ""),
                    account_id=el.get("accountId", ""),
                    symbol=el.get("symbol", ""),
                    asset_category=asset_category,
                    side="BUY" if quantity_signed > 0 else "SELL",
                    quantity=abs(quantity_signed),
                    price=float(el.get("tradePrice") or 0),
                    proceeds=float(el.get("proceeds") or 0),
                    commission=float(el.get("ibCommission") or 0),
                    executed_at_utc=executed_at_utc,
                    source_timezone=ACCOUNT_TIMEZONE,
                    original_timestamp=original_ts,
                    codes=codes,
                    underlying=el.get("underlyingSymbol") or None,
                    strike=float(strike) if strike else None,
                    expiration=self._parse_flex_date(el.get("expiry", "")),
                    right=el.get("putCall") or None,
                    multiplier=int(multiplier) if multiplier else None,
                    conid=int(conid) if conid else None,
                    raw=dict(el.attrib),
                )
            )
        return executions

    def _parse_activity_cash_transactions(self, xml_text: str) -> list[BrokerCashTransaction]:
        root = ElementTree.fromstring(xml_text)
        results: list[BrokerCashTransaction] = []
        for el in root.iter("CashTransaction"):
            executed_at_utc = None
            dt_raw = el.get("dateTime", "")
            if dt_raw:
                executed_at_utc, _ = self._parse_flex_datetime(dt_raw)

            results.append(
                BrokerCashTransaction(
                    external_id=el.get("transactionID") or None,
                    account_id=el.get("accountId", ""),
                    type=el.get("type", ""),
                    symbol=el.get("symbol") or None,
                    amount=float(el.get("amount") or 0),
                    settle_date=self._parse_flex_date(el.get("settleDate", "")),
                    executed_at_utc=executed_at_utc,
                    description=el.get("description") or None,
                    raw=dict(el.attrib),
                )
            )
        return results

    def _parse_activity_open_positions(self, xml_text: str) -> list[BrokerPositionLot]:
        root = ElementTree.fromstring(xml_text)
        results: list[BrokerPositionLot] = []
        for el in root.iter("OpenPosition"):
            open_dt = None
            open_raw = el.get("openDateTime", "")
            if open_raw:
                open_dt, _ = self._parse_flex_datetime(open_raw)
            cost_basis_price = el.get("costBasisPrice")
            cost_basis_money = el.get("costBasisMoney")
            mark_price = el.get("markPrice")

            results.append(
                BrokerPositionLot(
                    account_id=el.get("accountId", ""),
                    symbol=el.get("symbol", ""),
                    asset_category=el.get("assetCategory", ""),
                    quantity=float(el.get("position") or 0),
                    cost_basis_price=float(cost_basis_price) if cost_basis_price else None,
                    cost_basis_money=float(cost_basis_money) if cost_basis_money else None,
                    open_date=open_dt,
                    mark_price=float(mark_price) if mark_price else None,
                )
            )
        return results

    # ── BrokerProvider Protocol ─────────────────────────────────────────────

    def get_executions(self) -> list[BrokerExecution]:
        return self._parse_activity_trades(self._fetch_activity_xml())

    def get_cash_transactions(self) -> list[BrokerCashTransaction]:
        return self._parse_activity_cash_transactions(self._fetch_activity_xml())

    def get_position_lots(self) -> list[BrokerPositionLot]:
        return self._parse_activity_open_positions(self._fetch_activity_xml())

    def probe(self) -> dict[str, Any]:
        """Health check para provider_status.

        No corre un ciclo SendRequest/GetStatement completo — Flex penaliza el
        polling agresivo de la misma query, y este probe corre cada pocos
        minutos desde el scheduler. Solo valida que la configuración esté
        presente.
        """
        self._require_config()
        return {
            "configured": True,
            "query_activity_set": bool(self._query_id_activity),
            "query_trades_set": bool(self._query_id_trades),
        }
