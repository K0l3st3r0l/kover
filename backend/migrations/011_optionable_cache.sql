-- Caché de optionabilidad: no volver a preguntarle a Yahoo lo que ya sabemos.
--
-- Nota de numeración: el plan original (docs/COVERED_CALL_SCANNER_PLAN.md) reserva
-- 011 para option_contracts (K4). Esta migración se adelantó porque el rate limit de
-- Yahoo detectado en la primera corrida real de K3 (ver
-- wiki/projects/kover/bugs/scanner-rate-limit-false-not-optionable.md) exigía reducir
-- el volumen de requests antes de seguir, no solo espaciarlos. K4 toma el siguiente
-- número libre cuando corresponda.
ALTER TABLE instruments ADD COLUMN IF NOT EXISTS optionable_checked_at TIMESTAMPTZ;
