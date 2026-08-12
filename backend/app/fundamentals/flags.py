"""Hard flags de riesgo fundamental.

Dos orígenes, con reglas distintas:

- **METRIC**: se deducen de los números (runway corto, patrimonio negativo,
  dilución extrema).
- **FILING_TEXT**: se detectan buscando frases determinísticas en el texto del
  filing, y guardan siempre el extracto que las originó.

Restricción dura del proyecto: **una IA nunca crea por sí sola un hard flag
financiero sin evidencia trazable del filing.** Una IA puede resumir un 10-K,
pero el flag lo levanta el matcher determinístico de este módulo, con su cita.

Los flags REJECT vetan al candidato incluso en perfil agresivo. La prima no
compensa un riesgo fundamental crítico: primero la puerta, después el ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models.fundamentals import FlagSeverity, FundamentalRiskFlag
from .metrics import FundamentalMetrics

# Umbrales de veto y penalización.
RUNWAY_REJECT_QUARTERS = 2.0
RUNWAY_PENALIZE_QUARTERS = 6.0
DILUTION_PENALIZE = 0.25
STALE_FILING_DAYS = 200


@dataclass
class DetectedFlag:
    flag: FundamentalRiskFlag
    severity: FlagSeverity
    origin: str  # METRIC | FILING_TEXT
    detail: Optional[dict] = None
    section: Optional[str] = None
    text_excerpt: Optional[str] = None

    @property
    def is_reject(self) -> bool:
        return self.severity == FlagSeverity.REJECT


# ── Flags métricos ────────────────────────────────────────────────────────────

def detect_metric_flags(metrics: FundamentalMetrics, filing_age_days: Optional[int] = None) -> list[DetectedFlag]:
    flags: list[DetectedFlag] = []

    runway = metrics.cash_runway_quarters
    if runway is not None:
        if runway < RUNWAY_REJECT_QUARTERS:
            flags.append(
                DetectedFlag(
                    FundamentalRiskFlag.SEVERE_LIQUIDITY_RISK,
                    FlagSeverity.REJECT,
                    "METRIC",
                    {"cash_runway_quarters": round(runway, 2), "threshold": RUNWAY_REJECT_QUARTERS},
                )
            )
        elif runway < RUNWAY_PENALIZE_QUARTERS:
            flags.append(
                DetectedFlag(
                    FundamentalRiskFlag.SEVERE_LIQUIDITY_RISK,
                    FlagSeverity.PENALIZE,
                    "METRIC",
                    {"cash_runway_quarters": round(runway, 2), "threshold": RUNWAY_PENALIZE_QUARTERS},
                )
            )

    equity = metrics.stockholders_equity
    if equity is not None and equity < 0:
        flags.append(
            DetectedFlag(
                FundamentalRiskFlag.NEGATIVE_EQUITY,
                FlagSeverity.PENALIZE,
                "METRIC",
                {"stockholders_equity": equity},
            )
        )

    dilution = metrics.dilution_yoy
    if dilution is not None and dilution > DILUTION_PENALIZE:
        flags.append(
            DetectedFlag(
                FundamentalRiskFlag.EXTREME_DILUTION,
                FlagSeverity.PENALIZE,
                "METRIC",
                {"dilution_yoy": round(dilution, 4), "threshold": DILUTION_PENALIZE},
            )
        )

    if filing_age_days is not None and filing_age_days > STALE_FILING_DAYS:
        # Una empresa al día presenta cada trimestre. Pasar 200 días sin filing
        # sugiere atraso, y un atraso sostenido suele preceder problemas.
        flags.append(
            DetectedFlag(
                FundamentalRiskFlag.STALE_FILINGS,
                FlagSeverity.PENALIZE,
                "METRIC",
                {"days_since_last_filing": filing_age_days, "threshold": STALE_FILING_DAYS},
            )
        )

    return flags


# ── Flags de texto ────────────────────────────────────────────────────────────

# Cada patrón es deliberadamente literal. Se prefiere no detectar a inventar: un
# falso positivo veta una empresa sana y el usuario nunca ve la oportunidad.
TEXT_PATTERNS: list[tuple[FundamentalRiskFlag, FlagSeverity, str]] = [
    # El posesivo varía mucho ("the Company's", "our", "its", "the Group's") y
    # los apóstrofes llegan como entidades HTML. Se acepta cualquier relleno
    # corto sin punto entre las dos partes que sí son específicas: "substantial
    # doubt" y "ability to continue as a going concern". Exigir ambas evita el
    # falso positivo de los 10-K que solo nombran la base contable.
    (FundamentalRiskFlag.GOING_CONCERN, FlagSeverity.REJECT,
     r"substantial doubt[^.]{0,80}?ability to continue as a going concern"),
    (FundamentalRiskFlag.GOING_CONCERN, FlagSeverity.REJECT,
     r"ability to continue as a going concern[^.]{0,80}?substantial doubt"),
    (FundamentalRiskFlag.BANKRUPTCY, FlagSeverity.REJECT,
     r"(?:filed|filing) (?:a )?(?:voluntary )?petitions? (?:for relief )?under chapter (?:7|11)"),
    (FundamentalRiskFlag.BANKRUPTCY, FlagSeverity.REJECT,
     r"commenced (?:voluntary )?chapter (?:7|11) (?:bankruptcy )?(?:cases|proceedings)"),
    (FundamentalRiskFlag.DELISTING_RISK, FlagSeverity.REJECT,
     r"notice(?:d)? of (?:potential )?delisting|face(?:s)? (?:possible )?delisting|subject to delisting"),
    (FundamentalRiskFlag.COVENANT_BREACH, FlagSeverity.PENALIZE,
     r"(?:was|were|are|is) not in compliance with (?:certain |the )?(?:financial )?covenants?"),
    (FundamentalRiskFlag.COVENANT_BREACH, FlagSeverity.PENALIZE,
     r"(?:breach|violation) of (?:a |certain )?(?:financial )?covenants?"),
    (FundamentalRiskFlag.AUDITOR_WARNING, FlagSeverity.PENALIZE,
     r"material weakness(?:es)? in (?:our |the Company's )?internal control"),
    (FundamentalRiskFlag.RESTRUCTURING, FlagSeverity.INFO,
     r"restructuring plan|restructuring charges of"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
EXCERPT_RADIUS = 200


def strip_html(raw: str) -> str:
    """Los filings vienen en HTML/iXBRL; el matcher trabaja sobre texto plano."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#8217;", "'")
        .replace("&#8220;", '"')
        .replace("&#8221;", '"')
    )
    return _WS_RE.sub(" ", text)


def detect_text_flags(filing_text: str, section: Optional[str] = None) -> list[DetectedFlag]:
    """Busca las frases de riesgo y guarda el extracto que las respalda."""
    text = strip_html(filing_text)
    found: dict[FundamentalRiskFlag, DetectedFlag] = {}

    for flag, severity, pattern in TEXT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            continue
        # Si el mismo flag ya se detectó con severidad mayor, se conserva aquella.
        existing = found.get(flag)
        if existing is not None and existing.severity == FlagSeverity.REJECT:
            continue
        start = max(0, match.start() - EXCERPT_RADIUS)
        end = min(len(text), match.end() + EXCERPT_RADIUS)
        found[flag] = DetectedFlag(
            flag=flag,
            severity=severity,
            origin="FILING_TEXT",
            section=section,
            text_excerpt=text[start:end].strip(),
            detail={"matched": match.group(0)[:200]},
        )

    return list(found.values())


def has_reject(flags: list[DetectedFlag]) -> bool:
    return any(f.is_reject for f in flags)


def reject_reasons(flags: list[DetectedFlag]) -> list[str]:
    return [f.flag.value for f in flags if f.is_reject]
