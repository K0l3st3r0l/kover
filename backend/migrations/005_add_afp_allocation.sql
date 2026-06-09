-- Migration 005: Add afp_allocation to users
-- Persists per-user AFP fund allocation across devices/sessions.
-- Stored as JSONB: {"A": 0, "B": 0, "C": 0, "D": 40, "E": 60}

ALTER TABLE users ADD COLUMN IF NOT EXISTS afp_allocation JSONB;
