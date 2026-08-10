# Covered Call Scanner & Portfolio Manager — Plan adaptado a Kover

**Versión:** 1.0 (adaptación del plan genérico v1.0)
**Fecha:** 2026-08-09
**Proyecto:** `/root/apps/kover`
**Estado:** aprobado para ejecución incremental

---

## 0. Qué cambia respecto al plan original

El plan original asumía un proyecto nuevo con stack Node (pnpm monorepo, Fastify, Prisma, BullMQ). Kover ya existe con FastAPI + SQLAlchemy + React/Vite/Tailwind y tiene construido cerca del 40% del alcance (import IBKR, ledger de primas, ciclos de covered call, métricas fiscales, calculadora CC).

**Se conserva el dominio completo. Se descarta el stack.**

| Plan original | Kover |
|---|---|
| pnpm workspaces + `packages/*` | paquetes Python en `backend/app/*` |
| Fastify + Zod | FastAPI + Pydantic (ya existe) |
| Prisma | SQLAlchemy + migraciones SQL numeradas (`run_migrations.py`) |
| BullMQ + Redis + contenedor `worker` | APScheduler en proceso (precedente: `ai_committee_background_loop`) |
| Pino | `logging` stdlib con formatter JSON |
| React/TS/Vite/Tailwind/TanStack Query | idéntico, ya instalado |
| IBKR Web API como fuente primaria | yfinance (fase K1–K6) → IBKR Flex (K7) → IBKR Web API (K9) |

Redis y un contenedor `worker` separado no se construyen en v1. El universo real (acciones optionables US$10–20 con liquidez) son ~200–400 tickers; APScheduler + caché en Postgres alcanza. La arquitectura de jobs se escribe desacoplada para poder mover a Redis/RQ sin reescribir la lógica.

### Decisiones tomadas

1. **Se implementa dentro de kover**, no como proyecto aparte. El portfolio real vive en esa DB y el import IBKR ya está validado contra el extracto histórico.
2. **Datos de mercado vía yfinance en v1.** IBKR Web API requiere Client Portal Gateway con sesión autenticada — se evalúa por separado. IBKR Flex Web Service (token + query ID, HTTP puro, sin gateway) entra en K7 para reconciliación.
3. **Fundamentales y scanner son datos globales**, compartidos entre usuarios. Campaigns, cycles, alertas y settings son por usuario.
4. **Greeks se calculan localmente** con Black-Scholes. yfinance no entrega Delta.

---

## 1. Objetivo

Incorporar a Kover dos capacidades nuevas:

**A. Escaneo de opciones** — identificar, rankear y explicar oportunidades de covered call sobre acciones US con precio entre US$10 y US$20, optimizando calidad fundamental, riesgo de mercado, liquidez del subyacente, liquidez de la opción, spread, prima, Delta, DTE, IV, retorno en assignment, riesgo de eventos y eficiencia de capital.

**B. Seguimiento de operativa** — gestionar el ciclo de vida completo de cada posición: compra de acciones → venta de call → señal de recompra al 75/80% de prima capturada → liberación de acciones → nueva búsqueda, o assignment → liberación de capital → nueva búsqueda.

La aplicación es una herramienta de **análisis, seguimiento y decisión**. No ejecuta órdenes en v1.

### Filosofía de la estrategia

1. Comprar/mantener 100 acciones.
2. Vender una call cubierta.
3. Si la opción pierde 75–80% de su valor rápido: recomprar, realizar la prima, liberar las acciones, volver a escanear.
4. Si el subyacente supera el strike: no defender obligatoriamente; aceptar assignment si el retorno del ciclo es satisfactorio.
5. Tras el assignment: liberar capital, reejecutar el scanner, seleccionar el mejor candidato.
6. **El riesgo principal es la caída del subyacente, no el assignment.**

---

## 2. Lo que Kover ya tiene (no rehacer)

| Componente | Ubicación | Estado |
|---|---|---|
| Docker Compose + Postgres + migraciones | `docker-compose.yml`, `backend/run_migrations.py` | Listo |
| Import IBKR (CSV + pegado manual, dedupe, rebuild) | `app/api/import_ib.py` (1583 líneas) | Listo |
| Modelo Stock / Option / Transaction | `app/models/` | Base, se extiende |
| Ledger canónico de primas | `app/services/premium_ledger.py` | Listo |
| Ciclos CC con anualizado | `app/api/analytics.py:753` | Se migra a `campaigns` |
| Matemática CC / CSP / wheel | `app/api/calculator.py` | Se reutiliza |
| Cadenas de opciones yfinance | `app/market/market_data.py:425` | Se endurece |
| Multi-fuente de precios con fallback | `app/market/market_data.py` | Se le agrega provenance |
| Cash ledger con ancla | `app/services/cash_ledger.py` | Listo |
| Métricas fiscales CL | `app/api/fiscal.py` | Listo |
| Watchlist con S&P 500 | `app/api/watchlist.py` | Listo |
| Frontend con 15 páginas, auth, dark mode | `frontend/src/` | Se extiende |

**Las Fases 0 y 1 del plan original están cubiertas.** El plan de kover arranca en lo que aquí se llama K0.

---

## 3. Arquitectura

```
                    ┌──────────────────┐
                    │  React (Vite)    │
                    │  /scanner        │
                    │  /campaigns      │
                    └────────┬─────────┘
                             │ axios + TanStack Query
                             ▼
                    ┌──────────────────┐
                    │   FastAPI        │
                    │   kover-backend  │
                    └────────┬─────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   PostgreSQL         APScheduler          Providers layer
   (kover-db)         (in-process)                │
                             │        ┌───────────┼───────────┐
                             │        ▼           ▼           ▼
                             │    yfinance    SEC EDGAR   IBKR Flex
                             │    (quotes,    (XBRL,      (recon.
                             │     chains)     filings)     K7)
                             ▼
                      jobs/scheduler.py
                      ├── universe_refresh
                      ├── fundamentals_refresh
                      ├── market_risk_refresh
                      ├── scanner_run
                      ├── position_monitor
                      └── flex_sync (K7)
```

**Regla de acoplamiento:** la lógica de scanner y scoring depende de Protocols en `app/providers/base.py`, nunca de yfinance ni de SEC directamente. Cambiar a IBKR debe ser cambiar una implementación, no la lógica.

### Interfaces de proveedor

```python
# app/providers/base.py
class MarketDataProvider(Protocol): ...
class OptionDataProvider(Protocol): ...
class FundamentalsProvider(Protocol): ...
class CorporateEventsProvider(Protocol): ...
class BrokerProvider(Protocol): ...
class HistoricalMarketDataProvider(Protocol): ...
class HistoricalOptionDataProvider(Protocol): ...
```

Implementaciones v1:

```
YFinanceMarketDataProvider
YFinanceOptionDataProvider
SecEdgarFundamentalsProvider
AlphaVantageEventsProvider     (ALPHA_VANTAGE_KEY ya está en .env)
IbkrFlexBrokerProvider         (K7)
```

---

## 4. Estructura de módulos nueva

```
backend/app/
├── providers/
│   ├── base.py                 # Protocols + dataclasses de respuesta
│   ├── yfinance_market.py
│   ├── yfinance_options.py
│   ├── sec_edgar.py            # rate limit 5 rps + User-Agent obligatorio
│   ├── alpha_vantage_events.py
│   └── ibkr_flex.py            # K7
│
├── options_math/
│   ├── greeks.py               # Black-Scholes (math.erf, sin scipy)
│   ├── covered_call.py         # premium yield, RIA, break-even, buffer, EM
│   └── ticks.py                # calculate_target_price con redondeo a tick
│
├── fundamentals/
│   ├── normalizer.py           # XBRL aliases → métricas canónicas
│   ├── metrics.py              # current ratio, net debt, FCF, runway, dilución
│   ├── profiles.py             # FundamentalProfile
│   ├── flags.py                # hard flags + análisis textual determinístico
│   └── score.py                # Financial Safety Score 0–100
│
├── scanner/
│   ├── universe.py             # Stage 1
│   ├── market_risk.py          # Stage 3 — ATR, vol realizada, drawdown
│   ├── option_scan.py          # Stage 4 — cadenas + contratos
│   ├── profiles.py             # Conservador / Balanceado / Agresivo
│   └── funnel.py               # orquestador, escribe scanner_runs
│
├── scoring/
│   ├── percentiles.py          # winsorize + percentil dentro del run
│   ├── cc_opportunity.py
│   ├── market_safety.py
│   └── final.py                # Final Score + penalizaciones
│
├── campaigns/
│   ├── builder.py              # deriva campaigns/cycles del histórico
│   ├── state.py                # state machines
│   └── metrics.py              # P/L stock vs opciones vs total
│
├── signals/
│   ├── take_profit.py          # TP70/75/80, FAST_TP75
│   └── alerts.py
│
├── backtest/
│   ├── replay_actual.py        # modalidad A
│   ├── replay_exit_policy.py   # modalidad B
│   ├── fill_models.py          # LIMIT_TOUCH / CONSERVATIVE_CLOSE / NBBO
│   └── metrics.py
│
├── jobs/
│   ├── scheduler.py            # APScheduler, registro de jobs
│   └── tasks.py                # funciones invocables también a mano
│
├── health/
│   └── data_health.py          # freshness por proveedor
│
└── api/
    ├── scanner.py
    ├── fundamentals.py
    ├── campaigns.py
    ├── signals.py
    ├── backtests.py
    └── data_health.py
```

### Dependencias nuevas (`requirements.txt`)

```
apscheduler==3.10.4
requests==2.31.0        # ya viene transitivo por yfinance; se declara explícito
```

Y en dev (`requirements-dev.txt`, nuevo — pytest hoy no está en la imagen):

```
pytest==8.0.0
pytest-asyncio==0.23.4
```

**No se agrega scipy.** La normal acumulada de Black-Scholes se implementa con `math.erf`:

```python
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
```

---

## 5. Modelo de datos

Migraciones SQL numeradas continuando desde `006_add_fee_withholding_and_cash_anchor.sql`.

### 007_instruments_and_provenance.sql

```sql
CREATE TABLE instruments (
    id                SERIAL PRIMARY KEY,
    symbol            VARCHAR(16) NOT NULL UNIQUE,
    name              VARCHAR(255),
    exchange          VARCHAR(32),
    currency          VARCHAR(8) DEFAULT 'USD',
    ibkr_conid        INTEGER,
    sec_cik           VARCHAR(16),
    sector            VARCHAR(128),
    industry          VARCHAR(128),
    instrument_type   VARCHAR(32) DEFAULT 'STOCK',
    is_optionable     BOOLEAN,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ
);
CREATE INDEX idx_instruments_cik ON instruments(sec_cik);

-- Provenance de cualquier dato mostrado al usuario
CREATE TABLE data_provenance (
    id            SERIAL PRIMARY KEY,
    entity_type   VARCHAR(64) NOT NULL,   -- 'stock_quote','option_quote','fundamental'
    entity_key    VARCHAR(128) NOT NULL,
    source        VARCHAR(64) NOT NULL,   -- 'yfinance','yahoo_v8','sec_edgar','flex'
    as_of         TIMESTAMPTZ NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    is_stale      BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_provenance_lookup ON data_provenance(entity_type, entity_key, fetched_at DESC);

CREATE TABLE app_settings (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    key         VARCHAR(128) NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, key)
);

CREATE TABLE provider_status (
    provider      VARCHAR(64) PRIMARY KEY,
    status        VARCHAR(32) NOT NULL,
    last_success  TIMESTAMPTZ,
    last_error    TEXT,
    last_error_at TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### 008_campaigns_and_cycles.sql

```sql
CREATE TABLE campaigns (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    ticker              VARCHAR(16) NOT NULL,
    instrument_id       INTEGER REFERENCES instruments(id),
    status              VARCHAR(32) NOT NULL,  -- ver state machine §7
    shares              NUMERIC(18,4) NOT NULL,
    stock_cost_basis    NUMERIC(18,6) NOT NULL,
    opened_at           TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ,
    close_reason        VARCHAR(32),           -- ASSIGNED / STOCK_SALE / MANUAL
    -- resultados (se recalculan, no son fuente de verdad)
    stock_realized_pnl  NUMERIC(18,2),
    option_realized_pnl NUMERIC(18,2),
    dividends_total     NUMERIC(18,2),
    commissions_total   NUMERIC(18,2),
    total_pnl           NUMERIC(18,2),
    days_deployed       INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ
);
CREATE INDEX idx_campaigns_user_ticker ON campaigns(user_id, ticker);

CREATE TABLE covered_call_cycles (
    id                SERIAL PRIMARY KEY,
    campaign_id       INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    option_id         INTEGER REFERENCES options(id),
    cycle_num         INTEGER NOT NULL,
    status            VARCHAR(32) NOT NULL,   -- ver §8
    strike            NUMERIC(18,6) NOT NULL,
    contracts         INTEGER NOT NULL,
    expiration        TIMESTAMPTZ NOT NULL,
    opened_at         TIMESTAMPTZ NOT NULL,
    closed_at         TIMESTAMPTZ,
    entry_premium     NUMERIC(18,6) NOT NULL,  -- por acción
    exit_premium      NUMERIC(18,6),
    commissions       NUMERIC(18,2) DEFAULT 0,
    realized_pnl      NUMERIC(18,2),
    min_tick          NUMERIC(18,6) DEFAULT 0.01,
    tp70_price        NUMERIC(18,6),
    tp75_price        NUMERIC(18,6),
    tp80_price        NUMERIC(18,6),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ
);
CREATE INDEX idx_cycles_campaign ON covered_call_cycles(campaign_id);

CREATE TABLE campaign_events (
    id           SERIAL PRIMARY KEY,
    campaign_id  INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    cycle_id     INTEGER REFERENCES covered_call_cycles(id),
    event_type   VARCHAR(48) NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    payload      JSONB,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
```

`campaigns` y `covered_call_cycles` son **derivadas**: las construye `campaigns/builder.py` a partir de `transactions` + `options`, igual que `rebuild-positions` reconstruye posiciones hoy. Se pueden borrar y regenerar sin perder datos. Eso permite iterar el algoritmo de agrupación sin migraciones destructivas.

### 009_sec_fundamentals.sql

```sql
CREATE TABLE sec_filings (
    id             SERIAL PRIMARY KEY,
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    accession_no   VARCHAR(32) NOT NULL UNIQUE,
    form           VARCHAR(16) NOT NULL,
    filing_date    DATE NOT NULL,
    accepted_at    TIMESTAMPTZ NOT NULL,
    period_end     DATE,
    primary_doc    TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_filings_instrument ON sec_filings(instrument_id, accepted_at DESC);

CREATE TABLE financial_facts (
    id             SERIAL PRIMARY KEY,
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    metric         VARCHAR(64) NOT NULL,     -- métrica canónica
    source_tag     VARCHAR(128) NOT NULL,    -- tag XBRL original
    value          NUMERIC(24,4),
    unit           VARCHAR(16),
    form           VARCHAR(16),
    fiscal_year    INTEGER,
    fiscal_quarter INTEGER,
    period_start   DATE,
    period_end     DATE,
    filing_date    DATE,
    accepted_at    TIMESTAMPTZ NOT NULL,
    filing_id      INTEGER REFERENCES sec_filings(id),
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_facts_lookup ON financial_facts(instrument_id, metric, period_end DESC);

CREATE TABLE fundamental_snapshots (
    id                     SERIAL PRIMARY KEY,
    instrument_id          INTEGER NOT NULL REFERENCES instruments(id),
    as_of_date             DATE NOT NULL,
    accepted_at            TIMESTAMPTZ NOT NULL,  -- clave anti look-ahead
    profile                VARCHAR(32) NOT NULL,
    score_status           VARCHAR(32) NOT NULL,  -- OK / UNSUPPORTED_PROFILE / INSUFFICIENT_DATA
    financial_safety_score NUMERIC(6,2),
    revenue_ttm            NUMERIC(24,4),
    revenue_growth_yoy     NUMERIC(10,6),
    operating_income_ttm   NUMERIC(24,4),
    cash                   NUMERIC(24,4),
    total_debt             NUMERIC(24,4),
    net_debt               NUMERIC(24,4),
    operating_cf_ttm       NUMERIC(24,4),
    capex_ttm              NUMERIC(24,4),
    fcf_ttm                NUMERIC(24,4),
    current_ratio          NUMERIC(10,4),
    shares_outstanding     NUMERIC(24,4),
    dilution_yoy           NUMERIC(10,6),
    cash_runway_quarters   NUMERIC(10,4),
    components             JSONB,     -- desglose del score
    source_filing_id       INTEGER REFERENCES sec_filings(id),
    created_at             TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_snapshot_unique ON fundamental_snapshots(instrument_id, as_of_date);

CREATE TABLE fundamental_risk_flags (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    flag          VARCHAR(48) NOT NULL,
    severity      VARCHAR(16) NOT NULL,     -- REJECT / PENALIZE / INFO
    filing_id     INTEGER REFERENCES sec_filings(id),
    section       VARCHAR(128),
    text_excerpt  TEXT,
    detected_at   TIMESTAMPTZ DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ
);

CREATE TABLE corporate_events (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    event_type    VARCHAR(32) NOT NULL,     -- EARNINGS / DIVIDEND / SPLIT
    event_date    DATE NOT NULL,
    confirmed     BOOLEAN DEFAULT FALSE,
    source        VARCHAR(64) NOT NULL,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (instrument_id, event_type, event_date)
);
```

**Regla:** `fundamental_snapshots` nunca se sobrescribe. Es la base del backtesting sin look-ahead bias.

### 010_market_risk.sql

```sql
CREATE TABLE stock_daily_bars (
    id            SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    bar_date      DATE NOT NULL,
    open          NUMERIC(18,6),
    high          NUMERIC(18,6),
    low           NUMERIC(18,6),
    close         NUMERIC(18,6),
    volume        BIGINT,
    source        VARCHAR(32) NOT NULL,
    UNIQUE (instrument_id, bar_date)
);

CREATE TABLE market_risk_snapshots (
    id                  SERIAL PRIMARY KEY,
    instrument_id       INTEGER NOT NULL REFERENCES instruments(id),
    as_of_date          DATE NOT NULL,
    price               NUMERIC(18,6),
    avg_daily_volume_20 BIGINT,
    avg_dollar_volume_20 NUMERIC(24,2),
    atr14               NUMERIC(18,6),
    atr_pct             NUMERIC(10,6),
    realized_vol_20     NUMERIC(10,6),
    realized_vol_60     NUMERIC(10,6),
    return_5d           NUMERIC(10,6),
    return_20d          NUMERIC(10,6),
    max_drawdown_30d    NUMERIC(10,6),
    max_drawdown_90d    NUMERIC(10,6),
    gap_frequency       NUMERIC(10,6),
    worst_day_20d       NUMERIC(10,6),
    market_safety_score NUMERIC(6,2),
    components          JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (instrument_id, as_of_date)
);
```

### 011_option_contracts.sql

```sql
CREATE TABLE option_contracts (
    id             SERIAL PRIMARY KEY,
    instrument_id  INTEGER NOT NULL REFERENCES instruments(id),
    occ_symbol     VARCHAR(32),
    ibkr_conid     INTEGER,
    expiration     DATE NOT NULL,
    strike         NUMERIC(18,6) NOT NULL,
    right          VARCHAR(4) NOT NULL,      -- C / P
    multiplier     INTEGER DEFAULT 100,
    min_tick       NUMERIC(18,6) DEFAULT 0.01,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ,
    UNIQUE (instrument_id, expiration, strike, right)
);

CREATE TABLE option_quotes (
    id                SERIAL PRIMARY KEY,
    contract_id       INTEGER NOT NULL REFERENCES option_contracts(id),
    quote_at          TIMESTAMPTZ NOT NULL,
    bid               NUMERIC(18,6),
    ask               NUMERIC(18,6),
    last              NUMERIC(18,6),
    volume            INTEGER,
    open_interest     INTEGER,
    implied_vol       NUMERIC(10,6),
    delta             NUMERIC(10,6),
    gamma             NUMERIC(12,8),
    theta             NUMERIC(12,8),
    vega              NUMERIC(12,8),
    greeks_source     VARCHAR(32),    -- 'BS_CALCULATED' / 'PROVIDER'
    source            VARCHAR(32) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_option_quotes_contract ON option_quotes(contract_id, quote_at DESC);
```

### 012_scanner_runs.sql

```sql
CREATE TABLE scanner_runs (
    id                     SERIAL PRIMARY KEY,
    user_id                INTEGER REFERENCES users(id),
    started_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at           TIMESTAMPTZ,
    status                 VARCHAR(24) NOT NULL,   -- RUNNING / OK / FAILED / PARTIAL
    profile                VARCHAR(24) NOT NULL,
    settings               JSONB NOT NULL,
    universe_count         INTEGER,
    price_pass_count       INTEGER,
    liquidity_pass_count   INTEGER,
    fundamental_pass_count INTEGER,
    market_pass_count      INTEGER,
    option_scanned_count   INTEGER,
    candidate_count        INTEGER,
    error                  TEXT
);

CREATE TABLE scanner_candidates (
    id                     SERIAL PRIMARY KEY,
    run_id                 INTEGER NOT NULL REFERENCES scanner_runs(id) ON DELETE CASCADE,
    instrument_id          INTEGER NOT NULL REFERENCES instruments(id),
    ticker                 VARCHAR(16) NOT NULL,
    stage_reached          VARCHAR(32) NOT NULL,
    rejected_reason        VARCHAR(128),
    stock_price            NUMERIC(18,6),
    financial_snapshot_id  INTEGER REFERENCES fundamental_snapshots(id),
    market_snapshot_id     INTEGER REFERENCES market_risk_snapshots(id),
    financial_safety_score NUMERIC(6,2),
    market_safety_score    NUMERIC(6,2),
    final_score            NUMERIC(6,2),
    rank                   INTEGER
);
CREATE INDEX idx_candidates_run ON scanner_candidates(run_id, rank);

CREATE TABLE scanner_contract_candidates (
    id                   SERIAL PRIMARY KEY,
    candidate_id         INTEGER NOT NULL REFERENCES scanner_candidates(id) ON DELETE CASCADE,
    contract_id          INTEGER NOT NULL REFERENCES option_contracts(id),
    quote_id             INTEGER REFERENCES option_quotes(id),
    selection            VARCHAR(24),    -- BEST_BALANCED / BEST_PREMIUM / BEST_UPSIDE / NULL
    dte                  INTEGER,
    delta                NUMERIC(10,6),
    stock_entry          NUMERIC(18,6),  -- ask
    option_entry         NUMERIC(18,6),  -- bid
    capital              NUMERIC(18,2),
    premium_gross        NUMERIC(18,2),
    premium_net          NUMERIC(18,2),
    premium_yield        NUMERIC(10,6),
    break_even           NUMERIC(18,6),
    downside_buffer_pct  NUMERIC(10,6),
    return_if_assigned   NUMERIC(10,6),
    distance_to_strike   NUMERIC(10,6),
    spread_pct           NUMERIC(10,6),
    expected_move        NUMERIC(18,6),
    premium_over_em      NUMERIC(10,6),
    liquidity_score      NUMERIC(6,2),
    cc_opportunity_score NUMERIC(6,2),
    final_score          NUMERIC(6,2)
);

CREATE TABLE score_components (
    id            SERIAL PRIMARY KEY,
    scope         VARCHAR(32) NOT NULL,   -- FINANCIAL / MARKET / CC / FINAL
    ref_table     VARCHAR(48) NOT NULL,
    ref_id        INTEGER NOT NULL,
    component     VARCHAR(64) NOT NULL,
    raw_value     NUMERIC(24,8),
    normalized    NUMERIC(10,6),
    weight        NUMERIC(10,6),
    contribution  NUMERIC(10,6),
    note          TEXT
);
CREATE INDEX idx_score_components_ref ON score_components(ref_table, ref_id);
```

`score_components` es lo que permite responder **"¿por qué tiene 84?"** sin recalcular nada.

### 013_alerts.sql y 014_backtests.sql

```sql
CREATE TABLE alerts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    campaign_id   INTEGER REFERENCES campaigns(id),
    cycle_id      INTEGER REFERENCES covered_call_cycles(id),
    alert_type    VARCHAR(48) NOT NULL,   -- TP80 / FAST_TP75 / EXPIRING_TODAY /
                                          -- POTENTIAL_ASSIGNMENT / EARNINGS_RISK
    severity      VARCHAR(16) NOT NULL,
    message       TEXT NOT NULL,
    payload       JSONB,
    triggered_at  TIMESTAMPTZ DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at   TIMESTAMPTZ
);

CREATE TABLE backtest_runs (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    mode          VARCHAR(32) NOT NULL,   -- ACTUAL_REPLAY / EXIT_POLICY / FULL_STRATEGY
    exit_policy   VARCHAR(32),            -- TP70 / TP75 / TP80 / FAST75_TP80 / EXPIRATION
    fill_model    VARCHAR(32) NOT NULL,
    period_start  DATE,
    period_end    DATE,
    settings      JSONB,
    status        VARCHAR(24),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);

CREATE TABLE backtest_trades (
    id            SERIAL PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    ticker        VARCHAR(16) NOT NULL,
    opened_at     TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    strike        NUMERIC(18,6),
    entry_premium NUMERIC(18,6),
    exit_premium  NUMERIC(18,6),
    exit_reason   VARCHAR(32),
    commissions   NUMERIC(18,2),
    pnl           NUMERIC(18,2)
);

CREATE TABLE backtest_results (
    id            SERIAL PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    metric        VARCHAR(64) NOT NULL,
    value         NUMERIC(24,8),
    detail        JSONB
);
```

---

## 6. Embudo del scanner

### Stage 1 — Universo

Fuente del listado: **Nasdaq Trader symbol directory** (`nasdaqtraded.txt`, HTTP público, trae flag ETF y test issue). Optionabilidad: lista de símbolos con opciones de CBOE. Ambos endpoints deben verificarse al implementar y quedar aislados en `providers/`.

Exclusiones por defecto: OTC, warrants, preferred, closed-end funds, ETFs (salvo setting explícito), no optionables, test issues.

Filtros configurables (guardados en `app_settings`):

```
stock_price_min        = 10
stock_price_max        = 20
avg_daily_volume_min   = 500_000
avg_dollar_volume_min  = 10_000_000
```

Resultado esperado: miles → decenas/cientos.

### Stage 2 — Puerta fundamental

Solo tickers que pasaron Stage 1. Financial Safety Score + hard flags. Ver §9–§11.

### Stage 3 — Riesgo de mercado

Sobre `stock_daily_bars`: ATR14, ATR%, vol realizada 20d/60d, retorno 5d/20d, max drawdown 30d/90d, frecuencia de gaps, peor día en 20d → **Market Safety Score 0–100**.

Financial Safety y Market Safety son independientes. Una empresa puede tener Financial 90 / Market 40 y seguir siendo extremadamente volátil.

### Stage 4 — Cadenas de opciones

**Solo para tickers que pasaron universo + puerta fundamental + puerta de liquidez.** Este es el punto donde el costo de red se dispara: cada expiración de cada ticker es un request a Yahoo.

Presupuesto: 300 tickers × 2 expiraciones = 600 requests por corrida.

**Control de tasa obligatorio** (`providers/yfinance_options.py`):

```
YF_MAX_CONCURRENCY  = 4
YF_MIN_INTERVAL_MS  = 250        # ≈ 4 rps
YF_BACKOFF          = exponencial con jitter, 3 reintentos
YF_CIRCUIT_BREAKER  = 10 fallos consecutivos → job aborta y marca PARTIAL
```

Caché de cadena: 30 min. Caché de quote de acción: 15 s. Si una corrida encuentra la cadena en caché y fresca, no vuelve a pedirla.

Filtros iniciales:

```
DTE_MIN = 5,  DTE_MAX = 14
DELTA_MIN = 0.20, DELTA_MAX = 0.40
```

No rígidos: vienen de `app_settings` por perfil.

---

## 7. State machine — Campaign

```
STOCK_ACQUIRED
      │
      ▼
STOCK_AVAILABLE ◄──────────┐
      │                    │
      ▼                    │
   CALL_OPEN               │
      │                    │
 ┌────┼──────────┐         │
 ▼    ▼          ▼         │
CLOSED_TP  EXPIRED_OTM  ASSIGNED
 │         │             │
 └────┬────┘             ▼
      └──────────────► CLOSED
```

Transiciones adicionales soportadas: `MANUAL_CLOSE`, `ROLL`, `STOCK_SALE`.

El roll no es la estrategia principal pero **existe en el histórico de kover** (`app/api/options.py:368` ya tiene endpoint de roll), así que el builder debe reconocerlo.

## 8. State machine — Cycle

```python
class CycleStatus(str, Enum):
    OPEN = "OPEN"
    TP_ELIGIBLE = "TP_ELIGIBLE"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_MANUAL = "CLOSED_MANUAL"
    EXPIRED_OTM = "EXPIRED_OTM"
    ASSIGNED = "ASSIGNED"
    ROLLED = "ROLLED"
```

---

## 9. Normalización XBRL

Módulo `fundamentals/normalizer.py`. **Nunca confiar en un solo tag.** Cada métrica canónica tiene lista ordenada de aliases:

```python
ALIASES = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    # ...
}
```

Métricas canónicas: `revenue, grossProfit, operatingIncome, netIncome, cash, currentAssets, currentLiabilities, totalAssets, totalLiabilities, shortTermDebt, longTermDebt, operatingCashFlow, capitalExpenditure, freeCashFlow, sharesOutstanding, dilutedShares, stockholdersEquity, interestExpense`.

Cada fact guarda `source_tag, form, filing_date, accepted_at, period_start, period_end, fiscal_year, fiscal_quarter`. **La trazabilidad no se pierde nunca.**

### Acceso a SEC

```
Base: https://data.sec.gov
  /submissions/CIK##########.json
  /api/xbrl/companyfacts/CIK##########.json
```

Sin API key. Requiere `User-Agent` identificable (`SEC_USER_AGENT` en `.env`). Límite ~10 rps; se configura `SEC_MAX_RPS = 5` por margen.

Para carga masiva inicial usar los bulk `companyfacts.zip` / `submissions.zip` en vez de miles de requests.

**Todas las llamadas SEC son backend.** `data.sec.gov` no expone CORS.

### Métricas calculadas

```
current_ratio    = currentAssets / currentLiabilities
net_debt         = (shortTermDebt + longTermDebt) - cash
fcf              = operatingCashFlow - capitalExpenditure
fcf_margin       = fcf / revenue
operating_margin = operatingIncome / revenue
revenue_growth   = revenue_TTM / revenue_TTM_prev - 1
dilution_yoy     = sharesOutstanding / sharesOutstanding_1y - 1

# solo si FCF < 0
avg_quarterly_burn = abs(FCF últimos 2–4 trimestres) / n_quarters
runway_quarters    = cash / avg_quarterly_burn
```

---

## 10. Perfiles fundamentales

```python
class FundamentalProfile(str, Enum):
    MATURE_PROFITABLE = "MATURE_PROFITABLE"
    GROWTH_PROFITABLE = "GROWTH_PROFITABLE"
    GROWTH_PREPROFIT = "GROWTH_PREPROFIT"
    DEVELOPMENT_STAGE = "DEVELOPMENT_STAGE"
    FINANCIAL = "FINANCIAL"
    REIT = "REIT"
    UNKNOWN = "UNKNOWN"
```

v1 soporta con score completo los primeros cuatro. `FINANCIAL` y `REIT` se registran con `score_status = UNSUPPORTED_PROFILE` hasta implementar métricas sectoriales — **no reciben un score inventado.**

No se evalúa igual a Ford que a una pre-revenue.

---

## 11. Financial Safety Score

```
Liquidez                15%
Solvencia               15%
Caja / Cash Runway      20%
Flujo de caja           15%
Rentabilidad / tendencia 10%
Tendencia de ingresos   10%
Dilución                10%
Riesgo de filings        5%
```

No es solo una media ponderada: los **hard flags** actúan aparte.

```python
class FundamentalRiskFlag(str, Enum):
    GOING_CONCERN = "GOING_CONCERN"
    BANKRUPTCY = "BANKRUPTCY"
    RESTRUCTURING = "RESTRUCTURING"
    DELISTING_RISK = "DELISTING_RISK"
    SEVERE_LIQUIDITY_RISK = "SEVERE_LIQUIDITY_RISK"
    EXTREME_DILUTION = "EXTREME_DILUTION"
    NEGATIVE_EQUITY = "NEGATIVE_EQUITY"
    COVENANT_BREACH = "COVENANT_BREACH"
    AUDITOR_WARNING = "AUDITOR_WARNING"
    STALE_FILINGS = "STALE_FILINGS"
```

Veto (`REJECT`) inicial: going concern explícito, bankruptcy filing, runway < 2 trimestres, delisting inminente.

Penalización (`PENALIZE`): dilución > 25%, patrimonio negativo, runway < 6 trimestres, FCF deteriorándose rápido.

### Análisis textual de filings

Descargar el último 10-K, 10-Q y 8-K relevantes. Búsqueda **determinística** de: `going concern`, `substantial doubt`, `liquidity`, `covenant violation`, `default`, `restructuring`, `bankruptcy`, `material weakness`, `delisting`.

Guardar `flag, filing_id, text_excerpt, section, detected_at`.

Kover ya tiene integración con DeepSeek (`app/api/news.py`) y podría resumir filings. **Restricción dura: una IA nunca crea por sí sola un hard flag financiero sin evidencia trazable del filing.** La IA resume; el flag lo genera el matcher determinístico.

---

## 12. Riesgo de eventos corporativos

`AlphaVantageEventsProvider` sobre `EARNINGS_CALENDAR` (la key ya está en `.env` como `ALPHA_VANTAGE_KEY`).

Por defecto `exclude_earnings = true`: si hay earnings antes de la expiración, el contrato se excluye o se penaliza fuerte según perfil.

---

## 13. Métricas de la covered call

Precios de entrada **conservadores**: compra de acción al `ask`, venta de call al `bid`. **Nunca rankear con `last`.**

```
capital              = stock_entry * 100
premium_gross        = option_entry * 100
premium_net          = premium_gross - comisiones
premium_yield        = premium_net / capital
break_even           = stock_entry - option_entry
downside_buffer_pct  = option_entry / stock_entry
return_if_assigned   = (strike - stock_entry + option_entry - comisiones_por_accion) / stock_entry
distance_to_strike   = (strike - stock_entry) / stock_entry
mid                  = (bid + ask) / 2
spread_pct           = (ask - bid) / mid
expected_move        = stock_price * IV * sqrt(DTE / 365)
premium_over_em      = option_entry / expected_move
```

Si `bid` o `ask` faltan o `mid == 0` → la métrica es `None` con `reason`, **no 0**.

### Option Liquidity Score (0–100)

```
40%  calidad de spread
30%  percentil de volumen
30%  percentil de open interest
```

El spread pesa más porque la estrategia contempla cierres anticipados.

---

## 14. Perfiles del scanner

| | Conservador | Balanceado | Agresivo |
|---|---|---|---|
| Financial Safety ≥ | 75 | 60 | 45 |
| Market Safety ≥ | 65 | 45 | — |
| Spread ≤ | 8% | 12% | 20% |
| Delta | 0.20–0.30 | 0.25–0.35 | 0.30–0.40 |
| DTE | 7–14 | 5–10 | 5–10 |
| Earnings antes de exp. | excluir | excluir | permitido |

**Los hard flags fundamentales aplican incluso en modo agresivo.**

---

## 15. Scores de oportunidad

### CC Opportunity Score (0–100)

```
Premium Yield        25%
Return if Assigned   15%
Option Liquidity     15%
Spread Quality       15%
Delta Fit            10%
DTE Fit              10%
IV Opportunity       10%
```

Cada componente se normaliza como **percentil dentro del mismo scanner run**, con winsorización previa (p5/p95) para que un outlier no aplaste la escala. Así un 4% de yield no pesa igual en un mercado tranquilo que en uno con IV alta.

### Final Score

```
final = 0.45 * cc_opportunity + 0.35 * financial_safety + 0.20 * market_safety
```

Luego se aplican penalizaciones: evento (earnings), risk flags, liquidez.

**El orden es: primero puerta fundamental, después ranking.** Una prima enorme no compensa un riesgo fundamental crítico: CC Opportunity 97 con Financial Safety 25 no puede producir una recomendación aceptable, porque nunca llega al ranking.

### Un resultado por acción

Se calculan todos los contratos y se eligen tres:

```
BEST_BALANCED   → el que entra al ranking principal
BEST_PREMIUM
BEST_UPSIDE
```

El ranking principal no muestra 30 strikes del mismo ticker.

---

## 16. Gestión de take profit

Al abrir un ciclo se calculan y guardan TP70/TP75/TP80 **redondeados al tick del contrato**:

```python
def calculate_target_price(entry_price: float, profit_target: float, min_tick: float) -> float:
    """entry 0.50 @ 80% → 0.10. Redondea hacia arriba al tick permitido."""
```

Nunca asumir tick de $0.01 universalmente.

### Regla inicial

```
default_take_profit      = 80%
fast_take_profit         = 75%
fast_take_profit_max_days = 2
```

```
SI captured_profit >= 80%                       → señal TP80
SINO SI days_since_open <= 2 AND captured >= 75% → señal FAST_TP75
```

**La señal se evalúa contra el `ask`, no contra el `last`.** Recomprar requiere pagar el ask. La UI muestra `last`, `bid`, `ask`, `mid` como referencia, pero el gatillo es `ask <= target`.

v1: **solo alerta.** No se envía orden BTC automática.

---

## 17. Assignment

El assignment es un resultado **normal**, no un fallo. La UI dice `Potential assignment`, nunca `Danger`.

Al asignarse:

```
stock_gain      = (strike - stock_cost_basis) * shares
campaign_return = stock_gain + primas_totales + dividendos - comisiones_totales
```

Se cierra la campaign, se libera capital y se muestra `Capital available for redeployment` con acceso directo a correr el scanner.

### Métricas por campaign

Siempre separadas:

```
P/L Stock
P/L Opciones
P/L Total
```

Más: costo inicial, prima bruta, comisiones, dividendos, días de capital desplegado, retorno %, anualizado simple, rotación de capital, prima por día, retorno total por día.

---

## 18. Jobs (APScheduler, hora America/New_York)

```
05:30 ET  universe_refresh          (solo días hábiles)
06:00 ET  daily_bars_refresh
06:15 ET  fundamentals_refresh      (incremental, solo filings nuevos)
06:30 ET  corporate_events_refresh
07:00 ET  scanner_run (preliminar)

Mercado abierto:
  cada 15 min   scanner_refresh     (solo quotes + scores dependientes de mercado;
                                     NO recarga fundamentales)
  cada 60 seg   position_monitor    (posiciones abiertas: ask, captured %, TP)

07:15 ET  flex_sync                 (K7)
```

Los jobs viven en `jobs/tasks.py` como funciones puras invocables también desde un endpoint manual y desde tests. `jobs/scheduler.py` solo las registra. Eso permite mover a Redis/RQ después sin tocar lógica.

---

## 19. API REST

Prefijos siguiendo la convención existente de `main.py`.

```http
# Scanner
POST /api/scanner/run
GET  /api/scanner/runs
GET  /api/scanner/runs/{run_id}
GET  /api/scanner/runs/{run_id}/funnel        # conteos y razones de descarte
GET  /api/scanner/candidates                  # filtros: profile, price, dte, delta, min_score
GET  /api/scanner/candidates/{ticker}
GET  /api/scanner/candidates/{id}/explain     # desglose desde score_components

# Fundamentals
GET  /api/instruments/{symbol}/fundamentals
GET  /api/instruments/{symbol}/filings
GET  /api/instruments/{symbol}/risk-flags
GET  /api/instruments/{symbol}/options
GET  /api/instruments/{symbol}/covered-calls

# Campaigns
GET  /api/campaigns
GET  /api/campaigns/{id}
POST /api/campaigns/rebuild                   # regenera desde transactions
GET  /api/campaigns/{id}/cycles
GET  /api/cycles/{id}

# Señales
GET  /api/signals/take-profit
GET  /api/alerts
POST /api/alerts/{id}/acknowledge

# Backtest
POST /api/backtests
GET  /api/backtests
GET  /api/backtests/{id}

# Salud de datos
GET  /api/data-health

# Settings
GET  /api/settings
PUT  /api/settings
```

---

## 20. Frontend

Páginas nuevas en `frontend/src/pages/`:

```
Scanner.tsx           tabla rankeada + filtros interactivos
CandidateDetail.tsx   scores, fundamentales, flags, mejores calls, gráficos
Campaigns.tsx         campañas abiertas y cerradas con P/L desglosado
Fundamentals.tsx      vista por instrumento, trazable a filing
DataHealth.tsx        estado y frescura por proveedor
Backtests.tsx         K8
```

Componentes nuevos en `frontend/src/components/`:

```
ScoreBreakdown.tsx    "¿por qué 84?" — barras por componente con peso y aporte
TPIndicator.tsx       badge FAST TP75 / TP80 con captured %
FunnelChart.tsx       cuántas entraron, cuántas salieron y por qué
FreshnessBadge.tsx    as_of + fuente, en rojo si stale
```

Navegación: agregar `/scanner` y `/campaigns` a `NAV_LINKS` en [App.tsx:32](../frontend/src/App.tsx#L32); `/data-health` a `NAV_EXTRA`.

Se reutiliza el stack ya presente: axios + TanStack Query + Recharts + Tailwind con dark mode. No se agrega Zustand ni librerías de estado.

### Columnas del scanner

```
Rank · Ticker · Price · Final Score · Financial Safety · Market Safety ·
CC Opportunity · Strike · DTE · Delta · Bid · Ask · Spread% · Premium$ ·
Premium Yield · Return if Assigned · Break-even · Downside Buffer · IV ·
Option Volume · OI · Next Earnings
```

### Dashboard (extender el existente)

Agregar: Capital Deployed, Cash Available, Open Premium, Realized Premium, Current Annualized Return, Capital Turnover, Open Campaigns, TP Signals, Potential Assignments.

---

## 21. Backtesting

Tres modalidades, en orden obligatorio:

**A. Actual Replay** — reconstruir exactamente las operaciones IBKR importadas. Es la validación de que el motor entiende el histórico.

**B. Exit Policy Replay** — misma entrada real, distinta salida: TP70 / TP75 / TP80 / FAST75+TP80 / expiración. Comparar contra el resultado real. **Aquí se responde la pregunta central: ¿cerrar al 75/80% y reciclar supera a mantener hasta expiración?**

**C. Full Strategy Replay** — simula scanner, entrada, TP, reentrada, assignment y rotación. No se construye antes de validar A y B.

### Regla anti look-ahead

Una simulación fechada en `2026-03-01` solo puede usar información publicada antes de ese instante:

```sql
WHERE fundamental_snapshots.accepted_at <= :simulation_time
```

Igual para earnings, quotes y filings. Por eso los snapshots nunca se sobrescriben.

### Modelos de fill

```python
class FillModel(str, Enum):
    LIMIT_TOUCH = "LIMIT_TOUCH"                # daily_low <= target → ejecutado
    CONSERVATIVE_CLOSE = "CONSERVATIVE_CLOSE"  # daily_close <= target
    NBBO = "NBBO"                              # requiere histórico OPRA (no v1)
```

**Limitación conocida:** kover no tiene histórico de precios de opciones. La modalidad B en v1 se apoya en el histórico de operaciones reales importadas y en reconstrucción teórica Black-Scholes con IV estimada. Esto se documenta como aproximación, no como precisión de mercado. Un proveedor OPRA histórico es la vía para hacerlo exacto.

### Métricas comparadas

Total P/L, P/L stock, P/L opciones, prima realizada, número de calls, assignments, win rate, retorno medio y mediano por ciclo, DTE promedio, utilización de capital, rotación, $/capital/día, max drawdown, mejor y peor campaña, comisiones, costo de spread/slippage.

---

## 22. Salud de datos

Pantalla `/data-health`. Por proveedor: estado, última sincronización exitosa, último error.

Detección: quote stale, IV faltante, Delta faltante, fundamental stale, error de proveedor.

**Un scanner nunca debe rankear datos viejos en silencio como si fueran actuales.** Todo dato mostrado lleva `as_of`, `source` y `freshness`.

---

## 23. Reglas de dominio (invariantes)

1. Prima alta ≠ mejor oportunidad.
2. El riesgo fundamental se evalúa antes que las opciones.
3. Assignment no es automáticamente una pérdida.
4. El riesgo principal de una covered call es la caída del subyacente.
5. Nunca mostrar solo el P/L de la opción: siempre `stock + opción = campaign`.
6. Toda rentabilidad descuenta comisiones.
7. El spread importa especialmente cuando hay cierre anticipado.
8. `last` no es un precio ejecutable.
9. No usar datos futuros en backtesting.
10. Toda recomendación debe ser explicable.

### Reglas que aplican retroactivamente al Kover existente

Estas salen del plan pero corrigen deuda ya presente:

- **`null` + `reason`, nunca `0` como sustituto de "desconocido".** Hay puntos en `analytics.py` con fallback silencioso a 0.
- **Todo dato con `as_of`/`source`/`freshness`.** `market_data.py` cachea precios sin exponer antigüedad: una prima calculada sobre un precio de hace 3 horas se ve idéntica a una fresca.
- **`calculator.py` no debe aceptar `last` como precio de entrada** sin marcarlo.

---

## 24. Seguridad y configuración

Variables nuevas en `.env` (todas backend, nunca al navegador):

```
SEC_USER_AGENT="Kover/1.0 (mhrehbein@gmail.com)"
SEC_MAX_RPS=5
YF_MAX_CONCURRENCY=4
SCANNER_ENABLED=true
TRADING_ENABLED=false

# K7
IBKR_FLEX_TOKEN=
IBKR_FLEX_QUERY_TRADES=
IBKR_FLEX_QUERY_ACTIVITY=
```

Nunca loggear tokens IBKR, secretos OAuth, Flex token ni API keys.

### Trading safety (K9, no antes)

`TRADING_ENABLED=false` en v1. Cuando se habilite:

- confirmación manual obligatoria;
- validación `shares_owned >= contracts * 100` antes de cualquier call — **nunca permitir naked call**;
- `MAX_CONTRACTS_PER_ORDER`, `MAX_NOTIONAL_PER_ORDER`, `MAX_DAILY_ORDERS`, `KILL_SWITCH`;
- idempotency key para evitar órdenes duplicadas;
- toda integración de órdenes se prueba primero contra Paper Account.

---

## 25. Timezones

Internamente **UTC siempre**. Se guarda `executed_at_utc`, `source_timezone`, `original_timestamp`. El Activity Statement de IBKR entrega horas en EST — no almacenar timestamps ingenuos. La UI convierte al timezone del usuario (America/Santiago).

Los jobs se programan en `America/New_York` porque siguen el horario de mercado, no el del usuario.

---

## 26. Fases

Orden obligatorio. Después de cada fase: correr tests, correr migraciones, probar con datos reales, documentar, commit independiente vía `./deploy.sh`.

### K0 — Fundaciones
Migraciones 007. `providers/base.py` con Protocols. Logging estructurado. APScheduler arrancando. `app_settings`. `provider_status`.
**DoD:** `./deploy.sh` levanta todo, `/api/data-health` responde con estado de proveedores.

### K1 — Capa Campaign
Migración 008. `campaigns/builder.py` deriva campaigns y cycles del histórico ya importado. `/api/campaigns`. Página `Campaigns.tsx`.
**DoD:** BTBT, F, MARA y SMR se reconstruyen correctamente con aperturas, cierres, expiraciones, assignments, rolls y comisiones. El P/L total por ticker **cuadra con `/api/analytics/covered-call-cycles`** — si no cuadra, hay un bug en uno de los dos y se resuelve antes de seguir.

### K2 — SEC Fundamentals
Migración 009. Mapeo CIK, CompanyFacts, Submissions, normalizador XBRL, métricas, perfiles, flags determinísticos, Financial Safety Score.
**DoD:** `/instruments/F/fundamentals` muestra datos reales trazables al filing de origen. Luego validar SMR, MARA y QBTS para cubrir perfiles growth/pre-profit.

### K3 — Universo + riesgo de mercado
Migración 010. Universo optionable $10–20 con filtros de volumen. Barras diarias. Market Safety Score. Todavía sin opciones.
**DoD:** el usuario ve cuántas acciones entraron, cuántas se descartaron y **por qué** cada una.

### K4 — Option Scanner
Migración 011. Cadenas vía yfinance con rate limiting y backoff. Black-Scholes para Greeks. Todas las métricas de covered call. Option Liquidity Score.
**DoD:** para cada ticker elegible se muestra la mejor covered call con bid/ask reales.

### K5 — Scoring
Migración 012. CC Opportunity, Final Score, percentiles winsorizados, perfiles, `score_components`, `BEST_BALANCED/PREMIUM/UPSIDE`. Páginas `Scanner.tsx` y `CandidateDetail.tsx`.
**DoD:** scanner completo ordenado y **explicable**: cada score abre su desglose.

### K6 — Monitoreo en vivo
Migración 013. TP70/75/80 sobre ask con tick rounding, FAST_TP75, alertas de expiración, potential assignment, earnings risk. `position_monitor` cada 60 s. Sin trading.
**DoD:** `/campaigns` muestra captured % en vivo y dispara badge `FAST TP75 AVAILABLE` cuando corresponde.

### K7 — Reconciliación IBKR Flex
`providers/ibkr_flex.py` con las dos queries (Trade Confirmation, Activity Statement). Trade Confirmation sincroniza periódicamente sin polling agresivo (las executions aparecen ~5–10 min después). Activity Statement 1× cada mañana.
**DoD:** el import manual deja de ser necesario para el día a día.

#### Verificado contra la cuenta real (2026-08-09)

Ambas queries funcionan. Flujo: `SendRequest` → `ReferenceCode` → `GetStatement` en
`gdcdyn.interactivebrokers.com`. Reintentar ante `ErrorCode 1019` (statement en generación).

Confirmado en el XML real: las 6 filas con `notes="A"` son los 3 assignments conocidos con
sus dos patas cada uno (venta de acciones al strike + compra del call a $0), y hay 8 filas
con `IA` que **no** son asignaciones — la comparación token a token de `has_ib_code()` es
obligatoria también en el parser XML.

**Bloqueante a resolver antes de importar: el dedupe es unidireccional.**

Flex a nivel Execution trae 92 trades donde Kover tiene 80 en el mismo período. La
diferencia son fills parciales que el Activity Statement CSV entregaba agregados (18 grupos
con múltiples fills; p. ej. `BTBT 260522C00002500` del 2026-05-11 llega como 2+1+1 = 4
contratos).

`build_parsed_transactions` (línea ~989) sí detecta el caso **BD parcial + fila nueva
agregada**, comparando `group["qty_sum"]` contra la cantidad entrante — fue el fix del bug
del duplicado BTBT. Pero exige `group["count"] > 1`, así que el caso **inverso** —BD
agregada, Flex parcial— no entra a esa rama, el hash exacto no calza y cada fill se
importaría como transacción nueva.

Solución: comparar a nivel de grupo `(ticker, fecha, tipo)` sumando **ambos lados** en vez
de fila contra grupo. Sin eso, la primera corrida de Flex duplica ~12 operaciones.

**Hueco de datos detectado:** falta la retención de KHC del 2025-12-26 (−$1,20). El
dividendo de $4 sí está; la retención no, porque el extracto importado empezaba en
2026-01-01 y la sección Withholding Tax se agregó al importador recién el 2026-08-05.
Subestima el crédito del Art. 41A en $1,20. Se corrige solo al reimportar los 365 días de
Flex, una vez arreglado el dedupe.

### K8 — Backtest A y B
Migración 014. Actual Replay + Exit Policy Replay con comisiones.
**DoD:** comparación cuantitativa entre la estrategia real y TP70/TP75/TP80/FAST75+TP80.

### K9 — Full simulation, IBKR Web API, asistencia de órdenes
Solo después de validar todo lo anterior. Botón `Create Order` con preview y confirmación manual. Sin trading autónomo.

---

## 27. Testing

Kover ya tiene `backend/tests/` con 4 archivos. **pytest no está instalado en la imagen** — agregar `requirements-dev.txt` y un target para correrlos.

### Unit (prioridad alta)
Cálculo de prima, return if assigned, break-even, anualización, spread %, cálculo de TP, redondeo a tick, Financial Safety Score, CC Score, hard flags, P/L de campaign, assignment, Black-Scholes delta contra valores conocidos.

### Provider tests
Fixtures grabados para: respuestas SEC CompanyFacts, SEC Submissions, cadena yfinance, Flex XML. **Los tests unitarios nunca golpean APIs reales.**

### Integration
Postgres real vía Docker: builder de campaigns, funnel del scanner end-to-end con proveedores mockeados.

### Golden dataset
El extracto IBKR histórico existente es el fixture principal. BTBT, F, MARA y SMR deben reconstruirse correctamente, incluyendo cierres, expiraciones y assignments.

---

## 28. Definition of Done general

Una feature no está terminada si:

- no tiene tests;
- no maneja errores del proveedor;
- no guarda timestamp ni fuente;
- no distingue stale de live;
- no puede explicar sus cálculos;
- no considera comisiones;
- genera silenciosamente datos inventados cuando faltan datos.

Si una métrica no se puede calcular: `null` + `reason`. **Nunca `0`.**

---

## 29. Fuera de alcance en v1

```
Cash Secured Puts (el modelo los soporta, el scanner no los rankea)
Wheel completa
Credit spreads
Iron Condors
PMCC
Optimización de portfolio margin
Ejecución automatizada
Predicciones con machine learning
Decisiones de trading tomadas por LLM
```

La arquitectura se deja extensible para todo esto. La cuenta se trata como **Covered Calls only**.

---

## 30. Ciclo objetivo

```
        UNIVERSO DE MERCADO
               │
               ▼
        $10–20 + liquidez
               │
               ▼
        FILTRO FUNDAMENTAL
               │
               ▼
         RIESGO DE MERCADO
               │
               ▼
         SCANNER DE OPCIONES
               │
               ▼
          CC SCORE 0–100
               │
               ▼
        SELECCIÓN DE CANDIDATO
               │
               ▼
      COMPRAR ACCIÓN + VENDER CALL
               │
       ┌───────┴────────┐
       ▼                ▼
    TP75/80         ASSIGNMENT
       │                │
       ▼                ▼
 Acciones libres   Capital libre
       │                │
       └───────┬────────┘
               ▼
          CORRER SCANNER
               │
               ▼
             REPETIR
```

La métrica principal del sistema **no es** "cuánta prima cobré", sino:

> **qué rendimiento total obtuve por unidad de capital, tiempo y riesgo asumido.**

Ese es el principio central de toda la arquitectura.