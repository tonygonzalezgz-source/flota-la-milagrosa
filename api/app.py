"""
La Milagrosa — API Flask
Corre en: http://localhost:8001
Soporta SQLite (local) y PostgreSQL/Supabase (producción).
"""
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import time
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from dotenv import load_dotenv

import jwt as _jwt
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()  # carga variables desde .env si existe

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..")

# Genera una clave secreta aleatoria si no está en el entorno (en prod se debe fijar en .env)
SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "12"))
CRON_SECRET = os.environ.get("CRON_SECRET")  # protege endpoints /api/cron/*

# Rate limiting para el endpoint de login
_login_attempts: dict = {}   # {ip: [timestamp, ...]}
_LOGIN_MAX    = 10
_LOGIN_WINDOW = 300  # segundos

def _check_rate_limit(ip: str) -> bool:
    """Devuelve True si la IP puede intentar login, False si fue bloqueada."""
    now = time.time()
    times = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = times
    if len(times) >= _LOGIN_MAX:
        return False
    _login_attempts[ip].append(now)
    return True

app = Flask(__name__, static_folder=None)

# Orígenes permitidos: en producción ajustar ALLOWED_ORIGINS en las variables de entorno
_allowed = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, origins=_allowed)


# ── Decorador de autenticación JWT ──
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "No autorizado"}), 401
        token = auth_header[7:]
        try:
            payload = _jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.jwt_user_id  = payload.get("user_id")
            request.jwt_user_rol = payload.get("rol")
        except _jwt.ExpiredSignatureError:
            return jsonify({"error": "Sesión expirada. Inicia sesión nuevamente."}), 401
        except _jwt.InvalidTokenError:
            return jsonify({"error": "Token inválido"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Decorador de autorización por rol ──
def require_role(*roles):
    """Exige token válido (require_auth) y que el rol esté entre los permitidos."""
    def wrapper(f):
        @require_auth
        @wraps(f)
        def decorated(*args, **kwargs):
            if getattr(request, "jwt_user_rol", None) not in roles:
                return jsonify({"error": "No autorizado para esta acción"}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper


# ── Servir frontend estático en producción ──
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    full = os.path.join(FRONTEND_DIR, path)
    if path and os.path.isfile(full):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")

DATABASE_URL = os.environ.get("DATABASE_URL")   # None → SQLite local

# Supabase: el pooler en modo sesión (puerto 5432) limita a 15 clientes y se
# agota con las funciones concurrentes de Vercel (EMAXCONNSESSION). El modo
# transacción (puerto 6543) multiplexa las conexiones y es el indicado para
# serverless, así que se fuerza aquí sin importar cómo esté la variable.
if DATABASE_URL and "pooler.supabase.com" in DATABASE_URL and ":6543" not in DATABASE_URL:
    if ":5432" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace(":5432", ":6543")
    else:
        DATABASE_URL = DATABASE_URL.replace("pooler.supabase.com", "pooler.supabase.com:6543")
DB_PATH      = os.path.join(os.path.dirname(__file__), "flota.db")
SCHEMA_PATH  = os.path.join(os.path.dirname(__file__), "schema.sql")
PG_SCHEMA    = os.path.join(os.path.dirname(__file__), "supabase_schema.sql")

# Versión del esquema. IMPORTANTE: incrementar en 1 cada vez que se agregue
# una migración (ALTER/CREATE) a migrate_db(); si no se incrementa, la
# migración nueva NO corre en las BD ya versionadas.
SCHEMA_VERSION = 7

ROLE_VIEWS = {
    "Administrador":  ["dashboard", "historial", "mant", "propietario", "catalogo", "despacho", "historial-despacho", "gastos", "tecnologia", "chequeo", "eds", "lavada", "mapa", "relojes"],
    "Analista":       ["historial"],
    "Técnico Mant.":  ["mant"],
    "Técnico Cámaras":       ["tecnologia"],
    "Jefe Op. Tecnológicas": ["tecnologia"],
    "Operador EDS":   ["eds"],
    "Operador Lavada": ["lavada"],
    "Propietario":    ["propietario", "gastos", "tecnologia", "lavada"],
    "Despachador":    ["despacho", "historial-despacho", "chequeo"],
    "Jefe de Ruta":   ["dashboard", "despacho", "historial-despacho", "chequeo", "alistamiento", "relojes"],
    "Conductor":      ["alistamiento"],
}

# Roles que pueden operar el módulo de chequeo (llegada/salida en puestos)
ROLES_CHEQUEO = ("Despachador", "Administrador", "Jefe de Ruta")


# ══════════════════════════════════════════
#  Capa de abstracción DB
#  Hace que psycopg2 se comporte igual que sqlite3
# ══════════════════════════════════════════

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    class _PGCur:
        """Cursor wrapper: expone la misma API que sqlite3.Cursor."""
        def __init__(self, raw_cur, last_id=None):
            self._c       = raw_cur
            self.lastrowid = last_id

        def fetchall(self):
            try:
                return [dict(r) for r in self._c.fetchall()]
            except Exception:
                return []

        def fetchone(self):
            row = self._c.fetchone()
            return dict(row) if row else None

    class _PGConn:
        """Conexión wrapper: convierte ? → %s y gestiona lastrowid."""
        def __init__(self, raw_conn):
            self._conn = raw_conn

        def execute(self, sql, params=()):
            sql_pg = sql.replace("?", "%s")
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql_pg, params if params else ())

            last_id = None
            if sql_pg.strip().upper().startswith("INSERT"):
                # SAVEPOINT evita que lastval() (que falla en tablas sin
                # secuencia, como usuario_buses) aborte la transacción.
                aux = self._conn.cursor()
                try:
                    aux.execute("SAVEPOINT _lastval_sp")
                    try:
                        aux.execute("SELECT lastval()")
                        row = aux.fetchone()
                        last_id = row[0] if row else None
                        aux.execute("RELEASE SAVEPOINT _lastval_sp")
                    except Exception:
                        aux.execute("ROLLBACK TO SAVEPOINT _lastval_sp")
                except Exception:
                    pass

            return _PGCur(cur, last_id)

        def executemany(self, sql, params_list):
            sql_pg = sql.replace("?", "%s")
            cur = self._conn.cursor()
            cur.executemany(sql_pg, params_list)
            return _PGCur(cur)

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

        def close(self):
            self._conn.close()

    def get_db():
        conn = psycopg2.connect(DATABASE_URL, sslmode="require", connect_timeout=10)
        wrapper = _PGConn(conn)
        # Registrar la conexión en el contexto del request: si el handler lanza
        # una excepción antes de su db.close(), el teardown la cierra igual y
        # no queda huérfana ocupando un cupo del pooler.
        try:
            from flask import g
            g.setdefault("_db_conns", []).append(wrapper)
        except RuntimeError:
            pass  # fuera de un request (init_db, scripts)
        return wrapper

    @app.teardown_appcontext
    def _close_leaked_db(_exc):
        from flask import g
        for w in g.get("_db_conns", []):
            try:
                w.close()  # no-op si el handler ya la cerró
            except Exception:
                pass

else:
    import sqlite3

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _schema_version_guardada(db):
    """Versión de esquema registrada en la BD; 0 si la tabla no existe aún."""
    try:
        row = db.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        return row["version"] if row else 0
    except Exception:
        try:
            db.rollback()  # en Postgres el SELECT fallido aborta la transacción
        except Exception:
            pass
        return 0


def init_db():
    """Crea las tablas si no existen y ejecuta migraciones.

    En Vercel esto corre en cada cold start del serverless: si la BD ya está
    en SCHEMA_VERSION retorna tras UNA sola consulta, en lugar de repetir las
    ~70 sentencias de esquema/migración contra Supabase cada vez."""
    if not DATABASE_URL and not os.path.exists(DB_PATH):
        # ── Modo SQLite local: crear la BD por primera vez ──
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            sql = f.read()
        import sqlite3 as _sq3
        conn = _sq3.connect(DB_PATH)
        conn.executescript(sql)
        conn.commit()
        conn.close()
        print("[DB] Base de datos SQLite creada:", DB_PATH)
        migrate_db()
        return

    db = get_db()
    al_dia = _schema_version_guardada(db) == SCHEMA_VERSION
    db.close()
    if al_dia:
        return

    if DATABASE_URL:
        # ── Modo PostgreSQL: ejecuta el esquema en Supabase con autocommit ──
        print("[DB] Conectando a Supabase PostgreSQL…")
        with open(PG_SCHEMA, "r", encoding="utf-8") as f:
            sql = f.read()
        raw = psycopg2.connect(DATABASE_URL, sslmode="require")
        raw.autocommit = True
        cur = raw.cursor()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    cur.execute(stmt)
                except Exception:
                    pass   # IF NOT EXISTS cubre la mayoría; ignorar duplicados
        raw.close()
        print("[DB] Esquema Supabase listo.")
    migrate_db()


def migrate_db():
    """Migraciones idempotentes — funciona en SQLite y PostgreSQL."""
    db = get_db()

    if DATABASE_URL:
        # PostgreSQL soporta ADD COLUMN IF NOT EXISTS
        for col_sql in [
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS propietario_id INTEGER REFERENCES propietarios(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN IF NOT EXISTS ruta_id INTEGER REFERENCES rutas(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN IF NOT EXISTS conductor_id INTEGER REFERENCES conductores(id)",
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS km_inicial INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE alistamiento_vehicular ADD COLUMN IF NOT EXISTS novedades TEXT",
            "ALTER TABLE intervenciones_tecnologia ADD COLUMN IF NOT EXISTS firma_base64 TEXT",
            "ALTER TABLE intervenciones_tecnologia ADD COLUMN IF NOT EXISTS firma_nombre TEXT",
            # Documentos legales — SCHEMA_VERSION 5
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS soat_vencimiento DATE",
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS tecno_vencimiento DATE",
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS tarjeta_op_vencimiento DATE",
            # Vínculo Propietario (usuario ↔ catálogo propietarios) — SCHEMA_VERSION 6
            "ALTER TABLE propietarios ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL",
        ]:
            # Commit/rollback por sentencia: en Postgres un fallo (p.ej. ALTER
            # sobre una tabla que aún no existe) aborta la transacción y haría
            # fallar en silencio TODO lo que sigue, incluidos los CREATE TABLE.
            try:
                db.execute(col_sql)
                db.commit()
            except Exception:
                db.rollback()
        # La tabla de alistamiento cambió de columnas (versión vieja inventada
        # → preguntas exactas del formulario). Si existe el esquema viejo, se
        # recrea desde cero para alinearlo con la nueva definición.
        try:
            row = db.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'alistamiento_vehicular' AND column_name = 'espejo_izq'"
            ).fetchone()
            if row:
                db.execute("DROP TABLE IF EXISTS alistamiento_vehicular")
            db.commit()
        except Exception:
            db.rollback()
        # Tablas del módulo de mantenimiento preventivo
        for tbl_sql in [
            """CREATE TABLE IF NOT EXISTS catalogo_mantenimiento (
                id              SERIAL PRIMARY KEY,
                sistema         TEXT    NOT NULL,
                nombre          TEXT    NOT NULL,
                tipo_intervalo  TEXT    NOT NULL CHECK (tipo_intervalo IN ('KM','FECHA')),
                orden           INTEGER NOT NULL DEFAULT 0,
                activo          INTEGER NOT NULL DEFAULT 1,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sistema, nombre)
            )""",
            """CREATE TABLE IF NOT EXISTS bus_mantenimiento_config (
                id                    SERIAL PRIMARY KEY,
                bus_id                INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                item_id               INTEGER NOT NULL REFERENCES catalogo_mantenimiento(id) ON DELETE CASCADE,
                intervalo_km          INTEGER,
                intervalo_dias        INTEGER,
                umbral_amarillo_km    INTEGER,
                umbral_rojo_km        INTEGER,
                umbral_amarillo_dias  INTEGER,
                umbral_rojo_dias      INTEGER,
                activo                INTEGER NOT NULL DEFAULT 1,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, item_id)
            )""",
            """CREATE TABLE IF NOT EXISTS bus_mantenimiento_historial (
                id              SERIAL PRIMARY KEY,
                bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                item_id         INTEGER NOT NULL REFERENCES catalogo_mantenimiento(id),
                fecha_realizado DATE    NOT NULL,
                km_realizado    INTEGER,
                realizado_por   TEXT,
                observaciones   TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS conductores (
                id         SERIAL PRIMARY KEY,
                nombre     TEXT    NOT NULL,
                cedula     TEXT,
                telefono   TEXT,
                activo     INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS despachador_rutas (
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                ruta_id    INTEGER NOT NULL REFERENCES rutas(id)    ON DELETE CASCADE,
                PRIMARY KEY (usuario_id, ruta_id)
            )""",
            """CREATE TABLE IF NOT EXISTS despacho_diario (
                id             SERIAL PRIMARY KEY,
                fecha          DATE    NOT NULL,
                bus_id         INTEGER NOT NULL REFERENCES buses(id),
                ruta_id        INTEGER REFERENCES rutas(id),
                conductor_id   INTEGER REFERENCES conductores(id),
                despachador_id INTEGER REFERENCES usuarios(id),
                estado         TEXT    NOT NULL DEFAULT 'trabajando'
                                       CHECK(estado IN ('trabajando','taller','descanso')),
                cerrado        INTEGER NOT NULL DEFAULT 0,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, fecha)
            )""",
            """CREATE TABLE IF NOT EXISTS alistamiento_vehicular (
                id                         SERIAL PRIMARY KEY,
                fecha                      DATE    NOT NULL,
                bus_id                     INTEGER NOT NULL REFERENCES buses(id),
                conductor_id               INTEGER REFERENCES conductores(id),
                despachador_id             INTEGER REFERENCES usuarios(id),
                lugar                      TEXT,
                retrovisores               TEXT CHECK(retrovisores               IN ('buena','mala','otros')),
                luz_estacionaria           TEXT CHECK(luz_estacionaria           IN ('buena','mala','otros')),
                luz_alta_baja              TEXT CHECK(luz_alta_baja              IN ('buena','mala','otros')),
                luz_reversa                TEXT CHECK(luz_reversa                IN ('buena','mala','otros')),
                logo_empresa               TEXT CHECK(logo_empresa               IN ('buena','mala','otros')),
                nivel_liquido_freno        TEXT CHECK(nivel_liquido_freno        IN ('buena','mala','otros')),
                nivel_deposito_hidraulico  TEXT CHECK(nivel_deposito_hidraulico  IN ('buena','mala','otros')),
                nivel_refrigerante         TEXT CHECK(nivel_refrigerante         IN ('buena','mala','otros')),
                presion_llantas            TEXT CHECK(presion_llantas            IN ('buena','mala','otros')),
                pito                       TEXT CHECK(pito                       IN ('buena','mala','otros')),
                stop                       TEXT CHECK(stop                       IN ('buena','mala','otros')),
                llantas_general            TEXT CHECK(llantas_general            IN ('buena','mala','otros')),
                direccionales              TEXT CHECK(direccionales              IN ('buena','mala','otros')),
                frenos_general             TEXT CHECK(frenos_general             IN ('buena','mala','otros')),
                nivel_liquido_aceite       TEXT CHECK(nivel_liquido_aceite       IN ('buena','mala','otros')),
                ballestas                  TEXT CHECK(ballestas                  IN ('buena','mala','otros')),
                fugas_aceite               TEXT CHECK(fugas_aceite               IN ('buena','mala','otros')),
                anclaje_bateria            TEXT CHECK(anclaje_bateria            IN ('buena','mala','otros')),
                dispositivo_luminoso       TEXT CHECK(dispositivo_luminoso       IN ('buena','mala','otros')),
                equipo_prevencion          TEXT CHECK(equipo_prevencion          IN ('buena','mala','otros')),
                cinturon_seguridad         TEXT CHECK(cinturon_seguridad         IN ('buena','mala','otros')),
                salidas_emergencia         TEXT CHECK(salidas_emergencia         IN ('buena','mala','otros')),
                aseo_vehiculo              TEXT CHECK(aseo_vehiculo              IN ('buena','mala','otros')),
                fugas_diafragmas           TEXT CHECK(fugas_diafragmas           IN ('buena','mala','otros')),
                asientos_anclados          TEXT CHECK(asientos_anclados          IN ('buena','mala','otros')),
                limpia_brillas             TEXT CHECK(limpia_brillas             IN ('buena','mala','otros')),
                condiciones_botiquin       TEXT CHECK(condiciones_botiquin       IN ('buena','mala','otros')),
                observaciones_adicionales  TEXT CHECK(observaciones_adicionales  IN ('buena','mala','otros')),
                lavada_primeriada          TEXT CHECK(lavada_primeriada          IN ('buena','mala','otros')),
                primeriada                 TEXT CHECK(primeriada                 IN ('buena','mala','otros')),
                nombre_responsable         TEXT,
                novedades                  TEXT,
                created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, fecha)
            )""",
            """CREATE TABLE IF NOT EXISTS gastos_mantenimiento (
                id                 SERIAL PRIMARY KEY,
                bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                fecha              DATE    NOT NULL,
                categoria          TEXT    NOT NULL,
                descripcion        TEXT,
                taller             TEXT,
                monto              NUMERIC(12,2) NOT NULL DEFAULT 0,
                comprobante_base64 TEXT,
                comprobante_mime   TEXT,
                comprobante_nombre TEXT,
                usuario_id         INTEGER REFERENCES usuarios(id),
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_gastos_bus   ON gastos_mantenimiento(bus_id)",
            "CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos_mantenimiento(fecha)",
            """CREATE TABLE IF NOT EXISTS intervenciones_tecnologia (
                id           SERIAL PRIMARY KEY,
                bus_id       INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                area         TEXT NOT NULL CHECK(area IN ('camaras','sensores')),
                fecha        DATE NOT NULL,
                tipo         TEXT NOT NULL,
                descripcion  TEXT,
                tecnico      TEXT NOT NULL,
                firma_base64 TEXT,
                firma_nombre TEXT,
                usuario_id   INTEGER REFERENCES usuarios(id),
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_tec_bus   ON intervenciones_tecnologia(bus_id)",
            "CREATE INDEX IF NOT EXISTS idx_tec_fecha ON intervenciones_tecnologia(fecha)",
            "CREATE INDEX IF NOT EXISTS idx_tec_area  ON intervenciones_tecnologia(area)",
            """CREATE TABLE IF NOT EXISTS intervencion_tecnologia_fotos (
                id              SERIAL PRIMARY KEY,
                intervencion_id INTEGER NOT NULL REFERENCES intervenciones_tecnologia(id) ON DELETE CASCADE,
                foto_base64     TEXT NOT NULL,
                orden           INTEGER NOT NULL DEFAULT 0
            )""",
            "CREATE INDEX IF NOT EXISTS idx_tec_fotos ON intervencion_tecnologia_fotos(intervencion_id)",
            """CREATE TABLE IF NOT EXISTS actividades_eds (
                id            SERIAL PRIMARY KEY,
                tipo          TEXT NOT NULL CHECK(tipo IN ('aseo_patio','canaletas','aseo_estacion','trampa_grasa','novedad')),
                fecha         DATE NOT NULL,
                descripcion   TEXT,
                realizado_por TEXT NOT NULL,
                usuario_id    INTEGER REFERENCES usuarios(id),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_eds_fecha ON actividades_eds(fecha)",
            "CREATE INDEX IF NOT EXISTS idx_eds_tipo  ON actividades_eds(tipo)",
            """CREATE TABLE IF NOT EXISTS actividad_eds_fotos (
                id           SERIAL PRIMARY KEY,
                actividad_id INTEGER NOT NULL REFERENCES actividades_eds(id) ON DELETE CASCADE,
                foto_base64  TEXT NOT NULL,
                orden        INTEGER NOT NULL DEFAULT 0
            )""",
            "CREATE INDEX IF NOT EXISTS idx_eds_fotos ON actividad_eds_fotos(actividad_id)",
            # Lavada Primeriada (área de lavado, solo micros) — SCHEMA_VERSION 7
            # tipo: 'lavada' (exterior), 'primeriada' (interior), 'ambas'
            # (las dos en el mismo asiento cuando se hicieron juntas), 'novedad'.
            """CREATE TABLE IF NOT EXISTS actividades_lavada (
                id            SERIAL PRIMARY KEY,
                bus_id        INTEGER NOT NULL REFERENCES buses(id),
                tipo          TEXT NOT NULL CHECK(tipo IN ('lavada','primeriada','ambas','novedad')),
                fecha         DATE NOT NULL,
                descripcion   TEXT,
                realizado_por TEXT NOT NULL,
                usuario_id    INTEGER REFERENCES usuarios(id),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_lavada_fecha ON actividades_lavada(fecha)",
            "CREATE INDEX IF NOT EXISTS idx_lavada_bus   ON actividades_lavada(bus_id)",
            "CREATE INDEX IF NOT EXISTS idx_lavada_tipo  ON actividades_lavada(tipo)",
            """CREATE TABLE IF NOT EXISTS actividad_lavada_fotos (
                id           SERIAL PRIMARY KEY,
                actividad_id INTEGER NOT NULL REFERENCES actividades_lavada(id) ON DELETE CASCADE,
                foto_base64  TEXT NOT NULL,
                orden        INTEGER NOT NULL DEFAULT 0
            )""",
            "CREATE INDEX IF NOT EXISTS idx_lavada_fotos ON actividad_lavada_fotos(actividad_id)",
            """CREATE TABLE IF NOT EXISTS puestos_trabajo (
                id          SERIAL PRIMARY KEY,
                nombre      TEXT NOT NULL UNIQUE,
                descripcion TEXT,
                activo      INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS chequeos_despachador (
                id                 SERIAL PRIMARY KEY,
                usuario_id         INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                puesto_id          INTEGER REFERENCES puestos_trabajo(id),
                fecha              DATE NOT NULL,
                hora_llegada       TEXT NOT NULL,
                lat_llegada        DOUBLE PRECISION NOT NULL,
                lng_llegada        DOUBLE PRECISION NOT NULL,
                precision_llegada  DOUBLE PRECISION,
                hora_salida        TEXT,
                lat_salida         DOUBLE PRECISION,
                lng_salida         DOUBLE PRECISION,
                precision_salida   DOUBLE PRECISION,
                minutos_trabajados INTEGER,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(usuario_id, fecha)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_chequeos_fecha ON chequeos_despachador(fecha)",
            "CREATE INDEX IF NOT EXISTS idx_mant_hist_bus_item ON bus_mantenimiento_historial(bus_id, item_id, fecha_realizado DESC)",
            # Va después de crear puestos_trabajo (la referencia debe existir)
            "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS puesto_id INTEGER REFERENCES puestos_trabajo(id)",
            # Rastreo GPS: vínculo bus↔dispositivo Traccar — SCHEMA_VERSION 3
            """CREATE TABLE IF NOT EXISTS gps_dispositivos (
                id          SERIAL PRIMARY KEY,
                device_id   TEXT NOT NULL UNIQUE,
                bus_id      INTEGER REFERENCES buses(id) ON DELETE SET NULL,
                activo      INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # Asignación manual de geocercas "Reloj" a cada bus — SCHEMA_VERSION 4
            """CREATE TABLE IF NOT EXISTS gps_bus_relojes (
                id              SERIAL PRIMARY KEY,
                bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                geocerca_id     INTEGER NOT NULL,
                geocerca_nombre TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, geocerca_id)
            )""",
        ]:
            try:
                db.execute(tbl_sql)
                db.commit()
            except Exception:
                db.rollback()
    else:
        # SQLite: CREATE TABLE + ALTER TABLE con try/except
        db.execute("""
            CREATE TABLE IF NOT EXISTS propietarios (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre     TEXT    NOT NULL,
                cedula     TEXT,
                telefono   TEXT,
                email      TEXT,
                activo     INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS tarifas (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo   TEXT    UNIQUE NOT NULL,
                label  TEXT    NOT NULL,
                valor  REAL    NOT NULL DEFAULT 0,
                activa INTEGER NOT NULL DEFAULT 1
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS usuario_buses (
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                bus_id     INTEGER NOT NULL REFERENCES buses(id)    ON DELETE CASCADE,
                PRIMARY KEY (usuario_id, bus_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS registros_movilidad (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id        INTEGER NOT NULL REFERENCES buses(id),
                fecha         DATE    NOT NULL,
                vueltas       INTEGER NOT NULL DEFAULT 0,
                pasajeros     INTEGER NOT NULL DEFAULT 0,
                km_recorridos REAL    NOT NULL DEFAULT 0,
                novedades     TEXT    NOT NULL DEFAULT '',
                usuario_id    INTEGER REFERENCES usuarios(id),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, fecha)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS catalogo_mantenimiento (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                sistema         TEXT    NOT NULL,
                nombre          TEXT    NOT NULL,
                tipo_intervalo  TEXT    NOT NULL CHECK (tipo_intervalo IN ('KM','FECHA')),
                orden           INTEGER NOT NULL DEFAULT 0,
                activo          INTEGER NOT NULL DEFAULT 1,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sistema, nombre)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS bus_mantenimiento_config (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id                INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                item_id               INTEGER NOT NULL REFERENCES catalogo_mantenimiento(id) ON DELETE CASCADE,
                intervalo_km          INTEGER,
                intervalo_dias        INTEGER,
                umbral_amarillo_km    INTEGER,
                umbral_rojo_km        INTEGER,
                umbral_amarillo_dias  INTEGER,
                umbral_rojo_dias      INTEGER,
                activo                INTEGER NOT NULL DEFAULT 1,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, item_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS bus_mantenimiento_historial (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                item_id         INTEGER NOT NULL REFERENCES catalogo_mantenimiento(id),
                fecha_realizado DATE    NOT NULL,
                km_realizado    INTEGER,
                realizado_por   TEXT,
                observaciones   TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS conductores (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre     TEXT    NOT NULL,
                cedula     TEXT,
                telefono   TEXT,
                activo     INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS despachador_rutas (
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                ruta_id    INTEGER NOT NULL REFERENCES rutas(id)    ON DELETE CASCADE,
                PRIMARY KEY (usuario_id, ruta_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS despacho_diario (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha          DATE    NOT NULL,
                bus_id         INTEGER NOT NULL REFERENCES buses(id),
                ruta_id        INTEGER REFERENCES rutas(id),
                conductor_id   INTEGER REFERENCES conductores(id),
                despachador_id INTEGER REFERENCES usuarios(id),
                estado         TEXT    NOT NULL DEFAULT 'trabajando'
                                       CHECK(estado IN ('trabajando','taller','descanso')),
                cerrado        INTEGER NOT NULL DEFAULT 0,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, fecha)
            )
        """)
        # Recrear la tabla de alistamiento si tiene el esquema viejo (columnas inventadas).
        try:
            cols = db.execute("PRAGMA table_info(alistamiento_vehicular)").fetchall()
            col_names = {(c["name"] if isinstance(c, dict) else c[1]) for c in cols}
            if "espejo_izq" in col_names:
                db.execute("DROP TABLE IF EXISTS alistamiento_vehicular")
        except Exception:
            pass
        db.execute("""
            CREATE TABLE IF NOT EXISTS alistamiento_vehicular (
                id                         INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha                      DATE    NOT NULL,
                bus_id                     INTEGER NOT NULL REFERENCES buses(id),
                conductor_id               INTEGER REFERENCES conductores(id),
                despachador_id             INTEGER REFERENCES usuarios(id),
                lugar                      TEXT,
                retrovisores               TEXT CHECK(retrovisores               IN ('buena','mala','otros')),
                luz_estacionaria           TEXT CHECK(luz_estacionaria           IN ('buena','mala','otros')),
                luz_alta_baja              TEXT CHECK(luz_alta_baja              IN ('buena','mala','otros')),
                luz_reversa                TEXT CHECK(luz_reversa                IN ('buena','mala','otros')),
                logo_empresa               TEXT CHECK(logo_empresa               IN ('buena','mala','otros')),
                nivel_liquido_freno        TEXT CHECK(nivel_liquido_freno        IN ('buena','mala','otros')),
                nivel_deposito_hidraulico  TEXT CHECK(nivel_deposito_hidraulico  IN ('buena','mala','otros')),
                nivel_refrigerante         TEXT CHECK(nivel_refrigerante         IN ('buena','mala','otros')),
                presion_llantas            TEXT CHECK(presion_llantas            IN ('buena','mala','otros')),
                pito                       TEXT CHECK(pito                       IN ('buena','mala','otros')),
                stop                       TEXT CHECK(stop                       IN ('buena','mala','otros')),
                llantas_general            TEXT CHECK(llantas_general            IN ('buena','mala','otros')),
                direccionales              TEXT CHECK(direccionales              IN ('buena','mala','otros')),
                frenos_general             TEXT CHECK(frenos_general             IN ('buena','mala','otros')),
                nivel_liquido_aceite       TEXT CHECK(nivel_liquido_aceite       IN ('buena','mala','otros')),
                ballestas                  TEXT CHECK(ballestas                  IN ('buena','mala','otros')),
                fugas_aceite               TEXT CHECK(fugas_aceite               IN ('buena','mala','otros')),
                anclaje_bateria            TEXT CHECK(anclaje_bateria            IN ('buena','mala','otros')),
                dispositivo_luminoso       TEXT CHECK(dispositivo_luminoso       IN ('buena','mala','otros')),
                equipo_prevencion          TEXT CHECK(equipo_prevencion          IN ('buena','mala','otros')),
                cinturon_seguridad         TEXT CHECK(cinturon_seguridad         IN ('buena','mala','otros')),
                salidas_emergencia         TEXT CHECK(salidas_emergencia         IN ('buena','mala','otros')),
                aseo_vehiculo              TEXT CHECK(aseo_vehiculo              IN ('buena','mala','otros')),
                fugas_diafragmas           TEXT CHECK(fugas_diafragmas           IN ('buena','mala','otros')),
                asientos_anclados          TEXT CHECK(asientos_anclados          IN ('buena','mala','otros')),
                limpia_brillas             TEXT CHECK(limpia_brillas             IN ('buena','mala','otros')),
                condiciones_botiquin       TEXT CHECK(condiciones_botiquin       IN ('buena','mala','otros')),
                observaciones_adicionales  TEXT CHECK(observaciones_adicionales  IN ('buena','mala','otros')),
                lavada_primeriada          TEXT CHECK(lavada_primeriada          IN ('buena','mala','otros')),
                primeriada                 TEXT CHECK(primeriada                 IN ('buena','mala','otros')),
                nombre_responsable         TEXT,
                novedades                  TEXT,
                created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, fecha)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS gastos_mantenimiento (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                fecha              DATE    NOT NULL,
                categoria          TEXT    NOT NULL,
                descripcion        TEXT,
                taller             TEXT,
                monto              NUMERIC(12,2) NOT NULL DEFAULT 0,
                comprobante_base64 TEXT,
                comprobante_mime   TEXT,
                comprobante_nombre TEXT,
                usuario_id         INTEGER REFERENCES usuarios(id),
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_gastos_bus   ON gastos_mantenimiento(bus_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos_mantenimiento(fecha)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS intervenciones_tecnologia (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id       INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                area         TEXT NOT NULL CHECK(area IN ('camaras','sensores')),
                fecha        DATE NOT NULL,
                tipo         TEXT NOT NULL,
                descripcion  TEXT,
                tecnico      TEXT NOT NULL,
                firma_base64 TEXT,
                firma_nombre TEXT,
                usuario_id   INTEGER REFERENCES usuarios(id),
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_tec_bus   ON intervenciones_tecnologia(bus_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tec_fecha ON intervenciones_tecnologia(fecha)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_tec_area  ON intervenciones_tecnologia(area)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS intervencion_tecnologia_fotos (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                intervencion_id INTEGER NOT NULL REFERENCES intervenciones_tecnologia(id) ON DELETE CASCADE,
                foto_base64     TEXT NOT NULL,
                orden           INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_tec_fotos ON intervencion_tecnologia_fotos(intervencion_id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS actividades_eds (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo          TEXT NOT NULL CHECK(tipo IN ('aseo_patio','canaletas','aseo_estacion','trampa_grasa','novedad')),
                fecha         DATE NOT NULL,
                descripcion   TEXT,
                realizado_por TEXT NOT NULL,
                usuario_id    INTEGER REFERENCES usuarios(id),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_eds_fecha ON actividades_eds(fecha)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_eds_tipo  ON actividades_eds(tipo)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS actividad_eds_fotos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                actividad_id INTEGER NOT NULL REFERENCES actividades_eds(id) ON DELETE CASCADE,
                foto_base64  TEXT NOT NULL,
                orden        INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_eds_fotos ON actividad_eds_fotos(actividad_id)")
        # Lavada Primeriada (área de lavado, solo micros) — SCHEMA_VERSION 7
        # tipo: 'lavada' (exterior), 'primeriada' (interior), 'ambas'
        # (las dos en el mismo asiento cuando se hicieron juntas), 'novedad'.
        db.execute("""
            CREATE TABLE IF NOT EXISTS actividades_lavada (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id        INTEGER NOT NULL REFERENCES buses(id),
                tipo          TEXT NOT NULL CHECK(tipo IN ('lavada','primeriada','ambas','novedad')),
                fecha         DATE NOT NULL,
                descripcion   TEXT,
                realizado_por TEXT NOT NULL,
                usuario_id    INTEGER REFERENCES usuarios(id),
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_lavada_fecha ON actividades_lavada(fecha)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_lavada_bus   ON actividades_lavada(bus_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_lavada_tipo  ON actividades_lavada(tipo)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS actividad_lavada_fotos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                actividad_id INTEGER NOT NULL REFERENCES actividades_lavada(id) ON DELETE CASCADE,
                foto_base64  TEXT NOT NULL,
                orden        INTEGER NOT NULL DEFAULT 0
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_lavada_fotos ON actividad_lavada_fotos(actividad_id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS puestos_trabajo (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre      TEXT NOT NULL UNIQUE,
                descripcion TEXT,
                activo      INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS chequeos_despachador (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id         INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                puesto_id          INTEGER REFERENCES puestos_trabajo(id),
                fecha              DATE NOT NULL,
                hora_llegada       TEXT NOT NULL,
                lat_llegada        REAL NOT NULL,
                lng_llegada        REAL NOT NULL,
                precision_llegada  REAL,
                hora_salida        TEXT,
                lat_salida         REAL,
                lng_salida         REAL,
                precision_salida   REAL,
                minutos_trabajados INTEGER,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(usuario_id, fecha)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_chequeos_fecha ON chequeos_despachador(fecha)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mant_hist_bus_item ON bus_mantenimiento_historial(bus_id, item_id, fecha_realizado DESC)")
        # Rastreo GPS: vínculo bus↔dispositivo Traccar — SCHEMA_VERSION 3
        db.execute("""
            CREATE TABLE IF NOT EXISTS gps_dispositivos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id   TEXT NOT NULL UNIQUE,
                bus_id      INTEGER REFERENCES buses(id) ON DELETE SET NULL,
                activo      INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Asignación manual de geocercas "Reloj" a cada bus — SCHEMA_VERSION 4
        db.execute("""
            CREATE TABLE IF NOT EXISTS gps_bus_relojes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
                geocerca_id     INTEGER NOT NULL,
                geocerca_nombre TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bus_id, geocerca_id)
            )
        """)
        for col_sql in [
            "ALTER TABLE buses ADD COLUMN propietario_id INTEGER REFERENCES propietarios(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN ruta_id INTEGER REFERENCES rutas(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN conductor_id INTEGER REFERENCES conductores(id)",
            "ALTER TABLE buses ADD COLUMN km_inicial INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE alistamiento_vehicular ADD COLUMN novedades TEXT",
            "ALTER TABLE usuarios ADD COLUMN puesto_id INTEGER REFERENCES puestos_trabajo(id)",
            "ALTER TABLE intervenciones_tecnologia ADD COLUMN firma_base64 TEXT",
            "ALTER TABLE intervenciones_tecnologia ADD COLUMN firma_nombre TEXT",
            # Documentos legales — SCHEMA_VERSION 5
            "ALTER TABLE buses ADD COLUMN soat_vencimiento DATE",
            "ALTER TABLE buses ADD COLUMN tecno_vencimiento DATE",
            "ALTER TABLE buses ADD COLUMN tarjeta_op_vencimiento DATE",
            # Vínculo Propietario (usuario ↔ catálogo propietarios) — SCHEMA_VERSION 6
            "ALTER TABLE propietarios ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id)",
        ]:
            try:
                db.execute(col_sql)
            except Exception:
                pass

    # Backfill: cada usuario con rol='Propietario' debe tener una fila en
    # el catálogo `propietarios` (así aparece en el select del bus). Se
    # ejecuta cada vez que se migra el schema — idempotente porque solo
    # inserta los que aún no tienen usuario_id vinculado.
    try:
        pendientes = db.execute(
            """SELECT u.id, u.nombre
                 FROM usuarios u
            LEFT JOIN propietarios p ON p.usuario_id = u.id
                WHERE u.rol = 'Propietario' AND u.activo = 1 AND p.id IS NULL"""
        ).fetchall()
        for u in pendientes:
            urow = dict(u)
            db.execute(
                "INSERT INTO propietarios (nombre, activo, usuario_id) VALUES (?, 1, ?)",
                (urow["nombre"], urow["id"]),
            )
    except Exception as e:
        print(f"[migrate_db] backfill propietarios: {e}")

    # Insertar tarifas iniciales si la tabla está vacía (ambos motores)
    count = db.execute("SELECT COUNT(*) FROM tarifas").fetchone()
    total = list(count.values())[0] if isinstance(count, dict) else count[0]
    if total == 0:
        db.executemany(
            "INSERT INTO tarifas (tipo, label, valor) VALUES (?,?,?)",
            [
                ("normal",       "Pasajero Normal", 3200),
                ("estudiante",   "Estudiante",       1800),
                ("adulto_mayor", "Adulto Mayor",     1500),
            ],
        )

    # Seed catálogo de mantenimiento si está vacío (33 ítems del Excel BEA)
    try:
        cnt_cat = db.execute("SELECT COUNT(*) FROM catalogo_mantenimiento").fetchone()
        cat_total = list(cnt_cat.values())[0] if isinstance(cnt_cat, dict) else cnt_cat[0]
    except Exception:
        cat_total = -1
    if cat_total == 0:
        seed = [
            ('MOTOR', 'Kit Cambio de aceite motor y filtro', 'KM', 10),
            ('MOTOR', 'Correas Alternador',                  'KM', 20),
            ('MOTOR', 'Filtro Aire (motor)',                 'KM', 30),
            ('MOTOR', 'Filtro Combustible',                  'KM', 40),
            ('MOTOR', 'Afinacion motor (Calibrar Valvulas)', 'KM', 50),
            ('MOTOR', 'Casquetes',                           'KM', 60),
            ('CARDAN/EJE CENTRAL', 'Cardan',            'KM', 10),
            ('CARDAN/EJE CENTRAL', 'Cruceta cardan',    'KM', 20),
            ('CARDAN/EJE CENTRAL', 'Soportes y caucho', 'KM', 30),
            ('CARDAN/EJE CENTRAL', 'Tornilleria',       'KM', 40),
            ('FRENOS', 'Revision de Bandas, rodamientos y retenedores', 'KM',    10),
            ('FRENOS', 'Fugas de Aire',                                 'FECHA', 20),
            ('FRENOS', 'Manguera Freno',                                'KM',    30),
            ('SUSPENSION', 'Cambio de bujes de Muelle', 'KM', 10),
            ('SUSPENSION', 'Bujes y Pasadores',         'KM', 20),
            ('SUSPENSION', 'Grapas',                    'KM', 30),
            ('SUSPENSION', 'Amortiguadores',            'KM', 40),
            ('SUSPENSION', 'Barra Estabilizadora',      'KM', 50),
            ('ELECTRICO', 'Luces',   'FECHA', 10),
            ('ELECTRICO', 'Bateria', 'FECHA', 20),
            ('REFRIGERACION', 'Mangueras',   'KM', 10),
            ('REFRIGERACION', 'Radiador',    'KM', 20),
            ('REFRIGERACION', 'Intercooler', 'KM', 30),
            ('LUBRICACION', 'Engrase general (niveles aceite, transmision, diferencial y motor; refrigerante y liquidos de freno)', 'KM', 10),
            ('ACEITE', 'Cambio de aceite de motor', 'KM', 10),
        ]
        try:
            db.executemany(
                "INSERT INTO catalogo_mantenimiento (sistema, nombre, tipo_intervalo, orden) VALUES (?,?,?,?)",
                seed,
            )
        except Exception:
            pass

    # Sincroniza las placas reales de la flota (idempotente: solo actualiza
    # las que difieren). Corrige las placas de relleno heredadas en producción.
    try:
        from placas_reales import PLACAS_REALES
        actuales = {r["numero"]: r["placa"]
                    for r in db.execute("SELECT numero, placa FROM buses").fetchall()}
        for numero, placa_real in PLACAS_REALES.items():
            if actuales.get(numero) != placa_real:
                db.execute("UPDATE buses SET placa = ? WHERE numero = ?", (placa_real, numero))
    except Exception as e:
        print(f"[migrate_db] sync placas: {e}")

    # Registrar la versión migrada: mientras coincida con SCHEMA_VERSION,
    # los próximos init_db() retornan con una sola consulta.
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
    )
    db.execute(
        "INSERT INTO schema_version (id, version) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET version = excluded.version",
        (SCHEMA_VERSION,),
    )

    db.commit()
    db.close()


# ──────────────────────────────────────────
#  Auth
# ──────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if not _check_rate_limit(ip):
        return jsonify({"error": "Demasiados intentos. Espera 5 minutos."}), 429

    data = request.get_json(force=True)
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "Por favor completa ambos campos."}), 400

    db = get_db()
    user = db.execute(
        "SELECT * FROM usuarios WHERE username = ? AND activo = 1",
        (username,),
    ).fetchone()

    if not user:
        db.close()
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401

    stored_pw = user["password"]
    # Migración perezosa: si la contraseña no está hasheada, verificar en texto plano y hashear
    if stored_pw.startswith("pbkdf2:") or stored_pw.startswith("scrypt:"):
        valid = check_password_hash(stored_pw, password)
    else:
        valid = (stored_pw == password)
        if valid:
            # Hashear y guardar para la próxima vez. Si la escritura falla (BD en
            # solo lectura, pooler, etc.) NO se debe bloquear el inicio de sesión:
            # el usuario ya se autenticó. Se registra el error para diagnóstico.
            try:
                hashed = generate_password_hash(password, method='pbkdf2:sha256')
                db.execute("UPDATE usuarios SET password = ? WHERE id = ?", (hashed, user["id"]))
                db.commit()
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                print(f"[login] no se pudo migrar la contraseña del usuario {user['id']}: {e}")

    if not valid:
        db.close()
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401

    rol = user["rol"]
    bus_ids = []
    if rol in ("Propietario", "Técnico Mant."):
        rows = db.execute(
            "SELECT bus_id FROM usuario_buses WHERE usuario_id = ?", (user["id"],)
        ).fetchall()
        bus_ids = [r["bus_id"] for r in rows]

    db.close()

    # Generar token JWT
    payload = {
        "user_id": user["id"],
        "rol":     rol,
        "exp":     datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    token = _jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    return jsonify({
        "token":        token,
        "id":           user["id"],
        "username":     user["username"],
        "nombre":       user["nombre"],
        "rol":          rol,
        "iniciales":    user["iniciales"],
        "color":        user["color"],
        "allowedViews": ROLE_VIEWS.get(rol, []),
        "bus_ids":      bus_ids,
    })


# ──────────────────────────────────────────
#  Verificar sesión actual
# ──────────────────────────────────────────

@app.route("/api/me", methods=["GET"])
@require_auth
def get_current_user():
    db = get_db()
    user = db.execute(
        "SELECT id, username, nombre, rol, iniciales, color FROM usuarios WHERE id = ? AND activo = 1",
        (request.jwt_user_id,),
    ).fetchone()
    db.close()

    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 404

    rol = user["rol"]
    allowed_views = ROLE_VIEWS.get(rol, [])

    return jsonify({
        "id": user["id"],
        "username": user["username"],
        "nombre": user["nombre"],
        "rol": rol,
        "iniciales": user["iniciales"],
        "color": user["color"],
        "allowedViews": allowed_views,
        # Feature flag del chatbot (Fase 1): off salvo que FEATURE_CHATBOT sea true.
        "chatbot_enabled": _feature_chatbot_enabled(),
    })


def _feature_chatbot_enabled():
    return os.environ.get("FEATURE_CHATBOT", "false").strip().lower() in ("1", "true", "yes", "on")


# ──────────────────────────────────────────
#  Chatbot con IA (Fase 1) — /api/chat
# ──────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
@require_auth
def chat():
    """Chat con streaming (SSE) y tool calling.

    Valida sesión (require_auth), arma el contexto con la identidad del usuario
    y transmite la respuesta del LLM token a token. Las tools consultan la BD
    respetando el rol del usuario autenticado.
    """
    if not _feature_chatbot_enabled():
        return jsonify({"error": "El chatbot no está habilitado."}), 404

    data = request.get_json(force=True, silent=True) or {}
    raw_messages = data.get("messages", [])

    # Sanea el historial: solo roles válidos y contenido de texto.
    messages = []
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})

    if not messages or messages[-1]["role"] != "user":
        return jsonify({"error": "Falta un mensaje del usuario."}), 400

    # Import perezoso: solo se cargan los SDKs de IA cuando se usa el chat.
    from ai.provider import get_provider, SYSTEM_PROMPT
    from ai.tools import REGISTRY

    ctx = {
        "user_id": request.jwt_user_id,
        "rol": request.jwt_user_rol,
        "get_db": get_db,
        "hoy": hoy_bogota(),
    }

    try:
        provider = get_provider()
    except Exception as e:
        return jsonify({"error": f"Configuración de IA inválida: {e}"}), 500

    def gen():
        try:
            for ev in provider.stream(SYSTEM_PROMPT, messages, REGISTRY, ctx):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = {"type": "error", "error": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(gen()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────
#  Buses
# ──────────────────────────────────────────

@app.route("/api/buses", methods=["GET"])
@require_auth
def get_buses():
    user_id = request.args.get("user_id", type=int)
    db = get_db()
    if user_id:
        user = db.execute(
            "SELECT rol FROM usuarios WHERE id = ? AND activo = 1", (user_id,)
        ).fetchone()
        if user and user["rol"] in ("Propietario", "Técnico Mant."):
            rows = db.execute(
                """SELECT b.* FROM buses b
                   JOIN usuario_buses ub ON ub.bus_id = b.id
                   WHERE ub.usuario_id = ?
                   ORDER BY b.numero""",
                (user_id,),
            ).fetchall()
            db.close()
            return jsonify([dict(r) for r in rows])
    rows = db.execute("SELECT * FROM buses ORDER BY numero").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/buses/<int:bus_id>", methods=["GET"])
@require_auth
def get_bus(bus_id):
    db = get_db()
    row = db.execute("SELECT * FROM buses WHERE id = ?", (bus_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "Bus no encontrado"}), 404
    return jsonify(dict(row))


@app.route("/api/buses", methods=["POST"])
@require_role("Administrador")
def create_bus():
    data = request.get_json(force=True)
    numero     = data.get("numero")
    placa      = data.get("placa", "")
    modelo     = data.get("modelo", "")
    grupo      = data.get("grupo", "A")
    estado     = data.get("estado", "activo")
    km         = data.get("km_actuales", 0)
    prop_id    = data.get("propietario_id") or None
    soat       = data.get("soat_vencimiento") or None
    tecno      = data.get("tecno_vencimiento") or None
    tarjeta_op = data.get("tarjeta_op_vencimiento") or None

    if not numero:
        return jsonify({"error": "El número de bus es requerido"}), 400

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO buses (numero, placa, modelo, grupo, estado, km_actuales, propietario_id, "
            "soat_vencimiento, tecno_vencimiento, tarjeta_op_vencimiento) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (numero, placa, modelo, grupo, estado, km, prop_id, soat, tecno, tarjeta_op),
        )
        db.commit()
        new_id = cursor.lastrowid
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/buses/<int:bus_id>", methods=["PUT"])
@require_role("Administrador")
def update_bus(bus_id):
    data    = request.get_json(force=True)
    db      = get_db()
    bus     = db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        db.close()
        return jsonify({"error": "Bus no encontrado"}), 404

    fields = [
        "numero", "placa", "modelo", "grupo", "estado", "km_actuales", "propietario_id",
        "soat_vencimiento", "tecno_vencimiento", "tarjeta_op_vencimiento",
    ]
    nullable = ("propietario_id", "soat_vencimiento", "tecno_vencimiento", "tarjeta_op_vencimiento")
    updates, values = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f} = ?")
            values.append(data[f] if data[f] != "" or f not in nullable else None)

    if not updates:
        db.close()
        return jsonify({"error": "Sin campos para actualizar"}), 400

    values.append(bus_id)
    try:
        db.execute(f"UPDATE buses SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400
    db.close()
    return jsonify({"ok": True})


@app.route("/api/buses/<int:bus_id>", methods=["DELETE"])
@require_role("Administrador")
def delete_bus(bus_id):
    db = get_db()
    bus = db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        db.close()
        return jsonify({"error": "Bus no encontrado"}), 404

    has_records = db.execute(
        "SELECT 1 FROM registros_pasajeros WHERE bus_id = ? LIMIT 1", (bus_id,)
    ).fetchone()
    if has_records:
        db.close()
        return jsonify({"error": "No se puede eliminar: el bus tiene registros de pasajeros asociados"}), 409

    db.execute("DELETE FROM estado_mantenimiento WHERE bus_id = ?", (bus_id,))
    db.execute("DELETE FROM registros_mantenimiento WHERE bus_id = ?", (bus_id,))
    db.execute("DELETE FROM buses WHERE id = ?", (bus_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Propietarios
# ──────────────────────────────────────────

@app.route("/api/propietarios", methods=["GET"])
@require_auth
def get_propietarios():
    db = get_db()
    rows = db.execute(
        """
        SELECT p.*,
               (SELECT COUNT(*) FROM buses b WHERE b.propietario_id = p.id) AS buses_count
        FROM propietarios p
        WHERE p.activo = 1
        ORDER BY p.nombre
        """
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ──────────────────────────────────────────
#  Tarifas
# ──────────────────────────────────────────

@app.route("/api/tarifas", methods=["GET"])
@require_auth
def get_tarifas():
    db   = get_db()
    rows = db.execute("SELECT * FROM tarifas ORDER BY id").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tarifas/<int:tarifa_id>", methods=["PUT"])
@require_role("Administrador")
def update_tarifa(tarifa_id):
    data  = request.get_json(force=True)
    db    = get_db()
    row   = db.execute("SELECT id FROM tarifas WHERE id = ?", (tarifa_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Tarifa no encontrada"}), 404

    db.execute(
        "UPDATE tarifas SET label=?, valor=? WHERE id=?",
        (data.get("label", ""), data.get("valor", 0), tarifa_id),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Rutas
# ──────────────────────────────────────────

@app.route("/api/rutas", methods=["GET"])
@require_auth
def get_rutas():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM rutas WHERE activa = 1 ORDER BY grupo, id"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/rutas/all", methods=["GET"])
@require_auth
def get_rutas_all():
    db   = get_db()
    rows = db.execute("SELECT * FROM rutas ORDER BY grupo, id").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/rutas", methods=["POST"])
@require_role("Administrador")
def create_ruta():
    data   = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400

    grupo = data.get("grupo", "A")
    db    = get_db()
    cursor = db.execute(
        "INSERT INTO rutas (nombre, descripcion, grupo, color, activa) VALUES (?,?,?,?,?)",
        (nombre, data.get("descripcion", ""), grupo, data.get("color", "#6366f1"), data.get("activa", 1)),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/rutas/<int:ruta_id>", methods=["PUT"])
@require_role("Administrador")
def update_ruta(ruta_id):
    data = request.get_json(force=True)
    db   = get_db()
    row  = db.execute("SELECT id FROM rutas WHERE id = ?", (ruta_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Ruta no encontrada"}), 404

    db.execute(
        "UPDATE rutas SET nombre=?, descripcion=?, grupo=?, color=?, activa=? WHERE id=?",
        (data.get("nombre", ""), data.get("descripcion", ""), data.get("grupo", "A"),
         data.get("color", "#6366f1"), data.get("activa", 1), ruta_id),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/rutas/<int:ruta_id>", methods=["DELETE"])
@require_role("Administrador")
def delete_ruta(ruta_id):
    db  = get_db()
    row = db.execute("SELECT id FROM rutas WHERE id = ?", (ruta_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Ruta no encontrada"}), 404

    has_records = db.execute(
        "SELECT 1 FROM registros_pasajeros WHERE ruta_id = ? LIMIT 1", (ruta_id,)
    ).fetchone()
    if has_records:
        db.execute("UPDATE rutas SET activa = 0 WHERE id = ?", (ruta_id,))
        db.commit()
        db.close()
        return jsonify({"ok": True, "warning": "Ruta desactivada (tiene registros de pasajeros)"})

    db.execute("DELETE FROM rutas WHERE id = ?", (ruta_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Conductores (catálogo)
# ──────────────────────────────────────────

@app.route("/api/conductores", methods=["GET"])
@require_auth
def get_conductores():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM conductores WHERE activo = 1 ORDER BY nombre"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


def _norm_nombre_conductor(s):
    """Normaliza un nombre para comparar: mayúsculas y espacios colapsados."""
    return " ".join((s or "").split()).upper()


def _buscar_conductor_duplicado(db, nombre, cedula, excluir_id=None):
    """Devuelve el conductor activo que ya tiene la misma cédula o el mismo
    nombre (normalizado), o None si no hay duplicado. La comparación se hace
    en Python para que funcione igual en SQLite y Postgres (acentos, Ñ)."""
    rows = db.execute(
        "SELECT id, nombre, cedula FROM conductores WHERE activo = 1"
    ).fetchall()
    nombre_norm = _norm_nombre_conductor(nombre)
    cedula_norm = (cedula or "").strip()
    for r in rows:
        if excluir_id is not None and r["id"] == excluir_id:
            continue
        if cedula_norm and (r["cedula"] or "").strip() == cedula_norm:
            return dict(r)
        if nombre_norm and _norm_nombre_conductor(r["nombre"]) == nombre_norm:
            return dict(r)
    return None


@app.route("/api/conductores", methods=["POST"])
@require_role("Administrador")
def create_conductor():
    data   = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    cedula = (data.get("cedula") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400

    db  = get_db()
    dup = _buscar_conductor_duplicado(db, nombre, cedula)
    if dup:
        db.close()
        detalle = f"{dup['nombre']}" + (f" (cédula {dup['cedula']})" if (dup.get("cedula") or "").strip() else "")
        return jsonify({"error": f"Este conductor ya está dado de alta: {detalle}"}), 409

    cursor = db.execute(
        "INSERT INTO conductores (nombre, cedula, telefono, activo) VALUES (?,?,?,?)",
        (nombre, cedula, data.get("telefono", ""), data.get("activo", 1)),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/conductores/<int:cid>", methods=["PUT"])
@require_role("Administrador")
def update_conductor(cid):
    data = request.get_json(force=True)
    db   = get_db()
    if not db.execute("SELECT id FROM conductores WHERE id = ?", (cid,)).fetchone():
        db.close()
        return jsonify({"error": "Conductor no encontrado"}), 404

    dup = _buscar_conductor_duplicado(db, data.get("nombre", ""), data.get("cedula", ""), excluir_id=cid)
    if dup:
        db.close()
        detalle = f"{dup['nombre']}" + (f" (cédula {dup['cedula']})" if (dup.get("cedula") or "").strip() else "")
        return jsonify({"error": f"Ya hay otro conductor dado de alta con esos datos: {detalle}"}), 409

    db.execute(
        "UPDATE conductores SET nombre=?, cedula=?, telefono=?, activo=? WHERE id=?",
        (data.get("nombre", ""), data.get("cedula", ""), data.get("telefono", ""),
         data.get("activo", 1), cid),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/conductores/<int:cid>", methods=["DELETE"])
@require_role("Administrador")
def delete_conductor(cid):
    db = get_db()
    db.execute("UPDATE conductores SET activo = 0 WHERE id = ?", (cid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Puestos de trabajo (catálogo)
# ──────────────────────────────────────────

@app.route("/api/puestos", methods=["GET"])
@require_auth
def get_puestos():
    db   = get_db()
    rows = db.execute(
        "SELECT id, nombre, descripcion, activo FROM puestos_trabajo ORDER BY nombre"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/puestos", methods=["POST"])
@require_role("Administrador")
def create_puesto():
    data   = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre del puesto es requerido"}), 400

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO puestos_trabajo (nombre, descripcion, activo) VALUES (?,?,?)",
            (nombre, (data.get("descripcion") or "").strip(), data.get("activo", 1)),
        )
        db.commit()
        new_id = cursor.lastrowid
    except Exception:
        db.close()
        return jsonify({"error": "Ya existe un puesto con ese nombre"}), 400
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/puestos/<int:pid>", methods=["PUT"])
@require_role("Administrador")
def update_puesto(pid):
    data = request.get_json(force=True)
    db   = get_db()
    if not db.execute("SELECT id FROM puestos_trabajo WHERE id = ?", (pid,)).fetchone():
        db.close()
        return jsonify({"error": "Puesto no encontrado"}), 404

    allowed = ["nombre", "descripcion", "activo"]
    updates, values = [], []
    for f in allowed:
        if f in data:
            updates.append(f"{f} = ?")
            values.append(data[f])
    if updates:
        values.append(pid)
        try:
            db.execute(f"UPDATE puestos_trabajo SET {', '.join(updates)} WHERE id = ?", values)
            db.commit()
        except Exception:
            db.close()
            return jsonify({"error": "Ya existe un puesto con ese nombre"}), 400
    db.close()
    return jsonify({"ok": True})


@app.route("/api/puestos/<int:pid>", methods=["DELETE"])
@require_role("Administrador")
def delete_puesto(pid):
    db = get_db()
    db.execute("UPDATE puestos_trabajo SET activo = 0 WHERE id = ?", (pid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Chequeo de despachadores (llegada/salida con GPS)
# ──────────────────────────────────────────

def _validar_gps(data):
    """Valida lat/lng del body. Devuelve (lat, lng, precision) o None si inválido."""
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    try:
        prec = float(data.get("precision")) if data.get("precision") is not None else None
    except (TypeError, ValueError):
        prec = None
    return (lat, lng, prec)


def _chequeo_de(db, uid, fecha):
    """Chequeo del usuario para una fecha, con nombre de puesto, o None."""
    row = db.execute(
        """SELECT c.*, p.nombre AS puesto_nombre
           FROM chequeos_despachador c
           LEFT JOIN puestos_trabajo p ON p.id = c.puesto_id
           WHERE c.usuario_id = ? AND c.fecha = ?""",
        (uid, fecha),
    ).fetchone()
    return dict(row) if row else None


@app.route("/api/chequeo/hoy", methods=["GET"])
@require_role(*ROLES_CHEQUEO)
def get_chequeo_hoy():
    uid   = request.jwt_user_id
    fecha = hoy_bogota()
    db    = get_db()
    u = db.execute(
        """SELECT u.puesto_id, p.nombre AS puesto_nombre
           FROM usuarios u LEFT JOIN puestos_trabajo p ON p.id = u.puesto_id
           WHERE u.id = ?""",
        (uid,),
    ).fetchone()
    chequeo = _chequeo_de(db, uid, fecha)
    db.close()
    puesto = None
    if u and u["puesto_id"]:
        puesto = {"id": u["puesto_id"], "nombre": u["puesto_nombre"]}
    return jsonify({"fecha": fecha, "puesto": puesto, "chequeo": chequeo})


@app.route("/api/chequeo/llegada", methods=["POST"])
@require_role(*ROLES_CHEQUEO)
def chequeo_llegada():
    data = request.get_json(force=True)
    gps  = _validar_gps(data)
    if not gps:
        return jsonify({"error": "Se requiere la ubicación GPS para marcar"}), 400
    lat, lng, prec = gps

    uid   = request.jwt_user_id
    fecha = hoy_bogota()
    db    = get_db()

    previo = _chequeo_de(db, uid, fecha)
    if previo:
        db.close()
        return jsonify({"error": f"Ya marcaste tu llegada hoy a las {previo['hora_llegada'][:5]}"}), 409

    # Puesto elegido por el despachador al marcar; si no manda ninguno,
    # se usa el asignado en el catálogo (o queda sin puesto).
    puesto_id = data.get("puesto_id") or None
    if puesto_id:
        try:
            puesto_id = int(puesto_id)
        except (TypeError, ValueError):
            puesto_id = None
        valido = puesto_id and db.execute(
            "SELECT id FROM puestos_trabajo WHERE id = ? AND activo = 1", (puesto_id,)
        ).fetchone()
        if not valido:
            db.close()
            return jsonify({"error": "Selecciona un puesto de trabajo válido"}), 400
    else:
        u = db.execute("SELECT puesto_id FROM usuarios WHERE id = ?", (uid,)).fetchone()
        puesto_id = u["puesto_id"] if u else None
    try:
        db.execute(
            """INSERT INTO chequeos_despachador
               (usuario_id, puesto_id, fecha, hora_llegada, lat_llegada, lng_llegada, precision_llegada)
               VALUES (?,?,?,?,?,?,?)""",
            (uid, puesto_id, fecha, ahora_bogota(), lat, lng, prec),
        )
        db.commit()
    except Exception:
        # Carrera con el UNIQUE(usuario_id, fecha): otro request marcó primero
        db.close()
        return jsonify({"error": "Ya marcaste tu llegada hoy"}), 409

    chequeo = _chequeo_de(db, uid, fecha)
    db.close()
    return jsonify({"ok": True, "chequeo": chequeo}), 201


@app.route("/api/chequeo/salida", methods=["POST"])
@require_role(*ROLES_CHEQUEO)
def chequeo_salida():
    gps = _validar_gps(request.get_json(force=True))
    if not gps:
        return jsonify({"error": "Se requiere la ubicación GPS para marcar"}), 400
    lat, lng, prec = gps

    uid   = request.jwt_user_id
    fecha = hoy_bogota()
    db    = get_db()

    chequeo = _chequeo_de(db, uid, fecha)
    if not chequeo:
        db.close()
        return jsonify({"error": "Primero debes marcar tu llegada"}), 409
    if chequeo["hora_salida"]:
        db.close()
        return jsonify({"error": f"Ya marcaste tu salida hoy a las {chequeo['hora_salida'][:5]}"}), 409

    hora_salida = ahora_bogota()
    h1, m1, s1 = [int(x) for x in chequeo["hora_llegada"].split(":")]
    h2, m2, s2 = [int(x) for x in hora_salida.split(":")]
    minutos = max(0, ((h2 * 3600 + m2 * 60 + s2) - (h1 * 3600 + m1 * 60 + s1)) // 60)

    db.execute(
        """UPDATE chequeos_despachador
           SET hora_salida = ?, lat_salida = ?, lng_salida = ?, precision_salida = ?,
               minutos_trabajados = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (hora_salida, lat, lng, prec, minutos, chequeo["id"]),
    )
    db.commit()
    chequeo = _chequeo_de(db, uid, fecha)
    db.close()
    return jsonify({"ok": True, "chequeo": chequeo})


@app.route("/api/chequeo/historial", methods=["GET"])
@require_role(*ROLES_CHEQUEO)
def chequeo_historial():
    uid = request.jwt_user_id
    rol = request.jwt_user_rol

    if rol in ("Administrador", "Jefe de Ruta"):
        desde = request.args.get("desde") or hoy_bogota()
        hasta = request.args.get("hasta") or hoy_bogota()
        filtro_usuario, params_extra = "", []
    else:
        # El despachador solo ve su propio historial (últimos 7 días por defecto)
        default_desde = ((datetime.utcnow() - timedelta(hours=5)) - timedelta(days=6)).date().isoformat()
        desde = request.args.get("desde") or default_desde
        hasta = request.args.get("hasta") or hoy_bogota()
        filtro_usuario, params_extra = " AND c.usuario_id = ?", [uid]

    db   = get_db()
    rows = db.execute(
        f"""SELECT c.id, c.fecha, c.hora_llegada, c.hora_salida, c.minutos_trabajados,
                   c.lat_llegada, c.lng_llegada, c.precision_llegada,
                   c.lat_salida, c.lng_salida, c.precision_salida,
                   u.nombre AS despachador, p.nombre AS puesto
            FROM chequeos_despachador c
            JOIN usuarios u ON u.id = c.usuario_id
            LEFT JOIN puestos_trabajo p ON p.id = c.puesto_id
            WHERE c.fecha BETWEEN ? AND ?{filtro_usuario}
            ORDER BY c.fecha DESC, c.hora_llegada""",
        [desde, hasta] + params_extra,
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        # En Postgres DATE llega como objeto date → normalizar a ISO
        if d.get("fecha") is not None and not isinstance(d["fecha"], str):
            d["fecha"] = d["fecha"].isoformat()
        out.append(d)
    return jsonify(out)


# ──────────────────────────────────────────
#  Despacho diario
# ──────────────────────────────────────────

def _rutas_de_despachador(db, uid):
    """Rutas asignadas a un despachador (lista de dicts id/nombre/grupo/color)."""
    return db.execute(
        """SELECT r.id, r.nombre, r.grupo, r.color
           FROM despachador_rutas dr
           JOIN rutas r ON r.id = dr.ruta_id
           WHERE dr.usuario_id = ?
           ORDER BY r.grupo, r.nombre""",
        (uid,),
    ).fetchall()


@app.route("/api/despacho", methods=["GET"])
@require_auth
def get_despacho():
    """Devuelve las rutas y los buses (con su estado del día) que administra el usuario.
    Despachador → solo buses de los grupos de sus rutas asignadas. Admin → toda la flota."""
    fecha = request.args.get("fecha", date.today().isoformat())
    db    = get_db()
    rol   = getattr(request, "jwt_user_rol", None)
    uid   = getattr(request, "jwt_user_id", None)

    if rol == "Despachador":
        rutas  = [dict(r) for r in _rutas_de_despachador(db, uid)]
        grupos = sorted({r["grupo"] for r in rutas})
        if not grupos:
            db.close()
            return jsonify({"fecha": fecha, "rutas": rutas, "buses": []})
        ph    = ",".join("?" * len(grupos))
        buses = db.execute(
            f"""SELECT b.id, b.numero, b.placa, b.modelo, b.grupo,
                       b.soat_vencimiento, b.tecno_vencimiento, b.tarjeta_op_vencimiento,
                       d.estado, d.conductor_id, d.ruta_id, d.cerrado,
                       CASE WHEN a.bus_id IS NOT NULL THEN 1 ELSE 0 END AS tiene_alistamiento
                FROM buses b
                LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = ?
                LEFT JOIN alistamiento_vehicular a ON a.bus_id = b.id AND a.fecha = ?
                WHERE b.grupo IN ({ph})
                ORDER BY b.numero""",
            [fecha, fecha] + grupos,
        ).fetchall()
    else:
        rutas = db.execute("SELECT id, nombre, grupo, color FROM rutas ORDER BY grupo, nombre").fetchall()
        rutas = [dict(r) for r in rutas]
        buses = db.execute(
            """SELECT b.id, b.numero, b.placa, b.modelo, b.grupo,
                      b.soat_vencimiento, b.tecno_vencimiento, b.tarjeta_op_vencimiento,
                      d.estado, d.conductor_id, d.ruta_id, d.cerrado,
                      CASE WHEN a.bus_id IS NOT NULL THEN 1 ELSE 0 END AS tiene_alistamiento
               FROM buses b
               LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = ?
               LEFT JOIN alistamiento_vehicular a ON a.bus_id = b.id AND a.fecha = ?
               ORDER BY b.numero""",
            (fecha, fecha),
        ).fetchall()

    db.close()
    return jsonify({"fecha": fecha, "rutas": rutas, "buses": [dict(b) for b in buses]})


@app.route("/api/despacho/historial", methods=["GET"])
@require_auth
def get_historial_despacho():
    """Historial de despacho: todos los vehículos por cada fecha con actividad."""
    desde = request.args.get("desde", (date.today() - timedelta(days=30)).isoformat())
    hasta = request.args.get("hasta", date.today().isoformat())
    db    = get_db()
    rol   = getattr(request, "jwt_user_rol", None)
    uid   = getattr(request, "jwt_user_id", None)

    # Para cada fecha que tenga al menos un registro, muestra TODOS los vehículos
    # (LEFT JOIN desde buses hacia despacho_diario para no omitir los no editados)
    base_query = """
        WITH fechas AS (
            SELECT DISTINCT fecha FROM despacho_diario
            WHERE fecha BETWEEN ? AND ?{grupo_filter}
        )
        SELECT f.fecha, b.numero, b.placa, b.modelo, b.grupo,
               c.nombre AS conductor_nombre,
               r.nombre AS ruta_nombre,
               d.estado, d.cerrado
        FROM fechas f
        CROSS JOIN buses b
        LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = f.fecha
        LEFT JOIN conductores c ON c.id = d.conductor_id
        LEFT JOIN rutas r ON r.id = d.ruta_id
        {bus_filter}
        ORDER BY f.fecha DESC, b.numero
    """

    if rol == "Despachador":
        rutas_d = _rutas_de_despachador(db, uid)
        grupos  = list({r["grupo"] for r in rutas_d})
        if not grupos:
            db.close()
            return jsonify([])
        ph = ",".join("?" * len(grupos))
        query = base_query.format(
            grupo_filter=f" AND bus_id IN (SELECT id FROM buses WHERE grupo IN ({ph}))",
            bus_filter=f"WHERE b.grupo IN ({ph})",
        )
        rows = db.execute(query, [desde, hasta] + grupos + grupos).fetchall()
    else:
        query = base_query.format(grupo_filter="", bus_filter="")
        rows  = db.execute(query, (desde, hasta)).fetchall()

    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/despacho/batch", methods=["PUT"])
@require_auth
def batch_upsert_despacho():
    """Guardado instantáneo del despacho del día (upsert por bus/fecha)."""
    if getattr(request, "jwt_user_rol", None) == "Conductor":
        return jsonify({"error": "No autorizado"}), 403

    data       = request.get_json(force=True)
    fecha      = data.get("fecha")
    registros  = data.get("registros", [])
    uid        = getattr(request, "jwt_user_id", None)

    if not fecha:
        return jsonify({"error": "fecha es requerida"}), 400

    estados_validos = ("trabajando", "taller", "descanso")
    db    = get_db()
    saved = 0

    # Validación previa: si algún bus queda en 'trabajando' pero tiene
    # documentos vencidos (SOAT / Tecnomecánica / Tarjeta de Operación), se
    # aborta el lote entero para que el despachador vea el error y no se
    # active parcialmente.
    hoy = date.today()
    docs_bloqueados = []
    for r in registros:
        bus_id = r.get("bus_id")
        estado = r.get("estado") or "trabajando"
        if not bus_id or estado != "trabajando":
            continue
        bus_row = db.execute(
            "SELECT numero, placa, soat_vencimiento, tecno_vencimiento, tarjeta_op_vencimiento "
            "FROM buses WHERE id = ?",
            (bus_id,),
        ).fetchone()
        if not bus_row:
            continue
        bd = dict(bus_row)
        vencidos = _documentos_vencidos_bus(bd, hoy)
        if vencidos:
            etiquetas = [label for campo, _tipo, label in DOC_FIELDS if campo in vencidos]
            docs_bloqueados.append({
                "bus_id":     bus_id,
                "bus_numero": bd.get("numero"),
                "bus_placa":  bd.get("placa"),
                "documentos": etiquetas,
            })
    if docs_bloqueados:
        db.close()
        detalle = "; ".join(
            f"Bus {b['bus_numero']} ({', '.join(b['documentos'])})"
            for b in docs_bloqueados
        )
        return jsonify({
            "error": f"No se puede activar despacho: documentos vencidos — {detalle}. Solicita al Administrador la renovación.",
            "docs_bloqueados": docs_bloqueados,
        }), 409

    for r in registros:
        bus_id = r.get("bus_id")
        if not bus_id:
            continue
        estado = r.get("estado") or "trabajando"
        if estado not in estados_validos:
            estado = "trabajando"
        db.execute(
            """INSERT INTO despacho_diario
                   (bus_id, fecha, estado, conductor_id, ruta_id, despachador_id, updated_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(bus_id, fecha) DO UPDATE SET
                   estado         = excluded.estado,
                   conductor_id   = excluded.conductor_id,
                   ruta_id        = excluded.ruta_id,
                   despachador_id = excluded.despachador_id,
                   updated_at     = CURRENT_TIMESTAMP""",
            (bus_id, fecha, estado, r.get("conductor_id") or None,
             r.get("ruta_id") or None, uid),
        )
        saved += 1

    db.commit()
    db.close()
    return jsonify({"ok": True, "saved": saved})


@app.route("/api/cron/cierre-despacho", methods=["GET", "POST"])
def cron_cierre_despacho():
    """Consolida (cierra) el despacho del día. Invocado por el cron de Vercel a las 23:59.
    El guardado ya es instantáneo; esto solo marca los registros como cerrados."""
    if CRON_SECRET:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {CRON_SECRET}":
            return jsonify({"error": "No autorizado"}), 401

    fecha  = request.args.get("fecha", date.today().isoformat())
    db     = get_db()
    result = db.execute(
        "UPDATE despacho_diario SET cerrado = 1 WHERE fecha = ?", (fecha,)
    )
    cerrados = getattr(result, "rowcount", None)
    db.commit()
    db.close()
    return jsonify({"ok": True, "fecha": fecha, "cerrados": cerrados})


# ──────────────────────────────────────────
#  Alistamiento vehicular
# ──────────────────────────────────────────

# 30 ítems exactos del formulario oficial de alistamiento.
_ALIST_CAMPOS = [
    'retrovisores', 'luz_estacionaria', 'luz_alta_baja', 'luz_reversa', 'logo_empresa',
    'nivel_liquido_freno', 'nivel_deposito_hidraulico', 'nivel_refrigerante',
    'presion_llantas', 'pito', 'stop', 'llantas_general', 'direccionales',
    'frenos_general', 'nivel_liquido_aceite', 'ballestas', 'fugas_aceite',
    'anclaje_bateria', 'dispositivo_luminoso', 'equipo_prevencion', 'cinturon_seguridad',
    'salidas_emergencia', 'aseo_vehiculo', 'fugas_diafragmas', 'asientos_anclados',
    'limpia_brillas', 'condiciones_botiquin', 'observaciones_adicionales',
    'lavada_primeriada', 'primeriada',
]
_VALS_OK = ('buena', 'mala', 'otros')


def hoy_bogota():
    """Fecha actual en Colombia (UTC-5, sin horario de verano) como 'YYYY-MM-DD'.
    El día cambia a la medianoche local: 23:59 es el último momento editable."""
    return (datetime.utcnow() - timedelta(hours=5)).date().isoformat()


def ahora_bogota():
    """Hora actual en Colombia (UTC-5) como 'HH:MM:SS'."""
    return (datetime.utcnow() - timedelta(hours=5)).strftime("%H:%M:%S")


@app.route("/api/alistamiento", methods=["GET"])
@require_auth
def get_alistamiento():
    """Devuelve el alistamiento de un bus para una fecha dada, o null si no existe."""
    fecha  = request.args.get("fecha", date.today().isoformat())
    bus_id = request.args.get("bus_id")
    if not bus_id:
        return jsonify({"error": "bus_id es requerido"}), 400
    db  = get_db()
    row = db.execute(
        "SELECT * FROM alistamiento_vehicular WHERE bus_id = ? AND fecha = ?",
        (bus_id, fecha),
    ).fetchone()
    db.close()
    return jsonify(dict(row) if row else None)


@app.route("/api/alistamiento", methods=["POST"])
@require_auth
def upsert_alistamiento():
    """Crea o actualiza el alistamiento de un bus (UPSERT por bus_id + fecha)."""
    data           = request.get_json(force=True)
    fecha          = data.get("fecha")
    bus_id         = data.get("bus_id")
    conductor_id   = data.get("conductor_id") or None
    despachador_id = getattr(request, "jwt_user_id", None)
    lugar          = data.get("lugar") or None
    nombre_resp    = data.get("nombre_responsable") or None

    # Novedades por ítem (texto libre cuando se marca "Otros"). Se guarda como JSON.
    novedades = data.get("novedades")
    if isinstance(novedades, (dict, list)):
        nov_str = json.dumps(novedades, ensure_ascii=False) if novedades else None
    else:
        nov_str = novedades or None

    if not fecha or not bus_id:
        return jsonify({"error": "fecha y bus_id son requeridos"}), 400

    # Bloqueo por día: solo el Administrador puede modificar alistamientos de días
    # que no sean el de hoy. Despachadores y conductores únicamente registran el día
    # en curso; a la medianoche (Colombia) el día anterior queda congelado.
    rol = getattr(request, "jwt_user_rol", None)
    if rol != "Administrador" and fecha != hoy_bogota():
        return jsonify({
            "error": "Este alistamiento ya está cerrado. Solo el administrador puede modificar días anteriores."
        }), 403

    vals = [data.get(c) if data.get(c) in _VALS_OK else None for c in _ALIST_CAMPOS]
    cols_sql    = ", ".join(_ALIST_CAMPOS)
    placeholders = ", ".join(["?"] * len(_ALIST_CAMPOS))
    update_set  = ", ".join([f"{c} = excluded.{c}" for c in _ALIST_CAMPOS])

    db = get_db()
    db.execute(
        f"""INSERT INTO alistamiento_vehicular
               (fecha, bus_id, conductor_id, despachador_id, lugar, {cols_sql}, nombre_responsable, novedades, updated_at)
           VALUES (?,?,?,?,?,{placeholders},?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(bus_id, fecha) DO UPDATE SET
               conductor_id       = excluded.conductor_id,
               despachador_id     = excluded.despachador_id,
               lugar              = excluded.lugar,
               {update_set},
               nombre_responsable = excluded.nombre_responsable,
               novedades          = excluded.novedades,
               updated_at         = CURRENT_TIMESTAMP""",
        [fecha, bus_id, conductor_id, despachador_id, lugar] + vals + [nombre_resp, nov_str],
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/alistamiento/historial", methods=["GET"])
@require_auth
def historial_alistamiento():
    """Historial de alistamientos de un bus, ordenado del más reciente al más antiguo."""
    bus_id = request.args.get("bus_id")
    limite = request.args.get("limite", "60")
    if not bus_id:
        return jsonify({"error": "bus_id es requerido"}), 400
    try:
        limite = max(1, min(int(limite), 365))
    except (TypeError, ValueError):
        limite = 60
    db = get_db()
    rows = db.execute(
        f"""SELECT a.*, u.nombre AS despachador_nombre
              FROM alistamiento_vehicular a
              LEFT JOIN usuarios u ON u.id = a.despachador_id
             WHERE a.bus_id = ?
             ORDER BY a.fecha DESC
             LIMIT {limite}""",
        (bus_id,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/alistamiento/reporte", methods=["GET"])
@require_auth
def reporte_alistamiento():
    """Reporte consolidado: todos los buses con su alistamiento del día (o sin él).
    Pensado para el administrador; el despachador usa la vista de despacho."""
    rol = getattr(request, "jwt_user_rol", None)
    if rol in ("Despachador", "Conductor"):
        return jsonify({"error": "No autorizado"}), 403

    fecha = request.args.get("fecha", date.today().isoformat())
    cols  = ", ".join(f"a.{c}" for c in _ALIST_CAMPOS)
    db    = get_db()
    rows  = db.execute(
        f"""SELECT b.id AS bus_id, b.numero, b.placa, b.grupo,
                   a.lugar, a.nombre_responsable, a.novedades, a.updated_at,
                   {cols},
                   u.nombre AS despachador_nombre,
                   d.estado AS estado_despacho,
                   CASE WHEN a.bus_id IS NOT NULL THEN 1 ELSE 0 END AS tiene_alistamiento
              FROM buses b
              LEFT JOIN alistamiento_vehicular a ON a.bus_id = b.id AND a.fecha = ?
              LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = ?
              LEFT JOIN usuarios u ON u.id = a.despachador_id
             ORDER BY b.numero""",
        (fecha, fecha),
    ).fetchall()
    db.close()
    return jsonify({"fecha": fecha, "buses": [dict(r) for r in rows]})


# ──────────────────────────────────────────
#  Tipos de novedad
# ──────────────────────────────────────────

@app.route("/api/tipos-novedad", methods=["GET"])
@require_auth
def get_tipos_novedad():
    db = get_db()
    rows = db.execute("SELECT * FROM tipos_novedad ORDER BY orden").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ──────────────────────────────────────────
#  Registros de pasajeros
# ──────────────────────────────────────────

@app.route("/api/pasajeros", methods=["POST"])
@require_auth
def create_pasajeros():
    data = request.get_json(force=True)
    bus_id     = data.get("bus_id")
    ruta_id    = data.get("ruta_id")
    pasajeros  = data.get("pasajeros")
    usuario_id = data.get("usuario_id")

    if not all([bus_id, ruta_id, pasajeros]):
        return jsonify({"error": "Faltan campos requeridos"}), 400

    db = get_db()
    cursor = db.execute(
        "INSERT INTO registros_pasajeros (bus_id, ruta_id, pasajeros, usuario_id) VALUES (?,?,?,?)",
        (bus_id, ruta_id, pasajeros, usuario_id),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/pasajeros", methods=["GET"])
@require_auth
def get_pasajeros():
    fecha = request.args.get("fecha", date.today().isoformat())
    db = get_db()
    rows = db.execute(
        """
        SELECT rp.id, rp.pasajeros, rp.timestamp,
               b.numero AS bus_numero,
               r.nombre AS ruta_nombre, r.color AS ruta_color,
               u.nombre AS usuario_nombre
        FROM   registros_pasajeros rp
        JOIN   buses  b ON b.id = rp.bus_id
        JOIN   rutas  r ON r.id = rp.ruta_id
        LEFT JOIN usuarios u ON u.id = rp.usuario_id
        WHERE  DATE(rp.timestamp) = ?
        ORDER  BY rp.timestamp DESC
        """,
        (fecha,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ──────────────────────────────────────────
#  Mantenimiento
# ──────────────────────────────────────────

@app.route("/api/mantenimiento/estado/<int:bus_id>", methods=["GET"])
@require_auth
def get_maint_estado(bus_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT em.*, tn.clave, tn.label, tn.color
        FROM   estado_mantenimiento em
        JOIN   tipos_novedad tn ON tn.id = em.tipo_novedad_id
        WHERE  em.bus_id = ?
        """,
        (bus_id,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/mantenimiento/estado-flota", methods=["GET"])
@require_auth
def get_maint_estado_flota():
    """Estado de mantenimiento de TODOS los buses en una sola petición
    (evita el N+1 de una llamada por bus desde los dashboards).
    Respuesta: { "<bus_id>": [items...] }. Con user_id de un Propietario,
    solo sus buses."""
    user_id = request.args.get("user_id", type=int)
    db      = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    base = """
        SELECT em.*, tn.clave, tn.label, tn.color
        FROM   estado_mantenimiento em
        JOIN   tipos_novedad tn ON tn.id = em.tipo_novedad_id
    """
    if is_prop:
        if not bus_ids:
            db.close(); return jsonify({})
        ph   = ",".join("?" * len(bus_ids))
        rows = db.execute(base + f" WHERE em.bus_id IN ({ph})", bus_ids).fetchall()
    else:
        rows = db.execute(base).fetchall()
    db.close()

    por_bus = {}
    for r in rows:
        por_bus.setdefault(str(r["bus_id"]), []).append(dict(r))
    return jsonify(por_bus)


@app.route("/api/mantenimiento/estado", methods=["PUT"])
@require_auth
def update_maint_estado():
    data = request.get_json(force=True)
    bus_id          = data.get("bus_id")
    tipo_novedad_id = data.get("tipo_novedad_id")
    estado          = data.get("estado", "ok")
    progreso        = data.get("progreso", 100)
    ultima_fecha    = data.get("ultima_fecha", "")
    ultima_obs      = data.get("ultima_obs", "")

    if not all([bus_id, tipo_novedad_id]):
        return jsonify({"error": "Faltan campos requeridos"}), 400

    db = get_db()
    db.execute(
        """
        INSERT INTO estado_mantenimiento
            (bus_id, tipo_novedad_id, estado, progreso, ultima_fecha, ultima_obs, updated_at)
        VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)
        ON CONFLICT(bus_id, tipo_novedad_id) DO UPDATE SET
            estado       = excluded.estado,
            progreso     = excluded.progreso,
            ultima_fecha = excluded.ultima_fecha,
            ultima_obs   = excluded.ultima_obs,
            updated_at   = CURRENT_TIMESTAMP
        """,
        (bus_id, tipo_novedad_id, estado, progreso, ultima_fecha, ultima_obs),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/mantenimiento/registro", methods=["POST"])
@require_auth
def create_maint_registro():
    data = request.get_json(force=True)
    bus_id          = data.get("bus_id")
    tipo_novedad_id = data.get("tipo_novedad_id")
    observacion     = data.get("observacion", "")
    usuario_id      = data.get("usuario_id")

    if not all([bus_id, tipo_novedad_id]):
        return jsonify({"error": "Faltan campos requeridos"}), 400

    db = get_db()
    cursor = db.execute(
        "INSERT INTO registros_mantenimiento (bus_id, tipo_novedad_id, observacion, usuario_id) VALUES (?,?,?,?)",
        (bus_id, tipo_novedad_id, observacion, usuario_id),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


# ──────────────────────────────────────────
#  Dashboard
# ──────────────────────────────────────────

@app.route("/api/dashboard/propietario", methods=["GET"])
@require_auth
def dashboard_propietario():
    today = date.today().isoformat()
    user_id = request.args.get("user_id", type=int)
    db = get_db()

    bus_ids = []
    if user_id:
        user = db.execute(
            "SELECT rol FROM usuarios WHERE id = ? AND activo = 1", (user_id,)
        ).fetchone()
        if user and user["rol"] == "Propietario":
            rows = db.execute(
                "SELECT bus_id FROM usuario_buses WHERE usuario_id = ?", (user_id,)
            ).fetchall()
            bus_ids = [r["bus_id"] for r in rows]

    if bus_ids:
        ph = ",".join("?" * len(bus_ids))
        status_counts = db.execute(
            f"SELECT estado, COUNT(*) AS count FROM buses WHERE id IN ({ph}) GROUP BY estado",
            bus_ids,
        ).fetchall()
        today_pax = db.execute(
            f"SELECT COALESCE(SUM(pasajeros),0) AS total FROM registros_pasajeros WHERE DATE(timestamp)=? AND bus_id IN ({ph})",
            [today] + bus_ids,
        ).fetchone()
        alerts = db.execute(
            f"""SELECT em.estado, em.ultima_obs, em.updated_at,
                       b.numero AS bus_numero,
                       tn.label AS novedad_label, tn.color
                FROM   estado_mantenimiento em
                JOIN   buses        b  ON b.id  = em.bus_id
                JOIN   tipos_novedad tn ON tn.id = em.tipo_novedad_id
                WHERE  em.estado IN ('warn','alert') AND em.bus_id IN ({ph})
                ORDER  BY em.updated_at DESC
                LIMIT  10""",
            bus_ids,
        ).fetchall()
    else:
        status_counts = db.execute(
            "SELECT estado, COUNT(*) AS count FROM buses GROUP BY estado"
        ).fetchall()
        today_pax = db.execute(
            "SELECT COALESCE(SUM(pasajeros),0) AS total FROM registros_pasajeros WHERE DATE(timestamp)=?",
            (today,),
        ).fetchone()
        alerts = db.execute(
            """SELECT em.estado, em.ultima_obs, em.updated_at,
                      b.numero AS bus_numero,
                      tn.label AS novedad_label, tn.color
               FROM   estado_mantenimiento em
               JOIN   buses        b  ON b.id  = em.bus_id
               JOIN   tipos_novedad tn ON tn.id = em.tipo_novedad_id
               WHERE  em.estado IN ('warn','alert')
               ORDER  BY em.updated_at DESC
               LIMIT  10"""
        ).fetchall()

    db.close()
    return jsonify({
        "status_counts":    [dict(s) for s in status_counts],
        "today_passengers": today_pax["total"],
        "alerts":           [dict(a) for a in alerts],
    })


# ──────────────────────────────────────────
#  Movilidad diaria
# ──────────────────────────────────────────

def _bus_ids_for_user(db, user_id):
    """Retorna (es_propietario, [bus_ids]).
    Si no es Propietario → (False, []) → sin restricción.
    Si es Propietario    → (True,  ids) → filtrar por ids (puede ser lista vacía)."""
    if not user_id:
        return False, []
    u = db.execute("SELECT rol FROM usuarios WHERE id=? AND activo=1", (user_id,)).fetchone()
    if u and u["rol"] == "Propietario":
        rows = db.execute("SELECT bus_id FROM usuario_buses WHERE usuario_id=?", (user_id,)).fetchall()
        return True, [r["bus_id"] for r in rows]
    return False, []


@app.route("/api/movilidad", methods=["GET"])
@require_auth
def get_movilidad():
    fecha            = request.args.get("fecha", date.today().isoformat())
    user_id          = request.args.get("user_id", type=int)
    db               = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        ph   = ",".join("?" * len(bus_ids))
        rows = db.execute(
            f"""SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo,
                       ru.nombre AS ruta_nombre,
                       cm.nombre AS conductor_nombre,
                       CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END AS tiene_despacho,
                       d.estado       AS despacho_estado,
                       d.conductor_id AS despacho_conductor_id,
                       dc.nombre      AS despacho_conductor_nombre,
                       d.ruta_id      AS despacho_ruta_id,
                       dr.nombre      AS despacho_ruta_nombre
                FROM registros_movilidad rm
                JOIN buses b ON b.id = rm.bus_id
                LEFT JOIN rutas ru ON ru.id = rm.ruta_id
                LEFT JOIN conductores cm ON cm.id = rm.conductor_id
                LEFT JOIN despacho_diario d ON d.bus_id = rm.bus_id AND d.fecha = rm.fecha
                LEFT JOIN conductores dc ON dc.id = d.conductor_id
                LEFT JOIN rutas dr ON dr.id = d.ruta_id
                WHERE rm.fecha = ? AND rm.bus_id IN ({ph})
                ORDER BY b.numero""",
            [fecha] + bus_ids,
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo,
                      ru.nombre AS ruta_nombre,
                      cm.nombre AS conductor_nombre,
                      CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END AS tiene_despacho,
                      d.estado       AS despacho_estado,
                      d.conductor_id AS despacho_conductor_id,
                      dc.nombre      AS despacho_conductor_nombre,
                      d.ruta_id      AS despacho_ruta_id,
                      dr.nombre      AS despacho_ruta_nombre
               FROM registros_movilidad rm
               JOIN buses b ON b.id = rm.bus_id
               LEFT JOIN rutas ru ON ru.id = rm.ruta_id
               LEFT JOIN conductores cm ON cm.id = rm.conductor_id
               LEFT JOIN despacho_diario d ON d.bus_id = rm.bus_id AND d.fecha = rm.fecha
               LEFT JOIN conductores dc ON dc.id = d.conductor_id
               LEFT JOIN rutas dr ON dr.id = d.ruta_id
               WHERE rm.fecha = ?
               ORDER BY b.numero""",
            (fecha,),
        ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/movilidad/rango", methods=["GET"])
@require_auth
def get_movilidad_rango():
    desde            = request.args.get("desde", date.today().isoformat())
    hasta            = request.args.get("hasta", date.today().isoformat())
    user_id          = request.args.get("user_id", type=int)
    db               = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        ph   = ",".join("?" * len(bus_ids))
        rows = db.execute(
            f"""SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo,
                       ru.nombre AS ruta_nombre,
                       cm.nombre AS conductor_nombre,
                       CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END AS tiene_despacho,
                       d.estado       AS despacho_estado,
                       d.conductor_id AS despacho_conductor_id,
                       dc.nombre      AS despacho_conductor_nombre,
                       d.ruta_id      AS despacho_ruta_id,
                       dr.nombre      AS despacho_ruta_nombre
                FROM registros_movilidad rm
                JOIN buses b ON b.id = rm.bus_id
                LEFT JOIN rutas ru ON ru.id = rm.ruta_id
                LEFT JOIN conductores cm ON cm.id = rm.conductor_id
                LEFT JOIN despacho_diario d ON d.bus_id = rm.bus_id AND d.fecha = rm.fecha
                LEFT JOIN conductores dc ON dc.id = d.conductor_id
                LEFT JOIN rutas dr ON dr.id = d.ruta_id
                WHERE rm.fecha BETWEEN ? AND ? AND rm.bus_id IN ({ph})
                ORDER BY b.numero, rm.fecha""",
            [desde, hasta] + bus_ids,
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo,
                      ru.nombre AS ruta_nombre,
                      cm.nombre AS conductor_nombre,
                      CASE WHEN d.id IS NOT NULL THEN 1 ELSE 0 END AS tiene_despacho,
                      d.estado       AS despacho_estado,
                      d.conductor_id AS despacho_conductor_id,
                      dc.nombre      AS despacho_conductor_nombre,
                      d.ruta_id      AS despacho_ruta_id,
                      dr.nombre      AS despacho_ruta_nombre
               FROM registros_movilidad rm
               JOIN buses b ON b.id = rm.bus_id
               LEFT JOIN rutas ru ON ru.id = rm.ruta_id
               LEFT JOIN conductores cm ON cm.id = rm.conductor_id
               LEFT JOIN despacho_diario d ON d.bus_id = rm.bus_id AND d.fecha = rm.fecha
               LEFT JOIN conductores dc ON dc.id = d.conductor_id
               LEFT JOIN rutas dr ON dr.id = d.ruta_id
               WHERE rm.fecha BETWEEN ? AND ?
               ORDER BY b.numero, rm.fecha""",
            (desde, hasta),
        ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/movilidad/batch", methods=["PUT"])
@require_auth
def batch_upsert_movilidad():
    data       = request.get_json(force=True)
    fecha      = data.get("fecha")
    registros  = data.get("registros", [])
    usuario_id = data.get("usuario_id")
    # solo_datos=True (importación BEA): solo escribe vueltas/pasajeros/km.
    # Conductor, ruta y novedades existentes no se modifican; en registros
    # nuevos, conductor y ruta salen únicamente del despacho del día.
    solo_datos = bool(data.get("solo_datos"))

    if not fecha:
        return jsonify({"error": "fecha es requerida"}), 400

    db    = get_db()
    saved = 0
    buses_afectados = set()

    # Sincronización despacho → movilidad: para la MISMA fecha del batch
    # (nunca se desplazan días), el conductor y la ruta del despacho mandan.
    # Lo que envíe el cliente solo se usa como respaldo cuando no hay
    # despacho o el despacho tiene ese campo vacío.
    desp_rows = db.execute(
        "SELECT bus_id, conductor_id, ruta_id FROM despacho_diario WHERE fecha = ?",
        (fecha,),
    ).fetchall()
    despacho = {d["bus_id"]: d for d in desp_rows}

    for r in registros:
        bus_id = r.get("bus_id")
        if not bus_id:
            continue
        d = despacho.get(bus_id)
        if solo_datos:
            db.execute(
                """INSERT INTO registros_movilidad
                       (bus_id, fecha, vueltas, pasajeros, km_recorridos, novedades, ruta_id, conductor_id, usuario_id, updated_at)
                   VALUES (?,?,?,?,?,'',?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(bus_id, fecha) DO UPDATE SET
                       vueltas       = excluded.vueltas,
                       pasajeros     = excluded.pasajeros,
                       km_recorridos = excluded.km_recorridos,
                       usuario_id    = excluded.usuario_id,
                       updated_at    = CURRENT_TIMESTAMP""",
                (bus_id, fecha, r.get("vueltas", 0), r.get("pasajeros", 0),
                 r.get("km_recorridos", 0),
                 d["ruta_id"] if d else None,
                 d["conductor_id"] if d else None,
                 usuario_id),
            )
            buses_afectados.add(bus_id)
            saved += 1
            continue
        conductor_id = (d["conductor_id"] if d and d["conductor_id"] else None) or r.get("conductor_id") or None
        ruta_id      = (d["ruta_id"]      if d and d["ruta_id"]      else None) or r.get("ruta_id") or None
        db.execute(
            """INSERT INTO registros_movilidad
                   (bus_id, fecha, vueltas, pasajeros, km_recorridos, novedades, ruta_id, conductor_id, usuario_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(bus_id, fecha) DO UPDATE SET
                   vueltas       = excluded.vueltas,
                   pasajeros     = excluded.pasajeros,
                   km_recorridos = excluded.km_recorridos,
                   novedades     = excluded.novedades,
                   ruta_id       = excluded.ruta_id,
                   conductor_id  = excluded.conductor_id,
                   usuario_id    = excluded.usuario_id,
                   updated_at    = CURRENT_TIMESTAMP""",
            (bus_id, fecha, r.get("vueltas", 0), r.get("pasajeros", 0),
             r.get("km_recorridos", 0), r.get("novedades", ""),
             ruta_id, conductor_id, usuario_id),
        )
        buses_afectados.add(bus_id)
        saved += 1

    # Recalcula km_actuales para cada bus afectado: idempotente.
    # km_actuales = km_inicial + SUM(km_recorridos de registros_movilidad)
    for bid in buses_afectados:
        try:
            db.execute(
                """UPDATE buses
                       SET km_actuales = COALESCE(km_inicial,0) +
                           COALESCE((SELECT SUM(km_recorridos) FROM registros_movilidad WHERE bus_id = ?), 0)
                     WHERE id = ?""",
                (bid, bid),
            )
        except Exception:
            pass

    db.commit()
    db.close()
    return jsonify({"ok": True, "saved": saved})


@app.route("/api/movilidad/fecha/<fecha>", methods=["DELETE"])
@require_auth
def delete_movilidad_fecha(fecha):
    """Elimina todos los registros de movilidad para una fecha dada."""
    db      = get_db()
    result  = db.execute("DELETE FROM registros_movilidad WHERE fecha = ?", (fecha,))
    deleted = result.rowcount
    db.commit()
    db.close()
    return jsonify({"ok": True, "deleted": deleted})


@app.route("/api/movilidad/fechas", methods=["GET"])
@require_auth
def get_movilidad_fechas():
    """Fechas que tienen al menos un registro (para resaltar el calendario)."""
    user_id = request.args.get("user_id", type=int)
    db      = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        ph   = ",".join("?" * len(bus_ids))
        rows = db.execute(
            f"SELECT DISTINCT fecha FROM registros_movilidad WHERE bus_id IN ({ph}) ORDER BY fecha DESC LIMIT 120",
            bus_ids,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT DISTINCT fecha FROM registros_movilidad ORDER BY fecha DESC LIMIT 120"
        ).fetchall()
    db.close()
    return jsonify([r["fecha"] for r in rows])


# ──────────────────────────────────────────
#  Gastos / Facturas de mantenimiento
# ──────────────────────────────────────────

GASTO_CATEGORIAS = [
    "Cambio de aceite", "Frenos", "Llantas", "Motor", "Suspensión",
    "Eléctrico", "Combustible", "Repuestos", "Lavado", "Otro",
]


@app.route("/api/gastos", methods=["POST"])
@require_role("Administrador", "Propietario")
def create_gasto():
    data       = request.get_json(force=True)
    bus_id     = data.get("bus_id")
    fecha      = data.get("fecha")
    categoria  = (data.get("categoria") or "").strip()
    descripcion = (data.get("descripcion") or "").strip()
    taller     = (data.get("taller") or "").strip()
    monto      = data.get("monto")
    usuario_id = request.jwt_user_id
    comp_b64   = data.get("comprobante_base64")
    comp_mime  = data.get("comprobante_mime")
    comp_nombre = data.get("comprobante_nombre")

    if not bus_id or not fecha or not categoria or monto is None:
        return jsonify({"error": "Faltan campos requeridos (vehículo, fecha, categoría, monto)."}), 400

    db = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, usuario_id)
    if is_prop and int(bus_id) not in bus_ids:
        db.close()
        return jsonify({"error": "No autorizado para este vehículo."}), 403

    cursor = db.execute(
        """INSERT INTO gastos_mantenimiento
               (bus_id, fecha, categoria, descripcion, taller, monto,
                comprobante_base64, comprobante_mime, comprobante_nombre, usuario_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (bus_id, fecha, categoria, descripcion or None, taller or None, monto,
         comp_b64 or None, comp_mime or None, comp_nombre or None, usuario_id),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/gastos", methods=["GET"])
@require_auth
def get_gastos():
    """Lista metadata (SIN el base64) filtrada por dueño."""
    user_id   = request.jwt_user_id
    bus_id    = request.args.get("bus_id", type=int)
    categoria = request.args.get("categoria")
    desde     = request.args.get("desde")
    hasta     = request.args.get("hasta")

    db = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    where  = []
    params = []
    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        where.append("g.bus_id IN (%s)" % ",".join("?" * len(bus_ids)))
        params.extend(bus_ids)
    if bus_id:
        where.append("g.bus_id = ?"); params.append(bus_id)
    if categoria:
        where.append("g.categoria = ?"); params.append(categoria)
    if desde:
        where.append("g.fecha >= ?"); params.append(desde)
    if hasta:
        where.append("g.fecha <= ?"); params.append(hasta)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""SELECT g.id, g.bus_id, g.fecha, g.categoria, g.descripcion, g.taller,
                   g.monto, g.comprobante_mime, g.comprobante_nombre, g.created_at,
                   b.numero, b.placa,
                   CASE WHEN g.comprobante_base64 IS NOT NULL THEN 1 ELSE 0 END AS tiene_comprobante
            FROM gastos_mantenimiento g
            JOIN buses b ON b.id = g.bus_id
            {where_sql}
            ORDER BY g.fecha DESC, g.id DESC""",
        params,
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/gastos/<int:gasto_id>/comprobante", methods=["GET"])
@require_auth
def get_gasto_comprobante(gasto_id):
    user_id = request.jwt_user_id
    db = get_db()
    row = db.execute(
        "SELECT bus_id, comprobante_base64, comprobante_mime, comprobante_nombre "
        "FROM gastos_mantenimiento WHERE id = ?",
        (gasto_id,),
    ).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    is_prop, bus_ids = _bus_ids_for_user(db, user_id)
    if is_prop and row["bus_id"] not in bus_ids:
        db.close(); return jsonify({"error": "No autorizado"}), 403

    db.close()
    return jsonify({
        "comprobante_base64": row["comprobante_base64"],
        "comprobante_mime":   row["comprobante_mime"],
        "comprobante_nombre": row["comprobante_nombre"],
    })


@app.route("/api/gastos/<int:gasto_id>", methods=["DELETE"])
@require_role("Administrador", "Propietario")
def delete_gasto(gasto_id):
    user_id = request.jwt_user_id
    db = get_db()
    row = db.execute(
        "SELECT bus_id FROM gastos_mantenimiento WHERE id = ?", (gasto_id,)
    ).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    is_prop, bus_ids = _bus_ids_for_user(db, user_id)
    if is_prop and row["bus_id"] not in bus_ids:
        db.close(); return jsonify({"error": "No autorizado"}), 403

    db.execute("DELETE FROM gastos_mantenimiento WHERE id = ?", (gasto_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Dispositivos Tecnológicos (cámaras / sensores)
# ──────────────────────────────────────────

ROLES_TECNOLOGIA = ("Administrador", "Técnico Cámaras", "Jefe Op. Tecnológicas")
# Roles que ven TODAS las intervenciones (de todos los técnicos). El resto
# (Técnico Cámaras) solo ve/borra las suyas; Propietario se limita a sus buses.
TECNOLOGIA_ROLES_VER_TODO = ("Administrador", "Jefe Op. Tecnológicas")
TECNOLOGIA_AREAS = ("camaras", "sensores")
TECNOLOGIA_MAX_FOTOS = 5


@app.route("/api/tecnologia", methods=["POST"])
@require_role(*ROLES_TECNOLOGIA)
def create_intervencion_tecnologia():
    data        = request.get_json(force=True)
    bus_id      = data.get("bus_id")
    area        = (data.get("area") or "").strip().lower()
    fecha       = data.get("fecha")
    tipo        = (data.get("tipo") or "").strip()
    descripcion = (data.get("descripcion") or "").strip()
    tecnico     = (data.get("tecnico") or "").strip()
    firma_b64   = data.get("firma_base64")
    firma_nom   = (data.get("firma_nombre") or "").strip()
    fotos       = data.get("fotos") or []

    if not bus_id or not fecha or not tipo or not tecnico:
        return jsonify({"error": "Faltan campos requeridos (vehículo, fecha, tipo de intervención, técnico)."}), 400
    if area not in TECNOLOGIA_AREAS:
        return jsonify({"error": "Área inválida (debe ser 'camaras' o 'sensores')."}), 400
    if not isinstance(fotos, list) or len(fotos) > TECNOLOGIA_MAX_FOTOS:
        return jsonify({"error": f"Máximo {TECNOLOGIA_MAX_FOTOS} fotos por intervención."}), 400

    db = get_db()
    bus = db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        db.close()
        return jsonify({"error": "Vehículo no encontrado."}), 404

    cursor = db.execute(
        """INSERT INTO intervenciones_tecnologia
               (bus_id, area, fecha, tipo, descripcion, tecnico,
                firma_base64, firma_nombre, usuario_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (bus_id, area, fecha, tipo, descripcion or None, tecnico,
         firma_b64 or None, firma_nom or None,
         getattr(request, "jwt_user_id", None)),
    )
    new_id = cursor.lastrowid
    for i, foto in enumerate(fotos):
        if not foto:
            continue
        db.execute(
            "INSERT INTO intervencion_tecnologia_fotos (intervencion_id, foto_base64, orden) VALUES (?,?,?)",
            (new_id, foto, i),
        )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/tecnologia", methods=["GET"])
@require_auth
def get_intervenciones_tecnologia():
    """Lista metadata (SIN base64 de fotos) filtrada por dueño si es Propietario."""
    bus_id = request.args.get("bus_id", type=int)
    area   = request.args.get("area")
    desde  = request.args.get("desde")
    hasta  = request.args.get("hasta")

    rol     = getattr(request, "jwt_user_rol", None)
    user_id = getattr(request, "jwt_user_id", None)

    db = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    where  = []
    params = []
    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        where.append("t.bus_id IN (%s)" % ",".join("?" * len(bus_ids)))
        params.extend(bus_ids)
    # Un técnico solo ve sus propias intervenciones; Administrador,
    # Jefe Op. Tecnológicas y Propietario ven todas (según su alcance).
    if not is_prop and rol not in TECNOLOGIA_ROLES_VER_TODO:
        where.append("t.usuario_id = ?"); params.append(user_id)
    if bus_id:
        where.append("t.bus_id = ?"); params.append(bus_id)
    if area in TECNOLOGIA_AREAS:
        where.append("t.area = ?"); params.append(area)
    if desde:
        where.append("t.fecha >= ?"); params.append(desde)
    if hasta:
        where.append("t.fecha <= ?"); params.append(hasta)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""SELECT t.id, t.bus_id, t.area, t.fecha, t.tipo, t.descripcion,
                   t.tecnico, t.firma_nombre, t.created_at, b.numero, b.placa,
                   CASE WHEN t.firma_base64 IS NOT NULL THEN 1 ELSE 0 END AS tiene_firma,
                   (SELECT COUNT(*) FROM intervencion_tecnologia_fotos f
                     WHERE f.intervencion_id = t.id) AS num_fotos
            FROM intervenciones_tecnologia t
            JOIN buses b ON b.id = t.bus_id
            {where_sql}
            ORDER BY t.fecha DESC, t.id DESC""",
        params,
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tecnologia/<int:int_id>/fotos", methods=["GET"])
@require_auth
def get_intervencion_tecnologia_fotos(int_id):
    rol     = getattr(request, "jwt_user_rol", None)
    user_id = getattr(request, "jwt_user_id", None)

    db = get_db()
    row = db.execute(
        "SELECT bus_id, usuario_id, firma_base64, firma_nombre "
        "FROM intervenciones_tecnologia WHERE id = ?", (int_id,)
    ).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    is_prop, bus_ids = _bus_ids_for_user(db, user_id)
    if is_prop and row["bus_id"] not in bus_ids:
        db.close(); return jsonify({"error": "No autorizado"}), 403
    # Un técnico solo puede ver evidencias de sus propias intervenciones.
    if not is_prop and rol not in TECNOLOGIA_ROLES_VER_TODO and row["usuario_id"] != user_id:
        db.close(); return jsonify({"error": "No autorizado"}), 403

    fotos = db.execute(
        "SELECT foto_base64 FROM intervencion_tecnologia_fotos "
        "WHERE intervencion_id = ? ORDER BY orden, id",
        (int_id,),
    ).fetchall()
    db.close()
    return jsonify({
        "fotos": [f["foto_base64"] for f in fotos],
        "firma_base64": row["firma_base64"],
        "firma_nombre": row["firma_nombre"],
    })


@app.route("/api/tecnologia/<int:int_id>", methods=["DELETE"])
@require_role(*ROLES_TECNOLOGIA)
def delete_intervencion_tecnologia(int_id):
    db = get_db()
    row = db.execute(
        "SELECT id, usuario_id FROM intervenciones_tecnologia WHERE id = ?", (int_id,)
    ).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    # Un técnico solo puede borrar sus propias intervenciones;
    # Administrador y Jefe Op. Tecnológicas pueden borrar cualquiera.
    rol     = getattr(request, "jwt_user_rol", None)
    user_id = getattr(request, "jwt_user_id", None)
    if rol not in TECNOLOGIA_ROLES_VER_TODO and row["usuario_id"] != user_id:
        db.close(); return jsonify({"error": "No autorizado"}), 403

    # SQLite con FK ON + Postgres: el CASCADE borra las fotos
    db.execute("DELETE FROM intervenciones_tecnologia WHERE id = ?", (int_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Operador EDS (aseo de estación y novedades)
#  Solo Admin y Operador EDS — no toca buses ni propietarios
# ──────────────────────────────────────────

ROLES_EDS     = ("Administrador", "Operador EDS")
EDS_TIPOS     = ("aseo_patio", "canaletas", "aseo_estacion", "trampa_grasa", "novedad")
EDS_MAX_FOTOS = 5


@app.route("/api/eds", methods=["POST"])
@require_role(*ROLES_EDS)
def create_actividad_eds():
    data          = request.get_json(force=True)
    tipo          = (data.get("tipo") or "").strip().lower()
    fecha         = data.get("fecha")
    descripcion   = (data.get("descripcion") or "").strip()
    realizado_por = (data.get("realizado_por") or "").strip()
    fotos         = data.get("fotos") or []

    if not tipo or not fecha or not realizado_por:
        return jsonify({"error": "Faltan campos requeridos (tipo, fecha, responsable)."}), 400
    if tipo not in EDS_TIPOS:
        return jsonify({"error": "Tipo de actividad inválido."}), 400
    if tipo == "novedad" and not descripcion:
        return jsonify({"error": "Describe la novedad observada."}), 400
    if not isinstance(fotos, list) or len(fotos) > EDS_MAX_FOTOS:
        return jsonify({"error": f"Máximo {EDS_MAX_FOTOS} fotos por registro."}), 400

    db = get_db()
    cursor = db.execute(
        """INSERT INTO actividades_eds (tipo, fecha, descripcion, realizado_por, usuario_id)
           VALUES (?,?,?,?,?)""",
        (tipo, fecha, descripcion or None, realizado_por,
         getattr(request, "jwt_user_id", None)),
    )
    new_id = cursor.lastrowid
    for i, foto in enumerate(fotos):
        if not foto:
            continue
        db.execute(
            "INSERT INTO actividad_eds_fotos (actividad_id, foto_base64, orden) VALUES (?,?,?)",
            (new_id, foto, i),
        )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/eds", methods=["GET"])
@require_role(*ROLES_EDS)
def get_actividades_eds():
    """Lista metadata (SIN base64 de fotos). tipo=aseo agrupa los 3 aseos."""
    tipo  = request.args.get("tipo")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")

    where, params = [], []
    if tipo == "aseo":
        where.append("a.tipo != ?"); params.append("novedad")
    elif tipo in EDS_TIPOS:
        where.append("a.tipo = ?"); params.append(tipo)
    if desde:
        where.append("a.fecha >= ?"); params.append(desde)
    if hasta:
        where.append("a.fecha <= ?"); params.append(hasta)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    db = get_db()
    rows = db.execute(
        f"""SELECT a.id, a.tipo, a.fecha, a.descripcion, a.realizado_por, a.created_at,
                   (SELECT COUNT(*) FROM actividad_eds_fotos f
                     WHERE f.actividad_id = a.id) AS num_fotos
            FROM actividades_eds a
            {where_sql}
            ORDER BY a.fecha DESC, a.id DESC""",
        params,
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/eds/<int:act_id>/fotos", methods=["GET"])
@require_role(*ROLES_EDS)
def get_actividad_eds_fotos(act_id):
    db = get_db()
    row = db.execute("SELECT id FROM actividades_eds WHERE id = ?", (act_id,)).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    fotos = db.execute(
        "SELECT foto_base64 FROM actividad_eds_fotos "
        "WHERE actividad_id = ? ORDER BY orden, id",
        (act_id,),
    ).fetchall()
    db.close()
    return jsonify({"fotos": [f["foto_base64"] for f in fotos]})


@app.route("/api/eds/<int:act_id>", methods=["DELETE"])
@require_role("Administrador")   # solo el admin puede borrar historial; el operador no
def delete_actividad_eds(act_id):
    db = get_db()
    row = db.execute("SELECT id FROM actividades_eds WHERE id = ?", (act_id,)).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    # SQLite con FK ON + Postgres: el CASCADE borra las fotos
    db.execute("DELETE FROM actividades_eds WHERE id = ?", (act_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Lavada Primeriada (área de lavado — solo micros, grupo 'B')
#  Escritura: Admin + Operador Lavada. Lectura: además Propietario
#  (filtrado a sus buses vía _bus_ids_for_user).
# ──────────────────────────────────────────

ROLES_LAVADA_ESCRITURA = ("Administrador", "Operador Lavada")
ROLES_LAVADA_LECTURA   = ("Administrador", "Operador Lavada", "Propietario")
# tipo del registro. 'lavada' es la exterior, 'primeriada' es la interior — algunas
# jornadas se hacen las dos y otras solo una. 'novedad' es un hallazgo sin lavado.
LAVADA_TIPOS           = ("lavada", "primeriada", "ambas", "novedad")
LAVADA_TIPOS_LAVADO    = ("lavada", "primeriada", "ambas")   # todo lo que no es novedad
LAVADA_MAX_FOTOS       = 5


@app.route("/api/lavada", methods=["POST"])
@require_role(*ROLES_LAVADA_ESCRITURA)
def create_actividad_lavada():
    data          = request.get_json(force=True)
    bus_id        = data.get("bus_id")
    tipo          = (data.get("tipo") or "").strip().lower()
    fecha         = data.get("fecha")
    descripcion   = (data.get("descripcion") or "").strip()
    realizado_por = (data.get("realizado_por") or "").strip()
    fotos         = data.get("fotos") or []

    if not bus_id or not tipo or not fecha or not realizado_por:
        return jsonify({"error": "Faltan campos requeridos (bus, tipo, fecha, responsable)."}), 400
    if tipo not in LAVADA_TIPOS:
        return jsonify({"error": "Tipo de actividad inválido."}), 400
    if tipo == "novedad" and not descripcion:
        return jsonify({"error": "Describe la novedad observada."}), 400
    if not isinstance(fotos, list) or len(fotos) > LAVADA_MAX_FOTOS:
        return jsonify({"error": f"Máximo {LAVADA_MAX_FOTOS} fotos por registro."}), 400

    db  = get_db()
    bus = db.execute("SELECT id, grupo FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        db.close(); return jsonify({"error": "Vehículo no encontrado."}), 404
    if bus["grupo"] != "B":
        db.close(); return jsonify({"error": "Solo se permiten micros (grupo B) en Lavada Primeriada."}), 400

    cursor = db.execute(
        """INSERT INTO actividades_lavada
               (bus_id, tipo, fecha, descripcion, realizado_por, usuario_id)
           VALUES (?,?,?,?,?,?)""",
        (bus_id, tipo, fecha, descripcion or None, realizado_por,
         getattr(request, "jwt_user_id", None)),
    )
    new_id = cursor.lastrowid
    for i, foto in enumerate(fotos):
        if not foto:
            continue
        db.execute(
            "INSERT INTO actividad_lavada_fotos (actividad_id, foto_base64, orden) VALUES (?,?,?)",
            (new_id, foto, i),
        )
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/lavada", methods=["GET"])
@require_role(*ROLES_LAVADA_LECTURA)
def get_actividades_lavada():
    """Lista metadata (SIN base64 de fotos). El propietario ve solo sus buses."""
    tipo    = request.args.get("tipo")
    desde   = request.args.get("desde")
    hasta   = request.args.get("hasta")
    bus_arg = request.args.get("bus_id", type=int)

    user_id          = getattr(request, "jwt_user_id", None)
    db               = get_db()
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)

    where, params = [], []
    if is_prop:
        if not bus_ids:
            db.close(); return jsonify([])
        where.append("a.bus_id IN (%s)" % ",".join("?" * len(bus_ids)))
        params.extend(bus_ids)
    if bus_arg:
        where.append("a.bus_id = ?"); params.append(bus_arg)
    # 'lavados' agrupa lavada + primeriada (sin novedades); los tipos concretos
    # filtran por su propio valor. La cadena 'lavada' ya es un tipo real (exterior).
    if tipo == "lavados":
        where.append("a.tipo != ?"); params.append("novedad")
    elif tipo in LAVADA_TIPOS:
        where.append("a.tipo = ?"); params.append(tipo)
    if desde:
        where.append("a.fecha >= ?"); params.append(desde)
    if hasta:
        where.append("a.fecha <= ?"); params.append(hasta)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""SELECT a.id, a.bus_id, a.tipo, a.fecha, a.descripcion, a.realizado_por, a.created_at,
                   b.numero AS bus_numero, b.placa AS bus_placa, b.modelo AS bus_modelo,
                   (SELECT COUNT(*) FROM actividad_lavada_fotos f
                     WHERE f.actividad_id = a.id) AS num_fotos
            FROM actividades_lavada a
            JOIN buses b ON b.id = a.bus_id
            {where_sql}
            ORDER BY a.fecha DESC, a.id DESC""",
        params,
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/lavada/<int:act_id>/fotos", methods=["GET"])
@require_role(*ROLES_LAVADA_LECTURA)
def get_actividad_lavada_fotos(act_id):
    db  = get_db()
    row = db.execute(
        "SELECT id, bus_id FROM actividades_lavada WHERE id = ?", (act_id,)
    ).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    # Propietario solo puede ver fotos de sus propios buses
    user_id          = getattr(request, "jwt_user_id", None)
    is_prop, bus_ids = _bus_ids_for_user(db, user_id)
    if is_prop and row["bus_id"] not in bus_ids:
        db.close(); return jsonify({"error": "No autorizado"}), 403

    fotos = db.execute(
        "SELECT foto_base64 FROM actividad_lavada_fotos "
        "WHERE actividad_id = ? ORDER BY orden, id",
        (act_id,),
    ).fetchall()
    db.close()
    return jsonify({"fotos": [f["foto_base64"] for f in fotos]})


@app.route("/api/lavada/<int:act_id>", methods=["DELETE"])
@require_role("Administrador")   # solo el admin borra historial
def delete_actividad_lavada(act_id):
    db  = get_db()
    row = db.execute("SELECT id FROM actividades_lavada WHERE id = ?", (act_id,)).fetchone()
    if not row:
        db.close(); return jsonify({"error": "No encontrado"}), 404

    db.execute("DELETE FROM actividades_lavada WHERE id = ?", (act_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Admin — Gestión de usuarios
# ──────────────────────────────────────────

@app.route("/api/admin/usuarios", methods=["GET"])
@require_role("Administrador")
def admin_get_usuarios():
    db = get_db()
    rows = db.execute(
        """SELECT u.id, u.username, u.nombre, u.rol, u.iniciales, u.color, u.activo, u.created_at,
                  u.puesto_id, p.nombre AS puesto_nombre,
                  COUNT(ub.bus_id) AS buses_count
           FROM usuarios u
           LEFT JOIN usuario_buses ub ON ub.usuario_id = u.id
           LEFT JOIN puestos_trabajo p ON p.id = u.puesto_id
           GROUP BY u.id, u.puesto_id, p.nombre
           ORDER BY u.nombre"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


def _sync_propietario_from_usuario(db, usuario_id, nombre, rol, activo=1):
    """Mantiene coherencia entre `usuarios` (cuentas) y `propietarios` (catálogo).

    - Si el rol es Propietario y no existe una fila en `propietarios` ligada a
      este usuario, la crea con el mismo nombre.
    - Si ya existe una fila ligada, actualiza nombre y activo (para reflejar
      cambios hechos desde la pantalla de usuarios).
    - Si el rol dejó de ser Propietario, desactiva (no borra) el catálogo
      ligado para preservar las asignaciones históricas del bus.
    """
    try:
        row = db.execute(
            "SELECT id FROM propietarios WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        if rol == "Propietario":
            if row:
                db.execute(
                    "UPDATE propietarios SET nombre = ?, activo = ? WHERE usuario_id = ?",
                    (nombre, 1 if activo else 0, usuario_id),
                )
            else:
                db.execute(
                    "INSERT INTO propietarios (nombre, activo, usuario_id) VALUES (?, ?, ?)",
                    (nombre, 1 if activo else 0, usuario_id),
                )
        elif row:
            db.execute(
                "UPDATE propietarios SET activo = 0 WHERE usuario_id = ?", (usuario_id,)
            )
    except Exception as e:
        print(f"[sync_propietario] {e}")


@app.route("/api/admin/usuarios", methods=["POST"])
@require_role("Administrador")
def admin_create_usuario():
    data     = request.get_json(force=True)
    nombre   = (data.get("nombre") or "").strip()
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    rol      = data.get("rol", "Propietario")
    iniciales = (data.get("iniciales") or (nombre[:2].upper() if nombre else "??")).strip()
    color    = data.get("color", "#f59e0b")

    if not all([nombre, username, password]):
        return jsonify({"error": "Nombre, usuario y contraseña son requeridos"}), 400

    hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO usuarios (username, password, nombre, rol, iniciales, color, puesto_id) VALUES (?,?,?,?,?,?,?)",
            (username, hashed_pw, nombre, rol, iniciales, color, data.get("puesto_id") or None),
        )
        new_id = cursor.lastrowid
        _sync_propietario_from_usuario(db, new_id, nombre, rol, activo=1)
        db.commit()
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/admin/usuarios/<int:uid>", methods=["PUT"])
@require_role("Administrador")
def admin_update_usuario(uid):
    data = request.get_json(force=True)
    db   = get_db()
    if not db.execute("SELECT id FROM usuarios WHERE id = ?", (uid,)).fetchone():
        db.close()
        return jsonify({"error": "Usuario no encontrado"}), 404

    allowed = ["nombre", "username", "iniciales", "color", "activo", "puesto_id", "rol"]
    updates, values = [], []
    for f in allowed:
        if f in data:
            updates.append(f"{f} = ?")
            values.append(data[f])
    if data.get("password"):
        updates.append("password = ?")
        values.append(generate_password_hash(data["password"], method='pbkdf2:sha256'))

    if updates:
        values.append(uid)
        db.execute(f"UPDATE usuarios SET {', '.join(updates)} WHERE id = ?", values)
    # Refleja cambios de nombre/rol/activo en el catálogo `propietarios`
    fresh = db.execute(
        "SELECT nombre, rol, activo FROM usuarios WHERE id = ?", (uid,)
    ).fetchone()
    if fresh:
        f = dict(fresh)
        _sync_propietario_from_usuario(db, uid, f["nombre"], f["rol"], f.get("activo", 1))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/usuarios/<int:uid>", methods=["DELETE"])
@require_role("Administrador")
def admin_delete_usuario(uid):
    """Por defecto desactiva la cuenta (soft delete). Con ?hard=1 la elimina
    definitivamente, liberando el username (cédula) para poder crearla de nuevo
    con otro rol/puesto. El historial se conserva desvinculado (queda sin nombre)."""
    hard = request.args.get("hard") == "1"
    db = get_db()
    if not hard:
        db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (uid,))
        db.commit()
        db.close()
        return jsonify({"ok": True})

    if uid == request.jwt_user_id:
        db.close()
        return jsonify({"error": "No puedes eliminar tu propia cuenta."}), 400

    # Desvincular historial (LEFT JOIN en las consultas → el registro se conserva)
    db.execute("UPDATE registros_mantenimiento SET usuario_id = NULL WHERE usuario_id = ?", (uid,))
    db.execute("UPDATE registros_pasajeros SET usuario_id = NULL WHERE usuario_id = ?", (uid,))
    db.execute("UPDATE registros_movilidad SET usuario_id = NULL WHERE usuario_id = ?", (uid,))
    db.execute("UPDATE gastos_mantenimiento SET usuario_id = NULL WHERE usuario_id = ?", (uid,))
    db.execute("UPDATE intervenciones_tecnologia SET usuario_id = NULL WHERE usuario_id = ?", (uid,))
    db.execute("UPDATE despacho_diario SET despachador_id = NULL WHERE despachador_id = ?", (uid,))
    db.execute("UPDATE alistamiento_vehicular SET despachador_id = NULL WHERE despachador_id = ?", (uid,))
    # Asignaciones y chequeos propios de la cuenta sí se eliminan
    db.execute("DELETE FROM usuario_buses WHERE usuario_id = ?", (uid,))
    db.execute("DELETE FROM despachador_rutas WHERE usuario_id = ?", (uid,))
    db.execute("DELETE FROM chequeos_despachador WHERE usuario_id = ?", (uid,))
    db.execute("DELETE FROM usuarios WHERE id = ?", (uid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/usuarios/<int:uid>/buses", methods=["GET"])
@require_role("Administrador")
def admin_get_usuario_buses(uid):
    db = get_db()
    rows = db.execute(
        """SELECT b.id, b.numero, b.placa, b.modelo, b.grupo, b.estado
           FROM buses b
           JOIN usuario_buses ub ON ub.bus_id = b.id
           WHERE ub.usuario_id = ?
           ORDER BY b.numero""",
        (uid,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/usuarios/<int:uid>/buses", methods=["PUT"])
@require_role("Administrador")
def admin_set_usuario_buses(uid):
    data    = request.get_json(force=True)
    bus_ids = data.get("bus_ids", [])
    db = get_db()
    db.execute("DELETE FROM usuario_buses WHERE usuario_id = ?", (uid,))
    for bid in bus_ids:
        try:
            db.execute("INSERT INTO usuario_buses (usuario_id, bus_id) VALUES (?,?)", (uid, bid))
        except Exception:
            pass
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/usuarios/<int:uid>/rutas", methods=["GET"])
@require_role("Administrador")
def admin_get_usuario_rutas(uid):
    db   = get_db()
    rows = db.execute(
        """SELECT r.id, r.nombre, r.grupo, r.color
           FROM rutas r
           JOIN despachador_rutas dr ON dr.ruta_id = r.id
           WHERE dr.usuario_id = ?
           ORDER BY r.grupo, r.nombre""",
        (uid,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/usuarios/<int:uid>/rutas", methods=["PUT"])
@require_role("Administrador")
def admin_set_usuario_rutas(uid):
    data     = request.get_json(force=True)
    ruta_ids = data.get("ruta_ids", [])
    db = get_db()
    db.execute("DELETE FROM despachador_rutas WHERE usuario_id = ?", (uid,))
    for rid in ruta_ids:
        try:
            db.execute("INSERT INTO despachador_rutas (usuario_id, ruta_id) VALUES (?,?)", (uid, rid))
        except Exception:
            pass
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════
#  Mantenimiento preventivo
# ══════════════════════════════════════════

@app.route("/api/mantenimiento/config/<int:bus_id>", methods=["GET"])
@require_auth
def get_bus_mant_config(bus_id):
    """Devuelve los ítems del catálogo con la config y último historial para un bus."""
    db = get_db()
    bus = db.execute(
        "SELECT id, numero, placa, km_actuales, km_inicial FROM buses WHERE id = ?",
        (bus_id,),
    ).fetchone()
    if not bus:
        db.close()
        return jsonify({"error": "Bus no encontrado"}), 404

    rows = db.execute(
        """SELECT c.id AS item_id, c.sistema, c.nombre, c.tipo_intervalo, c.orden,
                  cfg.intervalo_km, cfg.intervalo_dias,
                  cfg.umbral_amarillo_km, cfg.umbral_rojo_km,
                  cfg.umbral_amarillo_dias, cfg.umbral_rojo_dias,
                  h.fecha_realizado AS ultima_fecha,
                  h.km_realizado    AS ultimo_km
             FROM catalogo_mantenimiento c
             LEFT JOIN bus_mantenimiento_config cfg
                    ON cfg.item_id = c.id AND cfg.bus_id = ? AND cfg.activo = 1
             LEFT JOIN LATERAL (
                  SELECT fecha_realizado, km_realizado
                    FROM bus_mantenimiento_historial
                   WHERE bus_id = ? AND item_id = c.id
                ORDER BY fecha_realizado DESC, id DESC
                   LIMIT 1
             ) h ON TRUE
            WHERE c.activo = 1
         ORDER BY c.sistema, c.orden, c.nombre""",
        (bus_id, bus_id),
    ).fetchall() if DATABASE_URL else None

    if rows is None:
        # SQLite no soporta LATERAL — usar consulta separada
        items = db.execute(
            """SELECT c.id AS item_id, c.sistema, c.nombre, c.tipo_intervalo, c.orden,
                      cfg.intervalo_km, cfg.intervalo_dias,
                      cfg.umbral_amarillo_km, cfg.umbral_rojo_km,
                      cfg.umbral_amarillo_dias, cfg.umbral_rojo_dias
                 FROM catalogo_mantenimiento c
                 LEFT JOIN bus_mantenimiento_config cfg
                        ON cfg.item_id = c.id AND cfg.bus_id = ? AND cfg.activo = 1
                WHERE c.activo = 1
             ORDER BY c.sistema, c.orden, c.nombre""",
            (bus_id,),
        ).fetchall()
        rows = []
        for it in items:
            d = dict(it)
            last = db.execute(
                """SELECT fecha_realizado, km_realizado
                     FROM bus_mantenimiento_historial
                    WHERE bus_id = ? AND item_id = ?
                 ORDER BY fecha_realizado DESC, id DESC LIMIT 1""",
                (bus_id, d["item_id"]),
            ).fetchone()
            d["ultima_fecha"] = last["fecha_realizado"] if last else None
            d["ultimo_km"]    = last["km_realizado"]    if last else None
            rows.append(d)

    db.close()
    return jsonify({"bus": dict(bus), "items": [dict(r) for r in rows]})


@app.route("/api/mantenimiento/config", methods=["POST"])
@require_auth
def upsert_bus_mant_config():
    """Bulk upsert de la config de un bus.
    Body: { bus_id, km_inicial, items: [{ item_id, intervalo_km, intervalo_dias,
            umbral_amarillo_km, umbral_rojo_km, umbral_amarillo_dias, umbral_rojo_dias }] }
    """
    data = request.get_json(force=True)
    bus_id = data.get("bus_id")
    items  = data.get("items", [])
    km_inicial = data.get("km_inicial")
    if not bus_id:
        return jsonify({"error": "bus_id requerido"}), 400

    db = get_db()
    if km_inicial is not None:
        try:
            ki = int(km_inicial)
            db.execute(
                """UPDATE buses
                       SET km_inicial = ?,
                           km_actuales = ? + COALESCE((SELECT SUM(km_recorridos) FROM registros_movilidad WHERE bus_id = ?), 0)
                     WHERE id = ?""",
                (ki, ki, bus_id, bus_id),
            )
        except Exception:
            pass

    saved = 0
    for it in items:
        item_id = it.get("item_id")
        if not item_id:
            continue
        existing = db.execute(
            "SELECT id FROM bus_mantenimiento_config WHERE bus_id = ? AND item_id = ?",
            (bus_id, item_id),
        ).fetchone()
        params = (
            it.get("intervalo_km"), it.get("intervalo_dias"),
            it.get("umbral_amarillo_km"), it.get("umbral_rojo_km"),
            it.get("umbral_amarillo_dias"), it.get("umbral_rojo_dias"),
        )
        if existing:
            db.execute(
                """UPDATE bus_mantenimiento_config
                       SET intervalo_km = ?, intervalo_dias = ?,
                           umbral_amarillo_km = ?, umbral_rojo_km = ?,
                           umbral_amarillo_dias = ?, umbral_rojo_dias = ?,
                           activo = 1, updated_at = CURRENT_TIMESTAMP
                     WHERE bus_id = ? AND item_id = ?""",
                params + (bus_id, item_id),
            )
        else:
            db.execute(
                """INSERT INTO bus_mantenimiento_config
                       (bus_id, item_id, intervalo_km, intervalo_dias,
                        umbral_amarillo_km, umbral_rojo_km,
                        umbral_amarillo_dias, umbral_rojo_dias)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (bus_id, item_id) + params,
            )
        saved += 1
    db.commit()
    db.close()
    return jsonify({"ok": True, "saved": saved})


@app.route("/api/mantenimiento/historial", methods=["POST"])
@require_auth
def add_mant_historial():
    """Registra un mantenimiento realizado (rol mecánico/admin)."""
    data = request.get_json(force=True)
    bus_id  = data.get("bus_id")
    item_id = data.get("item_id")
    fecha   = data.get("fecha_realizado") or date.today().isoformat()
    km      = data.get("km_realizado")
    obs     = data.get("observaciones", "")
    if not bus_id or not item_id:
        return jsonify({"error": "bus_id e item_id requeridos"}), 400

    db = get_db()
    user = db.execute(
        "SELECT nombre FROM usuarios WHERE id = ?", (request.jwt_user_id,)
    ).fetchone()
    realizado_por = (user and user["nombre"]) or "—"

    # Si no se pasa km, usa el actual del bus
    if km is None:
        b = db.execute("SELECT km_actuales FROM buses WHERE id = ?", (bus_id,)).fetchone()
        km = b["km_actuales"] if b else 0

    db.execute(
        """INSERT INTO bus_mantenimiento_historial
               (bus_id, item_id, fecha_realizado, km_realizado, realizado_por, observaciones)
           VALUES (?,?,?,?,?,?)""",
        (bus_id, item_id, fecha, km, realizado_por, obs),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/mantenimiento/historial/<int:bus_id>", methods=["GET"])
@require_auth
def get_mant_historial(bus_id):
    db = get_db()
    rows = db.execute(
        """SELECT h.id, h.item_id, c.sistema, c.nombre, h.fecha_realizado,
                  h.km_realizado, h.realizado_por, h.observaciones, h.created_at
             FROM bus_mantenimiento_historial h
             JOIN catalogo_mantenimiento c ON c.id = h.item_id
            WHERE h.bus_id = ?
         ORDER BY h.fecha_realizado DESC, h.id DESC
            LIMIT 200""",
        (bus_id,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/mantenimiento/alertas", methods=["GET"])
@require_auth
def get_mant_alertas():
    """Calcula on-the-fly las alarmas (amarillas/rojas) de toda la flota."""
    db    = get_db()
    today = date.today()
    rows = db.execute(
        """SELECT cfg.bus_id, b.numero AS bus_numero, b.placa AS bus_placa, b.km_actuales,
                  cfg.item_id, c.sistema, c.nombre, c.tipo_intervalo,
                  cfg.intervalo_km, cfg.intervalo_dias,
                  cfg.umbral_amarillo_km, cfg.umbral_rojo_km,
                  cfg.umbral_amarillo_dias, cfg.umbral_rojo_dias
             FROM bus_mantenimiento_config cfg
             JOIN buses b                ON b.id = cfg.bus_id
             JOIN catalogo_mantenimiento c ON c.id = cfg.item_id
            WHERE cfg.activo = 1 AND c.activo = 1"""
    ).fetchall()

    # Último registro del historial por (bus, ítem) en UNA sola consulta
    # (antes se hacía una consulta por cada fila de config: N+1 sobre Supabase,
    # y este endpoint se refresca cada 60 s desde el dashboard).
    last_rows = db.execute(
        """SELECT bus_id, item_id, fecha_realizado, km_realizado
             FROM (SELECT h.bus_id, h.item_id, h.fecha_realizado, h.km_realizado,
                          ROW_NUMBER() OVER (PARTITION BY h.bus_id, h.item_id
                                             ORDER BY h.fecha_realizado DESC, h.id DESC) AS rn
                     FROM bus_mantenimiento_historial h) ult
            WHERE rn = 1"""
    ).fetchall()
    ultimo_por_item = {(r["bus_id"], r["item_id"]): r for r in last_rows}

    alertas = []
    for r in rows:
        d = dict(r)
        bus_id  = d["bus_id"]
        item_id = d["item_id"]
        tipo    = d["tipo_intervalo"]

        last = ultimo_por_item.get((bus_id, item_id))

        nivel = None
        info  = {}

        if tipo == "KM":
            intervalo = d.get("intervalo_km")
            uy        = d.get("umbral_amarillo_km")
            ur        = d.get("umbral_rojo_km")
            if not intervalo:
                continue
            km_actual = d.get("km_actuales") or 0
            km_base   = (last["km_realizado"] if last else None) or 0
            proximo   = km_base + intervalo
            restante  = proximo - km_actual
            info = {"proximo_km": proximo, "km_restante": restante,
                    "ultimo_km": km_base, "ultima_fecha": (last["fecha_realizado"] if last else None)}
            if ur is not None and restante <= ur:
                nivel = "ROJO"
            elif uy is not None and restante <= uy:
                nivel = "AMARILLO"
        else:  # FECHA
            intervalo = d.get("intervalo_dias")
            uy        = d.get("umbral_amarillo_dias")
            ur        = d.get("umbral_rojo_dias")
            if not intervalo:
                continue
            fecha_base = last["fecha_realizado"] if last else None
            if fecha_base:
                if isinstance(fecha_base, str):
                    try:
                        fecha_base = datetime.strptime(fecha_base[:10], "%Y-%m-%d").date()
                    except Exception:
                        continue
                proxima = fecha_base + timedelta(days=intervalo)
            else:
                proxima = today + timedelta(days=intervalo)
            restante = (proxima - today).days
            info = {"proxima_fecha": proxima.isoformat(), "dias_restantes": restante,
                    "ultima_fecha": fecha_base.isoformat() if fecha_base else None}
            if ur is not None and restante <= ur:
                nivel = "ROJO"
            elif uy is not None and restante <= uy:
                nivel = "AMARILLO"

        if nivel:
            alertas.append({
                "bus_id":     bus_id,
                "bus_numero": d["bus_numero"],
                "bus_placa":  d["bus_placa"],
                "item_id":    item_id,
                "sistema":    d["sistema"],
                "nombre":     d["nombre"],
                "tipo":       tipo,
                "nivel":      nivel,
                **info,
            })

    db.close()
    # Ordena: ROJO primero, luego AMARILLO; dentro de cada uno, más urgente primero
    def sort_key(a):
        rank = 0 if a["nivel"] == "ROJO" else 1
        urg  = a.get("km_restante") if a["tipo"] == "KM" else a.get("dias_restantes")
        return (rank, urg if urg is not None else 999999)
    alertas.sort(key=sort_key)
    return jsonify(alertas)


# ══════════════════════════════════════════
#  Documentos legales del bus (SOAT, Tec.Mec., Tarjeta Op.)
# ══════════════════════════════════════════
#
# Ventana de aviso: se notifica cuando faltan ≤30 días para el vencimiento y
# se recuerda cada día hasta que Administrador renueve (asigna una fecha nueva
# posterior). Un bus con al menos un documento vencido no puede pasar a
# 'trabajando' en el despacho.

DOC_FIELDS = (
    ("soat_vencimiento",        "SOAT",           "SOAT"),
    ("tecno_vencimiento",       "TECNOMECANICA",  "Téc. Mecánica"),
    ("tarjeta_op_vencimiento",  "TARJETA_OP",     "Tarjeta de Operación"),
)

VENTANA_AVISO_DIAS = 30


def _parse_iso_date(v):
    """Devuelve un `date` a partir de una fecha ISO / datetime / date."""
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _documentos_vencidos_bus(row_bus, hoy=None):
    """Devuelve la lista de campos con documento vencido (fecha ≤ hoy)."""
    hoy = hoy or date.today()
    vencidos = []
    for campo, _tipo, _label in DOC_FIELDS:
        fecha = _parse_iso_date(row_bus.get(campo) if isinstance(row_bus, dict) else row_bus[campo])
        if fecha and fecha < hoy:
            vencidos.append(campo)
    return vencidos


@app.route("/api/documentos/alertas", methods=["GET"])
@require_auth
def get_documentos_alertas():
    """Alertas de documentos legales por bus, filtradas por rol.

    Propietario/Técnico Mant. → solo sus buses asignados.
    Cualquier otro rol autenticado → toda la flota.
    Devuelve una fila por (bus × documento) que esté por vencer (≤30 días) o
    ya vencido, incluidas las fechas nulas (sin registrar) como aviso."""
    db  = get_db()
    rol = getattr(request, "jwt_user_rol", None)
    uid = getattr(request, "jwt_user_id", None)

    if rol in ("Propietario", "Técnico Mant.") and uid:
        rows = db.execute(
            """SELECT b.id, b.numero, b.placa,
                      b.soat_vencimiento, b.tecno_vencimiento, b.tarjeta_op_vencimiento
                 FROM buses b
                 JOIN usuario_buses ub ON ub.bus_id = b.id
                WHERE ub.usuario_id = ?
                ORDER BY b.numero""",
            (uid,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT id, numero, placa,
                      soat_vencimiento, tecno_vencimiento, tarjeta_op_vencimiento
                 FROM buses
                ORDER BY numero"""
        ).fetchall()
    db.close()

    hoy = date.today()
    alertas = []
    for r in rows:
        d = dict(r)
        for campo, tipo, label in DOC_FIELDS:
            fecha = _parse_iso_date(d.get(campo))
            if fecha is None:
                # Documento sin fecha registrada: aviso amarillo permanente
                alertas.append({
                    "bus_id":       d["id"],
                    "bus_numero":   d["numero"],
                    "bus_placa":    d["placa"],
                    "tipo":         tipo,
                    "tipo_label":   label,
                    "fecha_vencimiento": None,
                    "dias_restantes":    None,
                    "estado":       "sin_registrar",
                })
                continue
            dias = (fecha - hoy).days
            if dias < 0:
                estado = "vencido"
            elif dias <= VENTANA_AVISO_DIAS:
                estado = "por_vencer"
            else:
                continue
            alertas.append({
                "bus_id":       d["id"],
                "bus_numero":   d["numero"],
                "bus_placa":    d["placa"],
                "tipo":         tipo,
                "tipo_label":   label,
                "fecha_vencimiento": fecha.isoformat(),
                "dias_restantes":    dias,
                "estado":       estado,
            })

    orden_estado = {"vencido": 0, "por_vencer": 1, "sin_registrar": 2}
    alertas.sort(key=lambda a: (
        orden_estado.get(a["estado"], 9),
        a["dias_restantes"] if a["dias_restantes"] is not None else 9999,
        a["bus_numero"] or 0,
    ))
    return jsonify(alertas)


# ──────────────────────────────────────────
#  Rastreo GPS (consulta en vivo al servidor Traccar)
# ──────────────────────────────────────────
#
# Arquitectura: las tablets corren Traccar Client y transmiten a un servidor
# Traccar (demo.traccar.org o propio). BusControl NO guarda coordenadas: solo
# el vínculo bus↔dispositivo (tabla gps_dispositivos). Cuando el usuario pulsa
# "Localizar", el backend consulta el API REST de Traccar en el momento.

TRACCAR_URL   = os.environ.get("TRACCAR_URL", "").rstrip("/")   # ej. https://demo.traccar.org
TRACCAR_TOKEN = os.environ.get("TRACCAR_TOKEN", "")             # token de la cuenta Traccar

# La API de Traccar (versiones recientes) solo acepta el token en /api/session,
# que devuelve una cookie de sesión (JSESSIONID) reutilizable en el resto de
# endpoints. Se cachea aquí para no reautenticar en cada consulta.
_traccar_cookie = {"value": None}


def _traccar_login():
    """Abre sesión con el token y guarda la cookie. Devuelve el header Cookie."""
    url = f"{TRACCAR_URL}/api/session?token={urllib.parse.quote(TRACCAR_TOKEN, safe='')}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            raw = resp.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        detail = "token revocado o inválido" if e.code in (400, 401, 403) else f"error {e.code}"
        raise RuntimeError(f"Traccar rechazó la sesión ({detail}).")
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"No se pudo contactar el servidor Traccar: {e}")
    cookie = "; ".join(c.split(";", 1)[0] for c in raw)
    if not cookie:
        raise RuntimeError("Traccar no devolvió cookie de sesión (revisa el token).")
    _traccar_cookie["value"] = cookie
    return cookie


def _traccar_get(path, params=None):
    """GET autenticado al API REST de Traccar (reusa/renueva la cookie de sesión)."""
    if not TRACCAR_URL or not TRACCAR_TOKEN:
        raise RuntimeError("Traccar no está configurado (faltan TRACCAR_URL o TRACCAR_TOKEN).")
    qs  = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{TRACCAR_URL}/api/{path}{qs}"

    def _do():
        cookie = _traccar_cookie["value"] or _traccar_login()
        req = urllib.request.Request(url, headers={"Accept": "application/json", "Cookie": cookie})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return _do()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):           # cookie expirada → reautenticar una vez
            _traccar_cookie["value"] = None
            try:
                return _do()
            except urllib.error.HTTPError as e2:
                raise RuntimeError(f"Traccar respondió con error {e2.code}.")
            except (urllib.error.URLError, TimeoutError, ValueError) as e2:
                raise RuntimeError(f"No se pudo contactar el servidor Traccar: {e2}")
        raise RuntimeError(f"Traccar respondió con error {e.code}.")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise RuntimeError(f"No se pudo contactar el servidor Traccar: {e}")


def _traccar_devices():
    """Lista normalizada de dispositivos de Traccar."""
    return [
        {"id": d.get("id"), "uniqueId": str(d.get("uniqueId")),
         "name": d.get("name"), "status": d.get("status"),
         "lastUpdate": d.get("lastUpdate")}
        for d in _traccar_get("devices")
    ]


def _traccar_geofences():
    """Mapa {id: nombre} de las geocercas definidas en Traccar (p. ej. 'Reloj 1')."""
    return {g.get("id"): g.get("name") for g in _traccar_get("geofences")}


def _kmh(knots):
    """Velocidad de nudos (formato de Traccar) a km/h."""
    return round(knots * 1.852, 1) if isinstance(knots, (int, float)) else None


def _hora_bogota(iso_utc):
    """deviceTime ISO/UTC de Traccar → ('HH:MM:SS' en Bogotá, antigüedad en segundos)."""
    if not iso_utc:
        return None, None
    try:
        dt = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
        dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        edad = max(0, int((datetime.utcnow() - dt_utc).total_seconds()))
        return (dt_utc - timedelta(hours=5)).strftime("%H:%M:%S"), edad
    except (ValueError, TypeError):
        return None, None


@app.route("/api/gps/traccar/devices", methods=["GET"])
@require_role("Administrador")
def gps_traccar_devices():
    """Dispositivos vistos por el servidor Traccar (para el mapeo device↔bus)."""
    try:
        return jsonify(_traccar_devices())
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/gps/localizables", methods=["GET"])
@require_role("Administrador", "Jefe de Ruta", "Propietario")
def gps_localizables():
    """Buses con dispositivo GPS asignado, para el selector 'Localiza tu bus'.
    El propietario solo ve los suyos (usuario_buses); admin/jefe ven todos."""
    db = get_db()
    if getattr(request, "jwt_user_rol", None) == "Propietario":
        rows = db.execute(
            """SELECT d.device_id, b.id AS bus_id, b.numero, b.placa
               FROM gps_dispositivos d
               JOIN buses b ON b.id = d.bus_id
               JOIN usuario_buses ub ON ub.bus_id = b.id
               WHERE d.activo = 1 AND ub.usuario_id = ?
               ORDER BY b.numero""",
            (request.jwt_user_id,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT d.device_id, b.id AS bus_id, b.numero, b.placa
               FROM gps_dispositivos d JOIN buses b ON b.id = d.bus_id
               WHERE d.activo = 1 ORDER BY b.numero"""
        ).fetchall()
    db.close()
    return jsonify({
        "traccar_configurado": bool(TRACCAR_URL and TRACCAR_TOKEN),
        "buses": [dict(r) for r in rows],
    })


@app.route("/api/gps/localizar", methods=["GET"])
@require_role("Administrador", "Jefe de Ruta", "Propietario")
def gps_localizar():
    """Ubicación en vivo de un bus/dispositivo, consultada al vuelo a Traccar.
    El propietario solo puede localizar buses que le pertenecen."""
    device_id = (request.args.get("device_id") or "").strip()
    bus_id    = request.args.get("bus_id", type=int)
    es_propietario = getattr(request, "jwt_user_rol", None) == "Propietario"

    db = get_db()
    if bus_id and not device_id:
        row = db.execute(
            "SELECT device_id FROM gps_dispositivos WHERE bus_id = ? AND activo = 1",
            (bus_id,),
        ).fetchone()
        if row:
            device_id = row["device_id"]
    bus = None
    if device_id:
        b = db.execute(
            """SELECT b.id, b.numero, b.placa FROM gps_dispositivos d
               JOIN buses b ON b.id = d.bus_id WHERE d.device_id = ?""",
            (device_id,),
        ).fetchone()
        if b:
            bus = dict(b)
        if es_propietario:
            owned = db.execute(
                """SELECT 1 FROM gps_dispositivos d
                   JOIN usuario_buses ub ON ub.bus_id = d.bus_id
                   WHERE d.device_id = ? AND ub.usuario_id = ?""",
                (device_id, request.jwt_user_id),
            ).fetchone()
            if not owned:
                db.close()
                return jsonify({"error": "No autorizado para localizar este bus."}), 403
    db.close()

    if not device_id:
        return jsonify({"error": "Ese bus no tiene un dispositivo GPS asignado."}), 404

    try:
        devices = _traccar_devices()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    dev = next((d for d in devices if d["uniqueId"] == device_id), None)
    if not dev:
        return jsonify({"error": f"El dispositivo '{device_id}' no aparece en Traccar."}), 404

    online = dev.get("status") == "online"
    try:
        posiciones = _traccar_get("positions", {"deviceId": dev["id"]})
        if not posiciones:  # fallback: filtrar del listado completo
            posiciones = [p for p in _traccar_get("positions") if p.get("deviceId") == dev["id"]]
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    if not posiciones:
        return jsonify({"device_id": device_id, "nombre": dev.get("name"), "bus": bus,
                        "online": online, "sin_posicion": True,
                        "error": "El dispositivo todavía no ha reportado ninguna posición."}), 200

    p = posiciones[0]
    attrs = p.get("attributes") or {}
    hora, edad = _hora_bogota(p.get("deviceTime") or p.get("fixTime"))
    return jsonify({
        "device_id":     device_id,
        "nombre":        dev.get("name"),
        "bus":           bus,
        "online":        online,
        "lat":           p.get("latitude"),
        "lng":           p.get("longitude"),
        "velocidad_kmh": _kmh(p.get("speed")),
        "rumbo":         p.get("course"),
        "altitud":       p.get("altitude"),
        "bateria":       attrs.get("batteryLevel", attrs.get("battery")),
        "hora":          hora,
        "edad_segundos": edad,
    })


@app.route("/api/gps/relojes/reporte", methods=["GET"])
@require_role("Administrador", "Jefe de Ruta")
def gps_relojes_reporte():
    """Reporte de pasos por los puntos de control ('Reloj'): a qué hora cruzó cada
    bus cada geocerca de Traccar en un rango de fechas. Consulta en vivo el histórico
    de eventos geofenceEnter de Traccar; no se guarda nada en BusControl."""
    if not (TRACCAR_URL and TRACCAR_TOKEN):
        return jsonify({"traccar_configurado": False, "pasos": []})

    fecha     = (request.args.get("fecha") or hoy_bogota()).strip()
    fecha_fin = (request.args.get("fecha_fin") or fecha).strip()
    bus_id    = request.args.get("bus_id", type=int)

    # Rango [fecha 00:00, fecha_fin 23:59:59] en Bogotá → UTC (Bogotá = UTC-5).
    try:
        desde_utc = (datetime.fromisoformat(f"{fecha}T00:00:00") + timedelta(hours=5))
        hasta_utc = (datetime.fromisoformat(f"{fecha_fin}T23:59:59") + timedelta(hours=5))
    except ValueError:
        return jsonify({"error": "Fecha inválida (usa YYYY-MM-DD)."}), 400
    from_iso = desde_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso   = hasta_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Dispositivos a consultar (los que tienen bus asignado; filtro opcional por bus).
    db = get_db()
    q = """SELECT d.device_id, b.id AS bus_id, b.numero AS bus_numero, b.placa AS bus_placa
           FROM gps_dispositivos d JOIN buses b ON b.id = d.bus_id
           WHERE d.activo = 1"""
    args = []
    if bus_id:
        q += " AND b.id = ?"
        args.append(bus_id)
    rows = db.execute(q, tuple(args)).fetchall()
    # Asignación manual reloj↔bus: {bus_id: {geocerca_id, ...}}. Si un bus tiene
    # relojes asignados, solo esos cuentan para él; si no tiene ninguno, se toman
    # todas las geocercas "Reloj" (comportamiento anterior, retrocompatible).
    relojes_por_bus = {}
    for r in db.execute("SELECT bus_id, geocerca_id FROM gps_bus_relojes").fetchall():
        relojes_por_bus.setdefault(r["bus_id"], set()).add(r["geocerca_id"])
    db.close()
    por_device = {r["device_id"]: dict(r) for r in rows}
    if not por_device:
        return jsonify({"traccar_configurado": True, "pasos": []})

    try:
        devices   = _traccar_devices()
        geocercas = _traccar_geofences()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    # uniqueId (device_id guardado) → id interno de Traccar
    id_traccar = {d["uniqueId"]: d["id"] for d in devices}

    pasos = []
    for device_id, info in por_device.items():
        traccar_id = id_traccar.get(device_id)
        if traccar_id is None:
            continue  # el dispositivo aún no aparece en Traccar
        try:
            eventos = _traccar_get("reports/events", {
                "from": from_iso, "to": to_iso,
                "deviceId": traccar_id, "type": "geofenceEnter",
            })
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 502
        asignadas = relojes_por_bus.get(info["bus_id"])
        for ev in eventos or []:
            geo_id = ev.get("geofenceId")
            if not geo_id:
                continue
            punto = geocercas.get(geo_id)
            # Solo puntos de control "Reloj" (ignora terminal u otras zonas)
            if not punto or "reloj" not in punto.lower():
                continue
            # Si el bus tiene relojes asignados manualmente, respetar esa lista.
            if asignadas and geo_id not in asignadas:
                continue
            hora, _ = _hora_bogota(ev.get("eventTime"))
            fecha_ev = None
            try:
                dt = datetime.fromisoformat(str(ev.get("eventTime")).replace("Z", "+00:00"))
                dt_utc = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
                fecha_ev = (dt_utc - timedelta(hours=5)).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
            pasos.append({
                "bus_numero": info["bus_numero"],
                "bus_placa":  info["bus_placa"],
                "punto":      punto,
                "fecha":      fecha_ev,
                "hora":       hora,
                "eventTime":  ev.get("eventTime"),
            })

    pasos.sort(key=lambda p: p["eventTime"] or "")
    return jsonify({"traccar_configurado": True, "pasos": pasos})


@app.route("/api/gps/dispositivos", methods=["GET"])
@require_role("Administrador")
def gps_dispositivos():
    """Mapeos device↔bus guardados en BusControl."""
    db = get_db()
    rows = db.execute(
        """SELECT d.device_id, d.bus_id, d.activo, b.numero AS bus_numero, b.placa AS bus_placa
           FROM gps_dispositivos d LEFT JOIN buses b ON b.id = d.bus_id
           ORDER BY d.device_id"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/gps/dispositivos/<device_id>", methods=["PUT"])
@require_role("Administrador")
def gps_asignar_dispositivo(device_id):
    """Crea o actualiza el vínculo de un dispositivo Traccar con un bus
    (bus_id null para desasignar)."""
    data = request.get_json(silent=True) or {}
    bus_id = data.get("bus_id")
    if bus_id is not None:
        try:
            bus_id = int(bus_id)
        except (TypeError, ValueError):
            return jsonify({"error": "bus_id inválido"}), 400
    db = get_db()
    if bus_id is not None:
        if not db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone():
            db.close()
            return jsonify({"error": "El bus no existe"}), 404
    db.execute(
        """INSERT INTO gps_dispositivos (device_id, bus_id) VALUES (?, ?)
           ON CONFLICT(device_id) DO UPDATE SET bus_id = excluded.bus_id,
                                                updated_at = CURRENT_TIMESTAMP""",
        (device_id, bus_id),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/gps/geocercas", methods=["GET"])
@require_role("Administrador")
def gps_geocercas():
    """Geocercas 'Reloj' definidas en Traccar (para asignarlas manualmente a buses)."""
    if not (TRACCAR_URL and TRACCAR_TOKEN):
        return jsonify({"traccar_configurado": False, "geocercas": []})
    try:
        geocercas = _traccar_geofences()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502
    relojes = [
        {"id": gid, "nombre": nombre}
        for gid, nombre in geocercas.items()
        if nombre and "reloj" in nombre.lower()
    ]
    relojes.sort(key=lambda g: (g["nombre"] or "").lower())
    return jsonify({"traccar_configurado": True, "geocercas": relojes})


@app.route("/api/gps/bus-relojes", methods=["GET"])
@require_role("Administrador")
def gps_bus_relojes():
    """Asignaciones manuales reloj↔bus. Devuelve un mapa por bus con sus relojes."""
    db = get_db()
    rows = db.execute(
        "SELECT bus_id, geocerca_id, geocerca_nombre FROM gps_bus_relojes"
    ).fetchall()
    db.close()
    por_bus = {}
    for r in rows:
        por_bus.setdefault(str(r["bus_id"]), []).append(
            {"geocerca_id": r["geocerca_id"], "geocerca_nombre": r["geocerca_nombre"]}
        )
    return jsonify(por_bus)


@app.route("/api/gps/bus-relojes/<int:bus_id>", methods=["PUT"])
@require_role("Administrador")
def gps_asignar_relojes(bus_id):
    """Reemplaza la lista de geocercas 'Reloj' asignadas a un bus.
    Body: {"geocercas": [{"id": 12, "nombre": "Reloj Milagrosa"}, ...]}.
    Lista vacía = el bus vuelve a contar todos los relojes (comportamiento por defecto)."""
    data = request.get_json(silent=True) or {}
    geocercas = data.get("geocercas") or []
    db = get_db()
    if not db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone():
        db.close()
        return jsonify({"error": "El bus no existe"}), 404
    db.execute("DELETE FROM gps_bus_relojes WHERE bus_id = ?", (bus_id,))
    for g in geocercas:
        try:
            gid = int(g.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        nombre = (g.get("nombre") or "").strip() or None
        db.execute(
            "INSERT INTO gps_bus_relojes (bus_id, geocerca_id, geocerca_nombre) VALUES (?, ?, ?)",
            (bus_id, gid, nombre),
        )
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("[API] Corriendo en http://localhost:8001")
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=8001)
