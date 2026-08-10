-- K1 — Campañas y ciclos de covered call.
--
-- Ambas tablas son DERIVADAS de transactions + options: las construye
-- campaigns/builder.py igual que rebuild_positions reconstruye las posiciones.
-- Se pueden borrar y regenerar completas sin perder información, lo que permite
-- iterar el algoritmo de agrupación sin migraciones destructivas.
--
-- Una campaign es la vida completa de un bloque de acciones (compra → N calls →
-- assignment o venta). Un cycle es una call individual vendida contra ellas.
-- La distinción importa porque el resultado de una call no es el resultado de
-- tener las acciones, y la métrica que manda es la segunda.

CREATE TABLE IF NOT EXISTS campaigns (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    ticker              VARCHAR(16) NOT NULL,
    instrument_id       INTEGER REFERENCES instruments(id),
    status              VARCHAR(32) NOT NULL,
    shares              DOUBLE PRECISION NOT NULL DEFAULT 0,
    shares_peak         DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- NULL = desconocido, no cero. Pasa cuando el histórico importado empieza
    -- después de la compra original: hay ventas sin compra que las respalde.
    stock_cost_basis    DOUBLE PRECISION,
    stock_invested      DOUBLE PRECISION,
    cost_basis_status   VARCHAR(32) NOT NULL DEFAULT 'KNOWN',
    opened_at           TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ,
    close_reason        VARCHAR(32),

    -- Resultados cacheados. No son fuente de verdad: se recalculan en cada
    -- rebuild a partir de las transacciones.
    stock_realized_pnl  DOUBLE PRECISION,
    option_realized_pnl DOUBLE PRECISION,
    option_open_premium DOUBLE PRECISION,
    dividends_total     DOUBLE PRECISION,
    commissions_total   DOUBLE PRECISION,
    total_pnl           DOUBLE PRECISION,
    days_deployed       INTEGER,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_campaigns_user_ticker ON campaigns(user_id, ticker);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(user_id, status);

CREATE TABLE IF NOT EXISTS covered_call_cycles (
    id            SERIAL PRIMARY KEY,
    campaign_id   INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    option_id     INTEGER REFERENCES options(id),
    cycle_num     INTEGER NOT NULL,
    status        VARCHAR(32) NOT NULL,
    ticker        VARCHAR(16) NOT NULL,
    strike        DOUBLE PRECISION NOT NULL,
    contracts     DOUBLE PRECISION NOT NULL,
    expiration    TIMESTAMPTZ NOT NULL,
    opened_at     TIMESTAMPTZ NOT NULL,
    closed_at     TIMESTAMPTZ,

    entry_premium DOUBLE PRECISION NOT NULL,   -- por acción
    exit_premium  DOUBLE PRECISION,            -- por acción
    gross_premium DOUBLE PRECISION,            -- entrada bruta, en dólares
    closing_cost  DOUBLE PRECISION,
    commissions   DOUBLE PRECISION DEFAULT 0,
    realized_pnl  DOUBLE PRECISION,
    open_premium  DOUBLE PRECISION,

    -- Redondeados al tick del contrato: asumir $0.01 universal produce targets
    -- que no son precios válidos para enviar como orden.
    min_tick      DOUBLE PRECISION DEFAULT 0.01,
    tp70_price    DOUBLE PRECISION,
    tp75_price    DOUBLE PRECISION,
    tp80_price    DOUBLE PRECISION,

    premium_source VARCHAR(32),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cycles_campaign ON covered_call_cycles(campaign_id, cycle_num);
CREATE INDEX IF NOT EXISTS idx_cycles_option ON covered_call_cycles(option_id);

CREATE TABLE IF NOT EXISTS campaign_events (
    id          SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    cycle_id    INTEGER REFERENCES covered_call_cycles(id) ON DELETE CASCADE,
    event_type  VARCHAR(48) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    payload     JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaign_events ON campaign_events(campaign_id, occurred_at);
