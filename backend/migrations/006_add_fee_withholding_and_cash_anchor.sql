-- Migration 006: tipos FEE / WITHHOLDING_TAX + ancla del saldo de caja
--
-- FEE y WITHHOLDING_TAX van separados a propósito: la retención de EE.UU. es
-- acreditable contra el Global Complementario (Art. 41A) y `api/fiscal.py` la
-- necesita distinguible; los fees de datos de mercado son gasto puro y no lo son.
--
-- El runner corre en autocommit, así que ADD VALUE no choca con el uso posterior
-- del tipo (mismo patrón que la migración 004).

ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'FEE';
ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'WITHHOLDING_TAX';

-- Ancla del saldo de caja: `cash_balance` pasa a derivarse de las transacciones,
-- pero el historial no tiene los depósitos antiguos. El ancla fija desde dónde
-- se suman los flujos. Con opening_date NULL se suma todo el historial.
ALTER TABLE users ADD COLUMN IF NOT EXISTS cash_opening_balance FLOAT DEFAULT 0.0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS cash_opening_date TIMESTAMP WITH TIME ZONE;
