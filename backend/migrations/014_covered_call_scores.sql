-- CC Opportunity Score y Final Score (K5) sobre los candidatos de K4.
--
-- Columnas en covered_call_candidates y no una tabla nueva: el score es un
-- atributo del contrato elegido, no una entidad aparte, y se recalcula en la
-- misma corrida que lo produjo.
--
-- El gate por perfil NO se persiste: es barato de evaluar y depende del perfil
-- que elija el usuario en la UI. Guardar tres columnas de gate obligaría a
-- rescanear para cambiar de perfil, cuando la única entrada que falta es un
-- umbral.
ALTER TABLE covered_call_candidates
    ADD COLUMN IF NOT EXISTS cc_opportunity_score NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS cc_score_components  JSONB,
    ADD COLUMN IF NOT EXISTS final_score          NUMERIC(6,2),
    -- OK | MISSING_FUNDAMENTAL | MISSING_MARKET | MISSING_BOTH |
    -- MISSING_CC_OPPORTUNITY. Un final_score NULL siempre trae su razón: sin
    -- esto, "sin score" es indistinguible de "todavía no se calculó".
    ADD COLUMN IF NOT EXISTS final_score_status   VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_cc_candidate_final_score
    ON covered_call_candidates(pick_type, final_score DESC NULLS LAST);
