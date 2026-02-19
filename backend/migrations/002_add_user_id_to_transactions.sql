-- Migración: Agregar user_id a la tabla transactions
-- Fecha: 2026-02-07

-- Agregar columna user_id
ALTER TABLE transactions ADD COLUMN user_id INTEGER;

-- Establecer un valor por defecto para registros existentes (ajustar según sea necesario)
-- Si ya tienes un usuario, usa su ID, por ejemplo: UPDATE transactions SET user_id = 1;

-- Agregar restricción de clave foránea
ALTER TABLE transactions ADD CONSTRAINT fk_transactions_user 
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Hacer que el campo sea NOT NULL (después de haber establecido los valores)
ALTER TABLE transactions ALTER COLUMN user_id SET NOT NULL;

-- Crear índice para mejorar el rendimiento de consultas
CREATE INDEX idx_transactions_user_id ON transactions(user_id);
