-- K3: universo optionable + riesgo de mercado.
-- Ver docs/COVERED_CALL_SCANNER_PLAN.md secciones 5 y 26.
--
-- Idempotente a propósito: `Base.metadata.create_all()` corre al arrancar el
-- backend, ANTES de que este script se ejecute (deploy.sh hace `up -d` y
-- recién después `run_migrations.py`). Si el modelo SQLAlchemy ya creó las
-- tablas nuevas, un CREATE TABLE liso choca y aborta todo el archivo —incluidas
-- las ALTER TABLE de más abajo, porque psycopg2 corre el script completo como
-- una única transacción implícita. IF NOT EXISTS lo hace seguro sin importar
-- el orden real de arranque.

CREATE TABLE IF NOT EXISTS stock_daily_bars (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    bar_date      DATE NOT NULL,
    open          NUMERIC(18,6),
    high          NUMERIC(18,6),
    low           NUMERIC(18,6),
    close         NUMERIC(18,6),
    volume        BIGINT,
    source        VARCHAR(32) NOT NULL,
    UNIQUE (instrument_id, bar_date)
);
CREATE INDEX IF NOT EXISTS idx_stock_daily_bars_instrument ON stock_daily_bars(instrument_id, bar_date DESC);

CREATE TABLE IF NOT EXISTS market_risk_snapshots (
    id                   SERIAL PRIMARY KEY,
    instrument_id        INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    as_of_date           DATE NOT NULL,
    price                NUMERIC(18,6),
    avg_daily_volume_20  BIGINT,
    avg_dollar_volume_20 NUMERIC(24,2),
    atr14                NUMERIC(18,6),
    atr_pct              NUMERIC(10,6),
    realized_vol_20      NUMERIC(10,6),
    realized_vol_60      NUMERIC(10,6),
    return_5d            NUMERIC(10,6),
    return_20d           NUMERIC(10,6),
    max_drawdown_30d     NUMERIC(10,6),
    max_drawdown_90d     NUMERIC(10,6),
    gap_frequency        NUMERIC(10,6),
    worst_day_20d        NUMERIC(10,6),
    market_safety_score  NUMERIC(6,2),
    components           JSONB,
    bars_used            INTEGER,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (instrument_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_market_risk_instrument ON market_risk_snapshots(instrument_id, as_of_date DESC);

-- Stage 1 del scanner: por qué cada instrumento entró o se descartó del
-- universo optionable $10-20. Se sobrescribe en cada corrida (no es
-- histórico como fundamental_snapshots): el universo de hoy es lo único que
-- importa para decidir qué escanear después.
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS universe_stage VARCHAR(32);
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS universe_rejected_reason VARCHAR(64);
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS universe_checked_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_instruments_universe_stage ON instruments(universe_stage);
