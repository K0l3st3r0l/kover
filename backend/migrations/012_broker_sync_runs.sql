-- Auditoría de corridas del sync IBKR Flex (K7). No reemplaza ninguna tabla
-- existente: transactions/stocks/options se siguen escribiendo por el mismo
-- /confirm que ya usan el CSV y el texto pegado. Esta tabla solo registra
-- qué trajo cada corrida del preview, para poder mirar atrás si algo no
-- cuadra — no hay auto-confirmación todavía (ver
-- wiki/projects/kover/decisions/ibkr-flex-sync.md).
--
-- Deliberadamente sin `external_id` en transactions ni columnas nuevas en
-- stocks/options: el dedupe sigue siendo heurístico (ya corregido para ser
-- bidireccional), no por identificador único del bróker.
CREATE TABLE IF NOT EXISTS broker_sync_runs (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    source              VARCHAR(16) NOT NULL,                    -- TRADES | ACTIVITY | BOTH
    triggered_by        VARCHAR(16) NOT NULL DEFAULT 'MANUAL',   -- MANUAL | SCHEDULED
    status              VARCHAR(16) NOT NULL DEFAULT 'OK',       -- OK | ERROR
    raw_row_count       INTEGER,
    importable_count    INTEGER,
    duplicate_count     INTEGER,
    warning_count       INTEGER,
    position_mismatches JSONB,
    error_message       TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_broker_sync_runs_user ON broker_sync_runs(user_id, started_at DESC);
