"""
La Milagrosa — API Flask
Corre en: http://localhost:8001
Soporta SQLite (local) y PostgreSQL/Supabase (producción).
"""
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import time
from datetime import date, datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

import jwt as _jwt
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()  # carga variables desde .env si existe

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..")

# Genera una clave secreta aleatoria si no está en el entorno (en prod se debe fijar en .env)
SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "12"))

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
DB_PATH      = os.path.join(os.path.dirname(__file__), "flota.db")
SCHEMA_PATH  = os.path.join(os.path.dirname(__file__), "schema.sql")
PG_SCHEMA    = os.path.join(os.path.dirname(__file__), "supabase_schema.sql")

ROLE_VIEWS = {
    "Administrador":  ["dashboard", "historial", "mant", "propietario", "catalogo"],
    "Analista":       ["historial"],
    "Técnico Mant.":  ["mant"],
    "Propietario":    ["propietario"],
    "Operador":       ["operador"],
}


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
                try:
                    aux = self._conn.cursor()
                    aux.execute("SELECT lastval()")
                    row = aux.fetchone()
                    last_id = row[0] if row else None
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

        def close(self):
            self._conn.close()

    def get_db():
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return _PGConn(conn)

else:
    import sqlite3

    def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def init_db():
    """Crea las tablas si no existen y ejecuta migraciones."""
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
    else:
        # ── Modo SQLite local ──
        if not os.path.exists(DB_PATH):
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                sql = f.read()
            import sqlite3 as _sq3
            conn = _sq3.connect(DB_PATH)
            conn.executescript(sql)
            conn.commit()
            conn.close()
            print("[DB] Base de datos SQLite creada:", DB_PATH)
    migrate_db()


def migrate_db():
    """Migraciones idempotentes — funciona en SQLite y PostgreSQL."""
    db = get_db()

    if DATABASE_URL:
        # PostgreSQL soporta ADD COLUMN IF NOT EXISTS
        for col_sql in [
            "ALTER TABLE buses ADD COLUMN IF NOT EXISTS propietario_id INTEGER REFERENCES propietarios(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN IF NOT EXISTS ruta_id INTEGER REFERENCES rutas(id)",
        ]:
            try:
                db.execute(col_sql)
            except Exception:
                pass
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
        for col_sql in [
            "ALTER TABLE buses ADD COLUMN propietario_id INTEGER REFERENCES propietarios(id)",
            "ALTER TABLE registros_movilidad ADD COLUMN ruta_id INTEGER REFERENCES rutas(id)",
        ]:
            try:
                db.execute(col_sql)
            except Exception:
                pass

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
            # Hashear y guardar para la próxima vez
            hashed = generate_password_hash(password, method='pbkdf2:sha256')
            db.execute("UPDATE usuarios SET password = ? WHERE id = ?", (hashed, user["id"]))
            db.commit()

    if not valid:
        db.close()
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401

    rol = user["rol"]
    bus_ids = []
    if rol == "Propietario":
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
        if user and user["rol"] == "Propietario":
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
@require_auth
def create_bus():
    data = request.get_json(force=True)
    numero     = data.get("numero")
    placa      = data.get("placa", "")
    modelo     = data.get("modelo", "")
    grupo      = data.get("grupo", "A")
    estado     = data.get("estado", "activo")
    km         = data.get("km_actuales", 0)
    prop_id    = data.get("propietario_id") or None

    if not numero:
        return jsonify({"error": "El número de bus es requerido"}), 400

    db = get_db()
    try:
        cursor = db.execute(
            "INSERT INTO buses (numero, placa, modelo, grupo, estado, km_actuales, propietario_id) VALUES (?,?,?,?,?,?,?)",
            (numero, placa, modelo, grupo, estado, km, prop_id),
        )
        db.commit()
        new_id = cursor.lastrowid
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/buses/<int:bus_id>", methods=["PUT"])
@require_auth
def update_bus(bus_id):
    data    = request.get_json(force=True)
    db      = get_db()
    bus     = db.execute("SELECT id FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        db.close()
        return jsonify({"error": "Bus no encontrado"}), 404

    fields = ["numero", "placa", "modelo", "grupo", "estado", "km_actuales", "propietario_id"]
    updates, values = [], []
    for f in fields:
        if f in data:
            updates.append(f"{f} = ?")
            values.append(data[f] if data[f] != "" or f not in ("propietario_id",) else None)

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
@require_auth
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


@app.route("/api/propietarios", methods=["POST"])
@require_auth
def create_propietario():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es requerido"}), 400

    db = get_db()
    cursor = db.execute(
        "INSERT INTO propietarios (nombre, cedula, telefono, email) VALUES (?,?,?,?)",
        (nombre, data.get("cedula", ""), data.get("telefono", ""), data.get("email", "")),
    )
    db.commit()
    new_id = cursor.lastrowid
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/propietarios/<int:prop_id>", methods=["PUT"])
@require_auth
def update_propietario(prop_id):
    data = request.get_json(force=True)
    db   = get_db()
    row  = db.execute("SELECT id FROM propietarios WHERE id = ?", (prop_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Propietario no encontrado"}), 404

    db.execute(
        "UPDATE propietarios SET nombre=?, cedula=?, telefono=?, email=? WHERE id=?",
        (data.get("nombre", ""), data.get("cedula", ""), data.get("telefono", ""), data.get("email", ""), prop_id),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/propietarios/<int:prop_id>", methods=["DELETE"])
@require_auth
def delete_propietario(prop_id):
    db  = get_db()
    row = db.execute("SELECT id FROM propietarios WHERE id = ?", (prop_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "Propietario no encontrado"}), 404

    assigned = db.execute(
        "SELECT 1 FROM buses WHERE propietario_id = ? LIMIT 1", (prop_id,)
    ).fetchone()
    if assigned:
        db.close()
        return jsonify({"error": "No se puede eliminar: tiene buses asignados"}), 409

    db.execute("DELETE FROM propietarios WHERE id = ?", (prop_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


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
@require_auth
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
@require_auth
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
@require_auth
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
@require_auth
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


@app.route("/api/pasajeros/stats", methods=["GET"])
@require_auth
def pasajeros_stats():
    """Totales por ruta para la fecha dada (default: hoy)."""
    fecha = request.args.get("fecha", date.today().isoformat())
    db = get_db()
    rows = db.execute(
        """
        SELECT r.nombre AS ruta, r.color, SUM(rp.pasajeros) AS total
        FROM   registros_pasajeros rp
        JOIN   rutas r ON r.id = rp.ruta_id
        WHERE  DATE(rp.timestamp) = ?
        GROUP  BY rp.ruta_id
        ORDER  BY total DESC
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


@app.route("/api/mantenimiento/registros", methods=["GET"])
@require_auth
def get_maint_registros():
    """Últimos N registros de mantenimiento (log histórico)."""
    limite = int(request.args.get("limite", 50))
    db = get_db()
    rows = db.execute(
        """
        SELECT rm.id, rm.observacion, rm.timestamp,
               b.numero AS bus_numero,
               tn.clave, tn.label, tn.color,
               u.nombre AS usuario_nombre
        FROM   registros_mantenimiento rm
        JOIN   buses        b  ON b.id  = rm.bus_id
        JOIN   tipos_novedad tn ON tn.id = rm.tipo_novedad_id
        LEFT JOIN usuarios  u  ON u.id  = rm.usuario_id
        ORDER  BY rm.timestamp DESC
        LIMIT  ?
        """,
        (limite,),
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


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
                       ru.nombre AS ruta_nombre
                FROM registros_movilidad rm
                JOIN buses b ON b.id = rm.bus_id
                LEFT JOIN rutas ru ON ru.id = rm.ruta_id
                WHERE rm.fecha = ? AND rm.bus_id IN ({ph})
                ORDER BY b.numero""",
            [fecha] + bus_ids,
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo,
                      ru.nombre AS ruta_nombre
               FROM registros_movilidad rm
               JOIN buses b ON b.id = rm.bus_id
               LEFT JOIN rutas ru ON ru.id = rm.ruta_id
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
            f"""SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo
                FROM registros_movilidad rm
                JOIN buses b ON b.id = rm.bus_id
                WHERE rm.fecha BETWEEN ? AND ? AND rm.bus_id IN ({ph})
                ORDER BY b.numero, rm.fecha""",
            [desde, hasta] + bus_ids,
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT rm.*, b.numero, b.placa, b.modelo, b.grupo
               FROM registros_movilidad rm
               JOIN buses b ON b.id = rm.bus_id
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

    if not fecha:
        return jsonify({"error": "fecha es requerida"}), 400

    db    = get_db()
    saved = 0
    for r in registros:
        bus_id = r.get("bus_id")
        if not bus_id:
            continue
        db.execute(
            """INSERT INTO registros_movilidad
                   (bus_id, fecha, vueltas, pasajeros, km_recorridos, novedades, ruta_id, usuario_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(bus_id, fecha) DO UPDATE SET
                   vueltas       = excluded.vueltas,
                   pasajeros     = excluded.pasajeros,
                   km_recorridos = excluded.km_recorridos,
                   novedades     = excluded.novedades,
                   ruta_id       = excluded.ruta_id,
                   usuario_id    = excluded.usuario_id,
                   updated_at    = CURRENT_TIMESTAMP""",
            (bus_id, fecha, r.get("vueltas", 0), r.get("pasajeros", 0),
             r.get("km_recorridos", 0), r.get("novedades", ""),
             r.get("ruta_id") or None, usuario_id),
        )
        saved += 1
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
#  Admin — Gestión de usuarios
# ──────────────────────────────────────────

@app.route("/api/admin/usuarios", methods=["GET"])
@require_auth
def admin_get_usuarios():
    db = get_db()
    rows = db.execute(
        """SELECT u.id, u.username, u.nombre, u.rol, u.iniciales, u.color, u.activo, u.created_at,
                  COUNT(ub.bus_id) AS buses_count
           FROM usuarios u
           LEFT JOIN usuario_buses ub ON ub.usuario_id = u.id
           GROUP BY u.id
           ORDER BY u.nombre"""
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/usuarios", methods=["POST"])
@require_auth
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
            "INSERT INTO usuarios (username, password, nombre, rol, iniciales, color) VALUES (?,?,?,?,?,?)",
            (username, hashed_pw, nombre, rol, iniciales, color),
        )
        db.commit()
        new_id = cursor.lastrowid
    except Exception as e:
        db.close()
        return jsonify({"error": str(e)}), 400
    db.close()
    return jsonify({"ok": True, "id": new_id}), 201


@app.route("/api/admin/usuarios/<int:uid>", methods=["PUT"])
@require_auth
def admin_update_usuario(uid):
    data = request.get_json(force=True)
    db   = get_db()
    if not db.execute("SELECT id FROM usuarios WHERE id = ?", (uid,)).fetchone():
        db.close()
        return jsonify({"error": "Usuario no encontrado"}), 404

    allowed = ["nombre", "username", "iniciales", "color", "activo"]
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
        db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/usuarios/<int:uid>", methods=["DELETE"])
@require_auth
def admin_delete_usuario(uid):
    db = get_db()
    db.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (uid,))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/usuarios/<int:uid>/buses", methods=["GET"])
@require_auth
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
@require_auth
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


# ──────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("[API] Corriendo en http://localhost:8001")
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=8001)
