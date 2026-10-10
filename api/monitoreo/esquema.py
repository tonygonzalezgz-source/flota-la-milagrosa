"""Tablas del módulo Monitoreo de Bus — SCHEMA_VERSION 12 (ingesta), 13 (rutas geográficas) y 14 (configuración
de ruta, encierros, tramos de velocidad; tipo/alias/tiempo objetivo en puntos).

Postgres (Supabase): `gps_posiciones` se particiona por mes según `recibido_at`
(la hora del servidor, siempre confiable; la del GPS puede venir vacía o
corrida). Así la retención futura es borrar particiones enteras en vez de
DELETE masivos. Una partición DEFAULT recoge cualquier fila si el cron diario
que crea las particiones no alcanzó a correr, para no perder posiciones.

Todas las tablas nuevas quedan con RLS activo y sin privilegios para `anon` /
`authenticated`: el backend entra como `postgres` (no le afecta) y nadie puede
leerlas con la llave pública de Supabase.
"""
from datetime import date

from .comun import EMPRESA_POR_DEFECTO, ahora_utc, es_pg

TABLAS_PROTEGIDAS = ("empresas", "gps_equipos", "gps_pendientes",
                     "gps_posiciones", "gps_posiciones_default", "gps_ultima_posicion",
                     "ruta_trazados", "ruta_puntos_control", "ruta_config",
                     "ruta_tramos_velocidad", "zonas_encierro")

_PG = [
    """CREATE TABLE IF NOT EXISTS empresas (
        id          SERIAL PRIMARY KEY,
        nombre      TEXT NOT NULL UNIQUE,
        activa      INTEGER NOT NULL DEFAULT 1,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    f"INSERT INTO empresas (id, nombre) VALUES ({EMPRESA_POR_DEFECTO}, 'Flota La Milagrosa') ON CONFLICT DO NOTHING",
    "SELECT setval(pg_get_serial_sequence('empresas', 'id'), GREATEST((SELECT MAX(id) FROM empresas), 1))",

    # Equipos GPS instalados en los buses (uno por bus). Tabla aparte de
    # gps_dispositivos (Traccar) para no alterar ese módulo en la transición.
    f"""CREATE TABLE IF NOT EXISTS gps_equipos (
        id                SERIAL PRIMARY KEY,
        empresa_id        INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO} REFERENCES empresas(id),
        imei              TEXT NOT NULL UNIQUE,
        token_hash        TEXT NOT NULL,
        bus_id            INTEGER REFERENCES buses(id) ON DELETE SET NULL,
        activo            INTEGER NOT NULL DEFAULT 1,
        notas             TEXT,
        ultimo_reporte_at TIMESTAMPTZ,
        ultima_hora_gps   TIMESTAMPTZ,
        ultimo_desfase_s  INTEGER,
        ultimo_fix        INTEGER,
        paquetes          BIGINT NOT NULL DEFAULT 0,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # Un bus no puede tener dos equipos activos a la vez.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_gps_equipos_bus_activo ON gps_equipos(bus_id) WHERE bus_id IS NOT NULL AND activo = 1",

    # IMEIs que reportan sin estar registrados: una fila por IMEI (se actualiza, no crece).
    """CREATE TABLE IF NOT EXISTS gps_pendientes (
        imei            TEXT PRIMARY KEY,
        token_hash      TEXT,
        primer_visto_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ultimo_visto_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        paquetes        INTEGER NOT NULL DEFAULT 1,
        ultimo_payload  TEXT,
        ultima_ip       TEXT
    )""",

    f"""CREATE TABLE IF NOT EXISTS gps_posiciones (
        id             BIGSERIAL,
        empresa_id     INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        equipo_id      INTEGER NOT NULL,
        bus_id         INTEGER,
        lat            DOUBLE PRECISION,
        lon            DOUBLE PRECISION,
        velocidad_kmh  REAL,
        rumbo          REAL,
        precision_m    REAL,
        satelites      SMALLINT,
        fix            SMALLINT NOT NULL,
        hora_gps       TIMESTAMPTZ,
        recibido_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (id, recibido_at)
    ) PARTITION BY RANGE (recibido_at)""",
    "CREATE TABLE IF NOT EXISTS gps_posiciones_default PARTITION OF gps_posiciones DEFAULT",
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_bus_hora ON gps_posiciones (bus_id, hora_gps)",
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_equipo_rec ON gps_posiciones (equipo_id, recibido_at)",

    # Una fila por bus: lo que consulta el mapa en vivo (nunca el histórico).
    # lat/lon/hora_gps = último fix VÁLIDO; ultimo_reporte_at/fix_actual = último
    # paquete recibido (con o sin fix). estado_motor lo usará el motor de eventos.
    f"""CREATE TABLE IF NOT EXISTS gps_ultima_posicion (
        bus_id            INTEGER PRIMARY KEY REFERENCES buses(id) ON DELETE CASCADE,
        empresa_id        INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        equipo_id         INTEGER,
        lat               DOUBLE PRECISION,
        lon               DOUBLE PRECISION,
        velocidad_kmh     REAL,
        rumbo             REAL,
        precision_m       REAL,
        satelites         SMALLINT,
        hora_gps          TIMESTAMPTZ,
        ultimo_reporte_at TIMESTAMPTZ,
        fix_actual        SMALLINT,
        estado_motor      TEXT,
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # ── Rutas geográficas (SCHEMA_VERSION 13) ──
    # Un trazado por sentido; puntos = JSON [[lat, lon], …] (sin PostGIS).
    f"""CREATE TABLE IF NOT EXISTS ruta_trazados (
        id            SERIAL PRIMARY KEY,
        empresa_id    INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id       INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        sentido       TEXT NOT NULL CHECK (sentido IN ('ida', 'regreso')),
        puntos        TEXT NOT NULL,
        longitud_m    REAL NOT NULL,
        nombre_origen TEXT,
        updated_by    INTEGER,
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (ruta_id, sentido)
    )""",
    # sentido NULL = quedó lejos de ambos trazados (hay que revisarlo).
    # medida_*_m = metros recorridos desde el inicio de ese trazado hasta el punto.
    # Los puntos no se borran (activo = 0): los pasos históricos los referencian.
    f"""CREATE TABLE IF NOT EXISTS ruta_puntos_control (
        id               SERIAL PRIMARY KEY,
        empresa_id       INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id          INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        nombre           TEXT NOT NULL,
        lat              DOUBLE PRECISION NOT NULL,
        lon              DOUBLE PRECISION NOT NULL,
        radio_m          INTEGER NOT NULL DEFAULT 50,
        sentido          TEXT CHECK (sentido IN ('ida', 'regreso', 'ambos')),
        medida_ida_m     REAL,
        medida_regreso_m REAL,
        orden            INTEGER NOT NULL DEFAULT 0,
        tipo             TEXT NOT NULL DEFAULT 'control' CHECK (tipo IN ('control', 'terminal')),
        alias            TEXT,
        minutos_objetivo INTEGER,
        activo           INTEGER NOT NULL DEFAULT 1,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ruta_puntos_ruta ON ruta_puntos_control (ruta_id, activo, orden)",

    # ── SCHEMA_VERSION 14 ──
    # tipo: 'terminal' marca inicio/fin de vuelta. alias: código corto para tablas
    # (p. ej. WAT). minutos_objetivo: tiempo esperado desde la salida del
    # terminal, para calcular atraso/adelanto.
    "ALTER TABLE ruta_puntos_control ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'control'",
    "ALTER TABLE ruta_puntos_control ADD COLUMN IF NOT EXISTS alias TEXT",
    "ALTER TABLE ruta_puntos_control ADD COLUMN IF NOT EXISTS minutos_objetivo INTEGER",
    # Parámetros del motor de eventos por ruta (sin fila = valores por defecto).
    """CREATE TABLE IF NOT EXISTS ruta_config (
        ruta_id          INTEGER PRIMARY KEY REFERENCES rutas(id) ON DELETE CASCADE,
        vel_aviso_kmh    INTEGER NOT NULL DEFAULT 50,
        vel_critica_kmh  INTEGER NOT NULL DEFAULT 60,
        corredor_m       INTEGER NOT NULL DEFAULT 50,
        posiciones_fuera INTEGER NOT NULL DEFAULT 2,
        precision_max_m  INTEGER NOT NULL DEFAULT 30,
        desconexion_min  INTEGER NOT NULL DEFAULT 3,
        updated_by       INTEGER,
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    # Límite de velocidad propio de un tramo (en metros a lo largo del trazado).
    f"""CREATE TABLE IF NOT EXISTS ruta_tramos_velocidad (
        id               SERIAL PRIMARY KEY,
        empresa_id       INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id          INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        sentido          TEXT NOT NULL CHECK (sentido IN ('ida', 'regreso')),
        desde_m          REAL NOT NULL,
        hasta_m          REAL NOT NULL,
        vel_aviso_kmh    INTEGER NOT NULL,
        vel_critica_kmh  INTEGER NOT NULL,
        nombre           TEXT,
        activo           INTEGER NOT NULL DEFAULT 1
    )""",
    # Patios/parqueaderos: un bus adentro está "en encierro" (no es abandono ni
    # desconexión). ruta_id NULL = aplica a toda la empresa.
    f"""CREATE TABLE IF NOT EXISTS zonas_encierro (
        id          SERIAL PRIMARY KEY,
        empresa_id  INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id     INTEGER REFERENCES rutas(id) ON DELETE CASCADE,
        nombre      TEXT NOT NULL,
        lat         DOUBLE PRECISION NOT NULL,
        lon         DOUBLE PRECISION NOT NULL,
        radio_m     INTEGER NOT NULL DEFAULT 100,
        activo      INTEGER NOT NULL DEFAULT 1,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
]

_SQLITE = [
    """CREATE TABLE IF NOT EXISTS empresas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre      TEXT NOT NULL UNIQUE,
        activa      INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    f"INSERT OR IGNORE INTO empresas (id, nombre) VALUES ({EMPRESA_POR_DEFECTO}, 'Flota La Milagrosa')",
    f"""CREATE TABLE IF NOT EXISTS gps_equipos (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id        INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO} REFERENCES empresas(id),
        imei              TEXT NOT NULL UNIQUE,
        token_hash        TEXT NOT NULL,
        bus_id            INTEGER REFERENCES buses(id) ON DELETE SET NULL,
        activo            INTEGER NOT NULL DEFAULT 1,
        notas             TEXT,
        ultimo_reporte_at TEXT,
        ultima_hora_gps   TEXT,
        ultimo_desfase_s  INTEGER,
        ultimo_fix        INTEGER,
        paquetes          INTEGER NOT NULL DEFAULT 0,
        created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_gps_equipos_bus_activo ON gps_equipos(bus_id) WHERE bus_id IS NOT NULL AND activo = 1",
    """CREATE TABLE IF NOT EXISTS gps_pendientes (
        imei            TEXT PRIMARY KEY,
        token_hash      TEXT,
        primer_visto_at TEXT NOT NULL,
        ultimo_visto_at TEXT NOT NULL,
        paquetes        INTEGER NOT NULL DEFAULT 1,
        ultimo_payload  TEXT,
        ultima_ip       TEXT
    )""",
    f"""CREATE TABLE IF NOT EXISTS gps_posiciones (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id     INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        equipo_id      INTEGER NOT NULL,
        bus_id         INTEGER,
        lat            REAL,
        lon            REAL,
        velocidad_kmh  REAL,
        rumbo          REAL,
        precision_m    REAL,
        satelites      INTEGER,
        fix            INTEGER NOT NULL,
        hora_gps       TEXT,
        recibido_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_bus_hora ON gps_posiciones (bus_id, hora_gps)",
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_equipo_rec ON gps_posiciones (equipo_id, recibido_at)",
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_rec ON gps_posiciones (recibido_at)",
    f"""CREATE TABLE IF NOT EXISTS gps_ultima_posicion (
        bus_id            INTEGER PRIMARY KEY REFERENCES buses(id) ON DELETE CASCADE,
        empresa_id        INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        equipo_id         INTEGER,
        lat               REAL,
        lon               REAL,
        velocidad_kmh     REAL,
        rumbo             REAL,
        precision_m       REAL,
        satelites         INTEGER,
        hora_gps          TEXT,
        ultimo_reporte_at TEXT,
        fix_actual        INTEGER,
        estado_motor      TEXT,
        updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    f"""CREATE TABLE IF NOT EXISTS ruta_trazados (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id    INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id       INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        sentido       TEXT NOT NULL CHECK (sentido IN ('ida', 'regreso')),
        puntos        TEXT NOT NULL,
        longitud_m    REAL NOT NULL,
        nombre_origen TEXT,
        updated_by    INTEGER,
        updated_at    TEXT,
        UNIQUE (ruta_id, sentido)
    )""",
    f"""CREATE TABLE IF NOT EXISTS ruta_puntos_control (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id       INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id          INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        nombre           TEXT NOT NULL,
        lat              REAL NOT NULL,
        lon              REAL NOT NULL,
        radio_m          INTEGER NOT NULL DEFAULT 50,
        sentido          TEXT CHECK (sentido IN ('ida', 'regreso', 'ambos')),
        medida_ida_m     REAL,
        medida_regreso_m REAL,
        orden            INTEGER NOT NULL DEFAULT 0,
        tipo             TEXT NOT NULL DEFAULT 'control' CHECK (tipo IN ('control', 'terminal')),
        alias            TEXT,
        minutos_objetivo INTEGER,
        activo           INTEGER NOT NULL DEFAULT 1,
        created_at       TEXT,
        updated_at       TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ruta_puntos_ruta ON ruta_puntos_control (ruta_id, activo, orden)",
    """CREATE TABLE IF NOT EXISTS ruta_config (
        ruta_id          INTEGER PRIMARY KEY REFERENCES rutas(id) ON DELETE CASCADE,
        vel_aviso_kmh    INTEGER NOT NULL DEFAULT 50,
        vel_critica_kmh  INTEGER NOT NULL DEFAULT 60,
        corredor_m       INTEGER NOT NULL DEFAULT 50,
        posiciones_fuera INTEGER NOT NULL DEFAULT 2,
        precision_max_m  INTEGER NOT NULL DEFAULT 30,
        desconexion_min  INTEGER NOT NULL DEFAULT 3,
        updated_by       INTEGER,
        updated_at       TEXT
    )""",
    f"""CREATE TABLE IF NOT EXISTS ruta_tramos_velocidad (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id       INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id          INTEGER NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
        sentido          TEXT NOT NULL CHECK (sentido IN ('ida', 'regreso')),
        desde_m          REAL NOT NULL,
        hasta_m          REAL NOT NULL,
        vel_aviso_kmh    INTEGER NOT NULL,
        vel_critica_kmh  INTEGER NOT NULL,
        nombre           TEXT,
        activo           INTEGER NOT NULL DEFAULT 1
    )""",
    f"""CREATE TABLE IF NOT EXISTS zonas_encierro (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id  INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        ruta_id     INTEGER REFERENCES rutas(id) ON DELETE CASCADE,
        nombre      TEXT NOT NULL,
        lat         REAL NOT NULL,
        lon         REAL NOT NULL,
        radio_m     INTEGER NOT NULL DEFAULT 100,
        activo      INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT
    )""",
]

# SQLite no tiene ADD COLUMN IF NOT EXISTS: se intenta y se ignora si ya existe.
_SQLITE_COLUMNAS = [
    "ALTER TABLE ruta_puntos_control ADD COLUMN tipo TEXT NOT NULL DEFAULT 'control'",
    "ALTER TABLE ruta_puntos_control ADD COLUMN alias TEXT",
    "ALTER TABLE ruta_puntos_control ADD COLUMN minutos_objetivo INTEGER",
]


def _proteger(db, tabla):
    """RLS sin políticas + sin privilegios para los roles públicos de Supabase."""
    db.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
    db.execute(f"REVOKE ALL ON {tabla} FROM anon, authenticated")


def migrar(db):
    """Idempotente. En Postgres hace commit/rollback por sentencia (un fallo
    aborta la transacción y arrastraría a las siguientes)."""
    if not es_pg():
        for sql in _SQLITE:
            db.execute(sql)
        for sql in _SQLITE_COLUMNAS:
            try:
                db.execute(sql)
            except Exception:
                pass   # la columna ya existe
        return

    for sql in _PG:
        try:
            db.execute(sql)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[monitoreo.migrar] {e}")
    for tabla in TABLAS_PROTEGIDAS:
        try:
            _proteger(db, tabla)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[monitoreo.migrar] RLS {tabla}: {e}")
    asegurar_particiones(db)
    asegurar_indices(db)


# Índices agregados después de crear la tabla. Van aquí (no en _PG) porque esto
# corre también a diario desde el cron: así aparecen sin subir SCHEMA_VERSION.
# En una tabla particionada se crean en todas las particiones, presentes y futuras.
_INDICES_PG = [
    # Reportes de recorrido: posiciones de un día de toda la flota.
    "CREATE INDEX IF NOT EXISTS idx_gps_pos_rec ON gps_posiciones (recibido_at)",
]


def asegurar_indices(db):
    if not es_pg():
        return []
    creados = []
    for sql in _INDICES_PG:
        try:
            db.execute(sql)
            db.commit()
            creados.append(sql.split(" ON ")[0].rsplit(" ", 1)[-1])
        except Exception as e:
            db.rollback()
            print(f"[monitoreo.indices] {e}")
    return creados


def _sumar_meses(d, n):
    total = d.year * 12 + (d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


def asegurar_particiones(db, meses=3):
    """Crea la partición del mes en curso y las de los `meses - 1` siguientes.
    Corre en cada migración y a diario desde /api/cron/monitoreo."""
    if not es_pg():
        return []
    creadas = []
    inicio_mes = ahora_utc().date().replace(day=1)   # recibido_at es UTC
    for i in range(meses):
        desde = _sumar_meses(inicio_mes, i)
        hasta = _sumar_meses(inicio_mes, i + 1)
        nombre = f"gps_posiciones_{desde:%Y_%m}"
        try:
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {nombre} PARTITION OF gps_posiciones "
                f"FOR VALUES FROM ('{desde} 00:00:00+00') TO ('{hasta} 00:00:00+00')"
            )
            _proteger(db, nombre)
            db.commit()
            creadas.append(nombre)
        except Exception as e:
            # Pasa si la partición DEFAULT ya tiene filas de ese mes: hay que
            # moverlas a mano. No bloquea la ingesta (siguen cayendo en DEFAULT).
            db.rollback()
            print(f"[monitoreo.particiones] {nombre}: {e}")
    return creadas
