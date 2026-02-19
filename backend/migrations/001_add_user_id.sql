-- Migration: Add user_id to stocks and options tables

-- Add user_id to stocks table
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE stocks ADD CONSTRAINT fk_stocks_user_id FOREIGN KEY (user_id) REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_stocks_user_id ON stocks(user_id);

-- Drop unique constraint on ticker (users can have same ticker)
ALTER TABLE stocks DROP CONSTRAINT IF EXISTS stocks_ticker_key;

-- Note: Existing data will have NULL user_id and needs to be migrated manually
-- or deleted before adding NOT NULL constraint
