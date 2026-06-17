-- ══════════════════════════════════════════════════════
--  LA MILAGROSA — Esquema de Base de Datos
--  Motor: SQLite 3
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    UNIQUE NOT NULL,
    password   TEXT    NOT NULL,
    nombre     TEXT    NOT NULL,
    rol        TEXT    NOT NULL,
    iniciales  TEXT    NOT NULL,
    color      TEXT    NOT NULL DEFAULT '#6366f1',
    activo     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS buses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    numero      INTEGER UNIQUE NOT NULL,
    placa       TEXT,
    modelo      TEXT,
    grupo       TEXT    NOT NULL CHECK(grupo IN ('A','B')),
    estado      TEXT    NOT NULL DEFAULT 'activo'
                        CHECK(estado IN ('activo','alerta','revision','inactivo')),
    km_actuales INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rutas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT    NOT NULL,
    descripcion TEXT,
    grupo       TEXT    NOT NULL CHECK(grupo IN ('A','B')),
    color       TEXT,
    activa      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tipos_novedad (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT    UNIQUE NOT NULL,
    label TEXT    NOT NULL,
    color TEXT    NOT NULL DEFAULT '#6366f1',
    orden INTEGER NOT NULL DEFAULT 0
);

-- Estado actual de mantenimiento por bus (una fila por bus × tipo)
CREATE TABLE IF NOT EXISTS estado_mantenimiento (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id          INTEGER NOT NULL REFERENCES buses(id),
    tipo_novedad_id INTEGER NOT NULL REFERENCES tipos_novedad(id),
    estado          TEXT    NOT NULL DEFAULT 'ok'
                            CHECK(estado IN ('ok','warn','alert')),
    progreso        INTEGER NOT NULL DEFAULT 100,
    ultima_fecha    TEXT,
    ultima_obs      TEXT,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bus_id, tipo_novedad_id)
);

-- Historial de novedades registradas por técnicos
CREATE TABLE IF NOT EXISTS registros_mantenimiento (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id          INTEGER NOT NULL REFERENCES buses(id),
    tipo_novedad_id INTEGER NOT NULL REFERENCES tipos_novedad(id),
    observacion     TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id),
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registros de pasajeros por bus y ruta
CREATE TABLE IF NOT EXISTS registros_pasajeros (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id     INTEGER NOT NULL REFERENCES buses(id),
    ruta_id    INTEGER NOT NULL REFERENCES rutas(id),
    pasajeros  INTEGER NOT NULL CHECK(pasajeros > 0),
    usuario_id INTEGER REFERENCES usuarios(id),
    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS propietarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT    NOT NULL,
    cedula     TEXT,
    telefono   TEXT,
    email      TEXT,
    activo     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tarifas (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo   TEXT    UNIQUE NOT NULL,
    label  TEXT    NOT NULL,
    valor  REAL    NOT NULL DEFAULT 0,
    activa INTEGER NOT NULL DEFAULT 1
);

-- Catálogo de conductores
CREATE TABLE IF NOT EXISTS conductores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT    NOT NULL,
    cedula     TEXT,
    telefono   TEXT,
    activo     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Rutas asignadas a cada despachador
CREATE TABLE IF NOT EXISTS despachador_rutas (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    ruta_id    INTEGER NOT NULL REFERENCES rutas(id)    ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, ruta_id)
);

-- Despacho diario: estado operativo de cada bus por día
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
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_reg_pax_timestamp ON registros_pasajeros(timestamp);
CREATE INDEX IF NOT EXISTS idx_reg_mant_timestamp ON registros_mantenimiento(timestamp);
CREATE INDEX IF NOT EXISTS idx_estado_mant_bus ON estado_mantenimiento(bus_id);
CREATE INDEX IF NOT EXISTS idx_despacho_fecha ON despacho_diario(fecha);
CREATE INDEX IF NOT EXISTS idx_despacho_bus ON despacho_diario(bus_id);
