-- Migración: Agregar user_id a la tabla transactions
-- Fecha: 2026-02-07

-- Agregar columna user_id
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS user_id INTEGER;

-- Establecer un valor por defecto para registros existentes (ajustar según sea necesario)
-- Si ya tienes un usuario, usa su ID, por ejemplo: UPDATE transactions SET user_id = 1;

-- Agregar restricción de clave foránea (idempotente con DO $$)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_transactions_user' AND conrelid = 'transactions'::regclass
    ) THEN
        ALTER TABLE transactions ADD CONSTRAINT fk_transactions_user
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Hacer que el campo sea NOT NULL (después de haber establecido los valores)
-- Solo si la columna existe y no es NOT NULL
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'transactions' AND column_name = 'user_id' AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE transactions ALTER COLUMN user_id SET NOT NULL;
    END IF;
END $$;

-- Crear índice para mejorar el rendimiento de consultas
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
