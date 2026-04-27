"""
migrate_to_supabase.py
──────────────────────
Transfiere todos los datos del SQLite local → Supabase PostgreSQL.

Uso:
    1. Asegúrate de tener el archivo .env con DATABASE_URL configurado
    2. python3 api/migrate_to_supabase.py
"""

import sqlite3
import os
import sys

# Cargar .env
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(__file__), "flota.db")

if not DATABASE_URL:
    print("❌  Falta DATABASE_URL en el archivo .env")
    sys.exit(1)

if not os.path.exists(DB_PATH):
    print("❌  No se encontró la base de datos SQLite:", DB_PATH)
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("❌  Instala dependencias: pip3 install -r requirements.txt")
    sys.exit(1)


# ── Conexiones ──────────────────────────────────────────
print("🔌  Conectando a SQLite local…")
sqlite_conn = sqlite3.connect(DB_PATH)
sqlite_conn.row_factory = sqlite3.Row

print("🔌  Conectando a Supabase…")
pg_conn = psycopg2.connect(DATABASE_URL, sslmode="require")
pg_cur  = pg_conn.cursor()


def rows(sql, params=()):
    return [dict(r) for r in sqlite_conn.execute(sql, params).fetchall()]


def pg_exec(sql, params=()):
    pg_cur.execute(sql, params)


def pg_insert_many(sql, data):
    if data:
        psycopg2.extras.execute_values(pg_cur, sql, data)


# ── Orden de migración (respeta FKs) ─────────────────────
TABLES_ORDER = [
    "usuarios",
    "propietarios",
    "rutas",
    "buses",
    "tarifas",
    "tipos_novedad",
    "usuario_buses",
    "estado_mantenimiento",
    "registros_mantenimiento",
    "registros_pasajeros",
    "registros_movilidad",
]


def migrate_table(table):
    data = rows(f"SELECT * FROM {table}")
    if not data:
        print(f"  ⚪  {table}: vacía, omitida")
        return

    cols = list(data[0].keys())
    cols_str = ", ".join(cols)
    vals_placeholder = ", ".join(["%s"] * len(cols))

    # Limpiar tabla destino antes de insertar
    pg_exec(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")

    records = [tuple(r[c] for c in cols) for r in data]
    pg_cur.executemany(
        f"INSERT INTO {table} ({cols_str}) VALUES ({vals_placeholder})",
        records,
    )

    # Resetear secuencia si hay columna id SERIAL
    if "id" in cols:
        pg_exec(f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE(MAX(id), 1)
            ) FROM {table}
        """)

    print(f"  ✅  {table}: {len(records)} filas migradas")


# ── Ejecutar migración ───────────────────────────────────
print("\n📦  Iniciando migración de datos…\n")

try:
    for table in TABLES_ORDER:
        try:
            migrate_table(table)
        except Exception as e:
            print(f"  ⚠️   {table}: {e}")
            pg_conn.rollback()

    pg_conn.commit()
    print("\n🎉  Migración completada con éxito.")
    print("    Ya puedes configurar DATABASE_URL en el servidor y usar Supabase.")

except Exception as e:
    pg_conn.rollback()
    print(f"\n❌  Error fatal: {e}")
    sys.exit(1)

finally:
    sqlite_conn.close()
    pg_conn.close()
