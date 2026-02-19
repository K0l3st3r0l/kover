-- Migración: Crear tabla watchlist
-- Fecha: 2026-02-07

CREATE TABLE IF NOT EXISTS watchlist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    company_name VARCHAR(255),
    target_price DECIMAL(10, 2),
    notes TEXT,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Índices para mejorar el rendimiento
CREATE INDEX idx_watchlist_user_id ON watchlist(user_id);
CREATE INDEX idx_watchlist_ticker ON watchlist(ticker);
CREATE UNIQUE INDEX idx_watchlist_user_ticker ON watchlist(user_id, ticker);
