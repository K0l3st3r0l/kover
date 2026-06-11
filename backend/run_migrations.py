#!/usr/bin/env python3
"""
Runner de migraciones SQL para Kover.
Ejecuta archivos .sql en orden alfabético, registrando los ya aplicados en la tabla migrations.
"""
import os
import sys
import glob
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@db:5432/kover")
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def ensure_migrations_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """)


def get_applied_migrations(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM migrations ORDER BY id")
        return {row[0] for row in cur.fetchall()}


def run_migration(conn, filepath, filename):
    with open(filepath, "r") as f:
        sql = f.read()

    with conn.cursor() as cur:
        print(f"Ejecutando: {filename}")
        cur.execute(sql)
        cur.execute("INSERT INTO migrations (filename) VALUES (%s)", (filename,))
        print(f"✓ {filename} completado")


def main():
    print("Ejecutando migraciones...")
    conn = get_connection()
    ensure_migrations_table(conn)
    applied = get_applied_migrations(conn)

    files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    ran = 0
    for filepath in files:
        filename = os.path.basename(filepath)
        if filename in applied:
            continue
        try:
            run_migration(conn, filepath, filename)
            ran += 1
        except Exception as e:
            print(f"✗ Error en {filename}: {e}")
            sys.exit(1)

    if ran == 0:
        print("✅ No hay migraciones pendientes.")
    else:
        print(f"✅ {ran} migración(es) completada(s).")

    conn.close()


if __name__ == "__main__":
    main()
