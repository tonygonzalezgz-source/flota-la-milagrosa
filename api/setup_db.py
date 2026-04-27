"""
La Milagrosa — Setup y Seed de la Base de Datos
Ejecutar una sola vez: python api/setup_db.py
"""
import sqlite3
import os

BASE_DIR   = os.path.dirname(__file__)
DB_PATH    = os.path.join(BASE_DIR, "flota.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def create_tables(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    print("[OK] Tablas creadas")


def seed_usuarios(conn):
    usuarios = [
        ("admin",       "admin123",    "Marco Admin",    "Administrador",  "MA", "#6366f1"),
        ("analista",    "analista123", "Laura Analista", "Analista",       "LA", "#22c55e"),
        ("tecnico",     "tecnico123",  "Jorge Técnico",  "Técnico Mant.",  "JT", "#f59e0b"),
        ("propietario", "prop123",     "Carlos Noriega", "Propietario",    "CN", "#f59e0b"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO usuarios (username, password, nombre, rol, iniciales, color) VALUES (?,?,?,?,?,?)",
        usuarios,
    )
    print(f"[OK] {len(usuarios)} usuarios sembrados")


def seed_buses(conn):
    buses = []
    # Grupo A: buses 1–63
    modelos_a = ["Mercedes Benz O500", "Volvo B9R", "Scania K310", "Hino AK", "Agrale MT17"]
    for n in range(1, 64):
        placa  = f"ABC-{100 + n:03d}"
        modelo = modelos_a[(n - 1) % len(modelos_a)]
        estado = "activo" if n % 7 != 0 else ("alerta" if n % 3 == 0 else "revision")
        buses.append((n, placa, modelo, "A", estado, (n * 1237) % 180000))

    # Grupo B: buses 64–94
    modelos_b = ["Marcopolo Viale", "Busscar Urbanuss", "Caio Induscar"]
    for n in range(64, 95):
        placa  = f"XYZ-{n:03d}"
        modelo = modelos_b[(n - 64) % len(modelos_b)]
        estado = "activo" if n % 5 != 0 else "alerta"
        buses.append((n, placa, modelo, "B", estado, (n * 987) % 200000))

    conn.executemany(
        "INSERT OR IGNORE INTO buses (numero, placa, modelo, grupo, estado, km_actuales) VALUES (?,?,?,?,?,?)",
        buses,
    )
    print(f"[OK] {len(buses)} buses sembrados")


def seed_rutas(conn):
    rutas = [
        ("Ruta 1 — Centro › Norte",            "Recorre el eje norte de la ciudad", "A", "#6366f1"),
        ("Ruta 2 — Centro › Sur",              "Recorre el eje sur de la ciudad",   "A", "#22c55e"),
        ("Ruta 3 — Centro › Este",             "Recorre el eje este de la ciudad",  "A", "#f59e0b"),
        ("Ruta 4 — Centro › Oeste",            "Recorre el eje oeste de la ciudad", "A", "#ef4444"),
        ("Ruta A — Terminal › Aeropuerto",     "Conecta terminal con aeropuerto",   "B", "#14b8a6"),
        ("Ruta B — Terminal › Zona Industrial","Conecta terminal con zona ind.",     "B", "#a855f7"),
        ("Ruta C — Terminal › Universidad",    "Conecta terminal con universidad",  "B", "#fb923c"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO rutas (nombre, descripcion, grupo, color) VALUES (?,?,?,?)",
        rutas,
    )
    print(f"[OK] {len(rutas)} rutas sembradas")


def seed_tipos_novedad(conn):
    tipos = [
        ("aceite",  "Aceite",  "#6366f1", 1),
        ("llantas", "Llantas", "#14b8a6", 2),
        ("bateria", "Batería", "#f59e0b", 3),
        ("luces",   "Luces",   "#22c55e", 4),
        ("frenos",  "Frenos",  "#ef4444", 5),
        ("motor",   "Motor",   "#a855f7", 6),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO tipos_novedad (clave, label, color, orden) VALUES (?,?,?,?)",
        tipos,
    )
    print(f"[OK] {len(tipos)} tipos de novedad sembrados")


def seed_estado_mantenimiento(conn):
    """Estado inicial para los primeros 10 buses (demo)."""
    bus_ids = [r[0] for r in conn.execute("SELECT id FROM buses ORDER BY numero LIMIT 10").fetchall()]
    nov_ids = {r["clave"]: r["id"] for r in conn.execute("SELECT id, clave FROM tipos_novedad").fetchall()}

    estados_demo = {
        "aceite":  ("ok",    82, "02 Abr 2026", "Cambio rutinario"),
        "llantas": ("warn",  58, "15 Feb 2026", "Presión baja delantera"),
        "bateria": ("alert", 18, "10 Ene 2026", "Carga crítica"),
        "luces":   ("ok",   100, "10 Abr 2026", "Todo operativo"),
        "frenos":  ("alert",  9, "05 Nov 2025", "Pastillas al límite"),
        "motor":   ("warn",  63, "20 Mar 2026", "Temperatura elevada"),
    }

    rows = []
    for bus_id in bus_ids:
        for clave, (estado, progreso, fecha, obs) in estados_demo.items():
            rows.append((bus_id, nov_ids[clave], estado, progreso, fecha, obs))

    conn.executemany(
        """INSERT OR IGNORE INTO estado_mantenimiento
           (bus_id, tipo_novedad_id, estado, progreso, ultima_fecha, ultima_obs)
           VALUES (?,?,?,?,?,?)""",
        rows,
    )
    print(f"[OK] Estado de mantenimiento inicial sembrado para {len(bus_ids)} buses")


def main():
    if os.path.exists(DB_PATH):
        resp = input(f"⚠️  La base de datos ya existe ({DB_PATH}).\n¿Deseas recrearla? (s/N): ")
        if resp.strip().lower() != "s":
            print("Cancelado.")
            return
        os.remove(DB_PATH)
        print("[DB] Base de datos anterior eliminada.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    create_tables(conn)
    seed_usuarios(conn)
    seed_buses(conn)
    seed_rutas(conn)
    seed_tipos_novedad(conn)
    seed_estado_mantenimiento(conn)

    conn.commit()
    conn.close()
    print(f"\n✅ Base de datos lista en: {DB_PATH}")


if __name__ == "__main__":
    main()
