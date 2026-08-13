-- Candidatos de covered call del scanner (K4).
--
-- Se guardan solo los tres mejores contratos por símbolo (BALANCED / PREMIUM /
-- UPSIDE), no la cadena completa: la cadena de un símbolo son ~900 contratos y
-- 306 símbolos serían ~275.000 filas por corrida de datos que caducan en
-- minutos. Lo que hace falta persistir es el resultado, no la materia prima —
-- la cadena se vuelve a pedir a CBOE cuando se necesite (0,3s por símbolo).
--
-- Cada corrida reemplaza a la anterior por símbolo. No es histórico: una prima
-- de ayer no sirve para decidir hoy, y para backtesting el plan contempla otra
-- estructura (ver docs/COVERED_CALL_SCANNER_PLAN.md §21).
--
-- CREATE TABLE IF NOT EXISTS sin excepción: `Base.metadata.create_all()` en
-- app/main.py corre antes que las migraciones de deploy.sh y gana la carrera.
-- Ver wiki/projects/kover/decisions/sql-migrations-runner.md.
CREATE TABLE IF NOT EXISTS covered_call_candidates (
    id                            SERIAL PRIMARY KEY,
    instrument_id                 INTEGER NOT NULL REFERENCES instruments(id),
    pick_type                     VARCHAR(16) NOT NULL,      -- BALANCED | PREMIUM | UPSIDE
    scanned_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    quote_as_of                   TIMESTAMPTZ,               -- timestamp que reporta CBOE (~15 min de delay)

    underlying_price              NUMERIC(18,6),
    stock_ask                     NUMERIC(18,6),

    occ_symbol                    VARCHAR(32) NOT NULL,
    expiration                    DATE NOT NULL,
    strike                        NUMERIC(18,6) NOT NULL,
    dte                           INTEGER NOT NULL,

    call_bid                      NUMERIC(18,6),
    call_ask                      NUMERIC(18,6),
    spread_pct                    NUMERIC(10,6),
    delta                         NUMERIC(10,6),
    implied_volatility            NUMERIC(10,6),
    volume                        INTEGER,
    open_interest                 INTEGER,

    premium_total                 NUMERIC(18,2),
    premium_yield                 NUMERIC(12,6),
    annualized_premium_yield      NUMERIC(12,6),
    return_if_assigned            NUMERIC(12,6),
    annualized_return_if_assigned NUMERIC(12,6),
    downside_protection           NUMERIC(12,6),
    breakeven                     NUMERIC(18,6),
    moneyness                     NUMERIC(12,6),

    liquidity_score               NUMERIC(6,2),
    liquidity_components          JSONB,

    -- Copia de los dos scores al momento del escaneo. Denormalizado a
    -- propósito: el ranking los necesita en cada fila y el snapshot fundamental
    -- puede cambiar entre corridas — guardarlos acá deja la fila explicable por
    -- sí sola, sin reconstruir contra qué se rankeó.
    financial_safety_score        NUMERIC(6,2),
    market_safety_score           NUMERIC(6,2)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cc_candidate_unico
    ON covered_call_candidates(instrument_id, pick_type);
CREATE INDEX IF NOT EXISTS idx_cc_candidate_ranking
    ON covered_call_candidates(pick_type, annualized_premium_yield DESC);
