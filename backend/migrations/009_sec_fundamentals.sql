-- K2 — Fundamentales desde SEC EDGAR.
--
-- Regla que gobierna el diseño: la trazabilidad no se pierde nunca. Cada número
-- que el scanner use para rankear tiene que poder responder de qué tag XBRL, de
-- qué filing y de qué fecha salió.
--
-- `fundamental_snapshots` NUNCA se sobrescribe. Es la base del backtesting sin
-- look-ahead bias: una simulación fechada el 2026-03-01 solo puede leer
-- snapshots con accepted_at <= esa fecha.

CREATE TABLE IF NOT EXISTS sec_filings (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    accession_no  VARCHAR(32) NOT NULL UNIQUE,
    form          VARCHAR(16) NOT NULL,
    filing_date   DATE NOT NULL,
    accepted_at   TIMESTAMPTZ NOT NULL,
    period_end    DATE,
    primary_doc   TEXT,
    is_xbrl       BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_filings_instrument ON sec_filings(instrument_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_filings_form ON sec_filings(instrument_id, form, filing_date DESC);

-- Un mismo período aparece en varios filings con valores distintos (restatements):
-- Ford tiene 231 facts de Revenues para 98 períodos. Se guardan todos con su
-- accepted_at, y quien consulta elige según la fecha de corte.
CREATE TABLE IF NOT EXISTS financial_facts (
    id             SERIAL PRIMARY KEY,
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    metric         VARCHAR(64) NOT NULL,
    source_tag     VARCHAR(128) NOT NULL,
    taxonomy       VARCHAR(32) NOT NULL DEFAULT 'us-gaap',
    value          DOUBLE PRECISION,
    unit           VARCHAR(16),
    form           VARCHAR(16),
    fiscal_year    INTEGER,
    fiscal_period  VARCHAR(8),
    period_start   DATE,
    period_end     DATE,
    frame          VARCHAR(24),
    filing_date    DATE,
    accepted_at    TIMESTAMPTZ,
    accession_no   VARCHAR(32),
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_facts_lookup
    ON financial_facts(instrument_id, metric, period_end DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique
    ON financial_facts(instrument_id, metric, source_tag, period_start, period_end, accession_no);

CREATE TABLE IF NOT EXISTS fundamental_snapshots (
    id                     SERIAL PRIMARY KEY,
    instrument_id          INTEGER NOT NULL REFERENCES instruments(id),
    as_of_date             DATE NOT NULL,
    accepted_at            TIMESTAMPTZ NOT NULL,
    profile                VARCHAR(32) NOT NULL,
    score_status           VARCHAR(32) NOT NULL,
    financial_safety_score DOUBLE PRECISION,

    revenue_ttm            DOUBLE PRECISION,
    revenue_growth_yoy     DOUBLE PRECISION,
    gross_profit_ttm       DOUBLE PRECISION,
    operating_income_ttm   DOUBLE PRECISION,
    net_income_ttm         DOUBLE PRECISION,
    operating_margin       DOUBLE PRECISION,

    cash                   DOUBLE PRECISION,
    current_assets         DOUBLE PRECISION,
    current_liabilities    DOUBLE PRECISION,
    total_assets           DOUBLE PRECISION,
    total_liabilities      DOUBLE PRECISION,
    stockholders_equity    DOUBLE PRECISION,
    short_term_debt        DOUBLE PRECISION,
    long_term_debt         DOUBLE PRECISION,
    total_debt             DOUBLE PRECISION,
    net_debt               DOUBLE PRECISION,

    operating_cf_ttm       DOUBLE PRECISION,
    capex_ttm              DOUBLE PRECISION,
    fcf_ttm                DOUBLE PRECISION,
    fcf_margin             DOUBLE PRECISION,

    current_ratio          DOUBLE PRECISION,
    debt_to_equity         DOUBLE PRECISION,
    shares_outstanding     DOUBLE PRECISION,
    dilution_yoy           DOUBLE PRECISION,
    cash_runway_quarters   DOUBLE PRECISION,

    -- Desglose del score y razones de lo que no se pudo calcular. Sin esto no se
    -- puede responder "¿por qué 67?".
    components             JSONB,
    missing_metrics        JSONB,

    source_filing_id       INTEGER REFERENCES sec_filings(id),
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_unique
    ON fundamental_snapshots(instrument_id, as_of_date);
CREATE INDEX IF NOT EXISTS idx_snapshot_lookup
    ON fundamental_snapshots(instrument_id, accepted_at DESC);

CREATE TABLE IF NOT EXISTS fundamental_risk_flags (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    flag          VARCHAR(48) NOT NULL,
    severity      VARCHAR(16) NOT NULL,      -- REJECT | PENALIZE | INFO
    origin        VARCHAR(16) NOT NULL,      -- METRIC | FILING_TEXT
    filing_id     INTEGER REFERENCES sec_filings(id),
    section       VARCHAR(128),
    text_excerpt  TEXT,
    detail        JSONB,
    detected_at   TIMESTAMPTZ DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_risk_flags_instrument
    ON fundamental_risk_flags(instrument_id, resolved_at, severity);

CREATE TABLE IF NOT EXISTS corporate_events (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    event_type    VARCHAR(32) NOT NULL,
    event_date    DATE NOT NULL,
    confirmed     BOOLEAN DEFAULT FALSE,
    source        VARCHAR(64) NOT NULL,
    detail        JSONB,
    fetched_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_unique
    ON corporate_events(instrument_id, event_type, event_date);
