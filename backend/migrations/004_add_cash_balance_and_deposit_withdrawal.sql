-- Migration 004: Add cash_balance to users + DEPOSIT/WITHDRAWAL to transaction types
-- Applied: 2026-03-01

-- Add new transaction types to enum
ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'DEPOSIT';
ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'WITHDRAWAL';

-- Add cash_balance column to users table (manual update via /api/auth/cash PUT)
ALTER TABLE users ADD COLUMN IF NOT EXISTS cash_balance FLOAT DEFAULT 0.0;
