"""Persistencia de veredictos del comité AFP (uno por día calendario UTC)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from ..database import SessionLocal

logger = logging.getLogger(__name__)


def _as_of_date(generated_at: str) -> Optional[str]:
    if not generated_at:
        return None
    try:
        stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        return stamp.date().isoformat()
    except Exception:
        return generated_at[:10] if len(generated_at) >= 10 else None


def _compact_context(ctx: Optional[dict]) -> Optional[dict]:
    if not isinstance(ctx, dict):
        return None
    keys = (
        "funds",
        "tpm_last",
        "tpm_trend_3m",
        "ipc_avg_3m",
        "imacec_last",
        "cobre_mom30d",
        "dolar_last",
        "dolar_range_60d",
        "horizon_years",
    )
    return {k: ctx[k] for k in keys if k in ctx}


def snapshot_from_committee(result: dict, origin: str = "live") -> Optional[dict]:
    generated_at = result.get("generated_at")
    as_of = _as_of_date(generated_at or "")
    if not as_of or not generated_at:
        return None
    analysts = []
    for row in result.get("analysts") or []:
        analysts.append({
            "model": row.get("model"),
            "parsed": row.get("parsed"),
            "error": row.get("error"),
        })
    arbiter = result.get("arbiter") or {}
    return {
        "as_of_date": as_of,
        "generated_at": generated_at,
        "provider": result.get("provider"),
        "origin": origin,
        "analysts": analysts,
        "arbiter": {"model": arbiter.get("model"), "parsed": arbiter.get("parsed")},
        "context": _compact_context(result.get("context")),
    }


def upsert_snapshot(result: dict, origin: str = "live") -> None:
    snap = snapshot_from_committee(result, origin=origin)
    if not snap:
        return
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO ai_committee_snapshots
                    (as_of_date, generated_at, provider, origin, analysts, arbiter, context)
                VALUES
                    (:as_of_date, CAST(:generated_at AS timestamptz), :provider, :origin,
                     CAST(:analysts AS jsonb), CAST(:arbiter AS jsonb), CAST(:context AS jsonb))
                ON CONFLICT (as_of_date) DO UPDATE SET
                    generated_at = EXCLUDED.generated_at,
                    provider     = EXCLUDED.provider,
                    origin       = EXCLUDED.origin,
                    analysts     = EXCLUDED.analysts,
                    arbiter      = EXCLUDED.arbiter,
                    context      = COALESCE(EXCLUDED.context, ai_committee_snapshots.context)
                WHERE EXCLUDED.generated_at >= ai_committee_snapshots.generated_at
                """
            ),
            {
                "as_of_date": snap["as_of_date"],
                "generated_at": snap["generated_at"],
                "provider": snap.get("provider"),
                "origin": snap["origin"],
                "analysts": json.dumps(snap["analysts"], ensure_ascii=False),
                "arbiter": json.dumps(snap["arbiter"], ensure_ascii=False),
                "context": json.dumps(snap.get("context"), ensure_ascii=False) if snap.get("context") else None,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("AI committee snapshot persist failed")
    finally:
        db.close()


def list_snapshots() -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT as_of_date, generated_at, provider, origin, analysts, arbiter, context
                FROM ai_committee_snapshots
                ORDER BY as_of_date ASC
                """
            )
        ).mappings().all()
        out = []
        for row in rows:
            as_of = row["as_of_date"]
            generated = row["generated_at"]
            out.append({
                "as_of_date": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
                "generated_at": generated.isoformat() if hasattr(generated, "isoformat") else str(generated),
                "provider": row["provider"],
                "origin": row["origin"],
                "analysts": row["analysts"] or [],
                "arbiter": row["arbiter"] or {},
                "context": row["context"],
            })
        return out
    except Exception:
        logger.exception("AI committee snapshot list failed")
        return []
    finally:
        db.close()
