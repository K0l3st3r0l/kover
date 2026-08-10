-- K0 — Fundaciones del scanner de covered calls.
-- Instrumentos canónicos, trazabilidad de datos, settings y estado de proveedores.
-- Idempotente: el runner puede reejecutarla y `Base.metadata.create_all` puede
-- haber creado las tablas antes desde los modelos SQLAlchemy.
--
-- Nota de tipos: se usa DOUBLE PRECISION y no NUMERIC para el dinero, por
-- consistencia con stocks/options/transactions. Mezclar Decimal y float en los
-- mismos cálculos es peor que un tipo uniforme subóptimo.

CREATE TABLE IF NOT EXISTS instruments (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(16) NOT NULL UNIQUE,
    name            VARCHAR(255),
    exchange        VARCHAR(32),
    currency        VARCHAR(8) DEFAULT 'USD',
    ibkr_conid      INTEGER,
    sec_cik         VARCHAR(16),
    sector          VARCHAR(128),
    industry        VARCHAR(128),
    instrument_type VARCHAR(32) DEFAULT 'STOCK',
    is_optionable   BOOLEAN,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_instruments_cik ON instruments(sec_cik);
CREATE INDEX IF NOT EXISTS idx_instruments_conid ON instruments(ibkr_conid);

-- Todo dato mostrado al usuario tiene que poder responder de dónde salió y de
-- cuándo es. Sin esto un precio de hace 3 horas se ve igual que uno fresco.
CREATE TABLE IF NOT EXISTS data_provenance (
    id          SERIAL PRIMARY KEY,
    entity_type VARCHAR(64) NOT NULL,
    entity_key  VARCHAR(128) NOT NULL,
    source      VARCHAR(64) NOT NULL,
    as_of       TIMESTAMPTZ NOT NULL,
    fetched_at  TIMESTAMPTZ DEFAULT NOW(),
    is_stale    BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_provenance_lookup
    ON data_provenance(entity_type, entity_key, fetched_at DESC);

-- user_id NULL = setting global (universo, umbrales del scanner).
CREATE TABLE IF NOT EXISTS app_settings (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER REFERENCES users(id),
    key        VARCHAR(128) NOT NULL,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- UNIQUE con user_id NULL no funciona en Postgres: dos filas con NULL no
-- colisionan. Se usan dos índices parciales.
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_settings_user_key
    ON app_settings(user_id, key) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_settings_global_key
    ON app_settings(key) WHERE user_id IS NULL;

CREATE TABLE IF NOT EXISTS provider_status (
    id             SERIAL PRIMARY KEY,
    provider       VARCHAR(64) NOT NULL UNIQUE,
    status         VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    last_success   TIMESTAMPTZ,
    last_attempt   TIMESTAMPTZ,
    last_error     TEXT,
    last_error_at  TIMESTAMPTZ,
    consecutive_errors INTEGER DEFAULT 0,
    detail         JSONB,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO provider_status (provider, status)
VALUES ('yfinance', 'UNKNOWN'),
       ('sec_edgar', 'UNKNOWN'),
       ('alpha_vantage', 'UNKNOWN'),
       ('ibkr_flex', 'UNKNOWN')
ON CONFLICT (provider) DO NOTHING;
