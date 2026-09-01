-- Historial de veredictos del comité AFP. El JSON diario se pisaba; sin
-- esta tabla no hay forma de medir si la recomendación rindió.
-- CREATE TABLE IF NOT EXISTS: create_all puede ganar la carrera al runner.

CREATE TABLE IF NOT EXISTS ai_committee_snapshots (
    id            SERIAL PRIMARY KEY,
    as_of_date    DATE NOT NULL UNIQUE,
    generated_at  TIMESTAMPTZ NOT NULL,
    provider      TEXT,
    origin        TEXT NOT NULL DEFAULT 'live',
    analysts      JSONB NOT NULL DEFAULT '[]'::jsonb,
    arbiter       JSONB NOT NULL DEFAULT '{}'::jsonb,
    context       JSONB
);

CREATE INDEX IF NOT EXISTS idx_ai_committee_snapshots_generated_at
    ON ai_committee_snapshots (generated_at);

-- Veredicto real del 2026-07-05 (último caché de OpenCode antes de que
-- dejara de regenerar). Se siembra para que el seguimiento no empiece
-- en cero el día que se agrega la tabla.
INSERT INTO ai_committee_snapshots (
    as_of_date, generated_at, provider, origin, analysts, arbiter
) VALUES (
    '2026-07-05',
    '2026-07-05T09:25:39.246614+00',
    'opencode',
    'seed',
    $analysts$[
      {
        "model": "deepseek-v4-pro",
        "parsed": {
          "regimen": "agresivo",
          "distribucion": [{"fondo": "A", "pct": 100}]
        }
      },
      {
        "model": "minimax-m3",
        "parsed": {
          "regimen": "Riesgo moderado con sesgo alcista",
          "distribucion": [{"fondo": "B", "pct": 70}, {"fondo": "C", "pct": 30}]
        }
      }
    ]$analysts$::jsonb,
    $arbiter${
      "model": "glm-5.1",
      "parsed": {
        "decision_final": {
          "regimen": "Agresivo con hedge táctico",
          "distribucion": [{"fondo": "B", "pct": 80}, {"fondo": "C", "pct": 20}]
        }
      }
    }$arbiter$::jsonb
)
ON CONFLICT (as_of_date) DO NOTHING;
