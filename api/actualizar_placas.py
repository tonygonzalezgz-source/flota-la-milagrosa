"""
Actualiza las placas de los buses con las placas reales (PLACAS 2026 FM).

Funciona contra SQLite local o Supabase/PostgreSQL según DATABASE_URL:
  - Local (SQLite):   python api/actualizar_placas.py
  - Producción (PG):  DATABASE_URL="postgresql://..." python api/actualizar_placas.py

Hace UPDATE buses SET placa=? WHERE numero=?  (solo cambia la columna placa;
no toca ningún otro dato). Muestra el antes/después de cada cambio.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from placas_reales import PLACAS_REALES

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH      = os.path.join(os.path.dirname(__file__), "flota.db")


def connect():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return conn, "%s"
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    return conn, "?"


def main():
    conn, ph = connect()
    cur = conn.cursor()

    destino = "Supabase/PostgreSQL" if DATABASE_URL else f"SQLite ({DB_PATH})"
    print(f"[DB] Destino: {destino}\n")

    cur.execute("SELECT numero, placa FROM buses ORDER BY numero")
    actuales = {row[0]: row[1] for row in cur.fetchall()}

    cambios = 0
    sin_bus = []
    for numero, placa_real in sorted(PLACAS_REALES.items()):
        if numero not in actuales:
            sin_bus.append(numero)
            continue
        if actuales[numero] == placa_real:
            continue
        cur.execute(f"UPDATE buses SET placa = {ph} WHERE numero = {ph}", (placa_real, numero))
        print(f"  Bus {numero:>2}: {actuales[numero] or '(vacío)':<10} → {placa_real}")
        cambios += 1

    conn.commit()
    conn.close()

    print(f"\n[OK] {cambios} placas actualizadas.")
    if sin_bus:
        print(f"[AVISO] Estos números no existen en la tabla buses: {sin_bus}")
    if cambios == 0:
        print("Todas las placas ya coincidían; no hubo cambios.")


if __name__ == "__main__":
    main()
