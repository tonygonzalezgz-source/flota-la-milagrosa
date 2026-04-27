-- ══════════════════════════════════════════════════════
--  LA MILAGROSA — Esquema PostgreSQL (Supabase)
--  Ejecutar en: Supabase → SQL Editor
-- ══════════════════════════════════════════════════════

-- Usuarios del sistema
CREATE TABLE IF NOT EXISTS usuarios (
    id         SERIAL PRIMARY KEY,
    username   TEXT    UNIQUE NOT NULL,
    password   TEXT    NOT NULL,
    nombre     TEXT    NOT NULL,
    rol        TEXT    NOT NULL,
    iniciales  TEXT    NOT NULL,
    color      TEXT    NOT NULL DEFAULT '#6366f1',
    activo     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Flota de buses
CREATE TABLE IF NOT EXISTS buses (
    id          SERIAL PRIMARY KEY,
    numero      INTEGER UNIQUE NOT NULL,
    placa       TEXT,
    modelo      TEXT,
    grupo       TEXT    NOT NULL CHECK(grupo IN ('A','B')),
    estado      TEXT    NOT NULL DEFAULT 'activo'
                        CHECK(estado IN ('activo','alerta','revision','inactivo')),
    km_actuales INTEGER NOT NULL DEFAULT 0,
    propietario_id INTEGER,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Rutas de transporte
CREATE TABLE IF NOT EXISTS rutas (
    id          SERIAL PRIMARY KEY,
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    grupo       TEXT NOT NULL CHECK(grupo IN ('A','B')),
    color       TEXT,
    activa      INTEGER NOT NULL DEFAULT 1
);

-- Propietarios (personas dueñas de buses)
CREATE TABLE IF NOT EXISTS propietarios (
    id         SERIAL PRIMARY KEY,
    nombre     TEXT    NOT NULL,
    cedula     TEXT,
    telefono   TEXT,
    email      TEXT,
    activo     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tarifas de pasajeros
CREATE TABLE IF NOT EXISTS tarifas (
    id     SERIAL PRIMARY KEY,
    tipo   TEXT   UNIQUE NOT NULL,
    label  TEXT   NOT NULL,
    valor  REAL   NOT NULL DEFAULT 0,
    activa INTEGER NOT NULL DEFAULT 1
);

-- Asignación de buses a usuarios propietarios
CREATE TABLE IF NOT EXISTS usuario_buses (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    bus_id     INTEGER NOT NULL REFERENCES buses(id)    ON DELETE CASCADE,
    PRIMARY KEY (usuario_id, bus_id)
);

-- Tipos de novedad de mantenimiento
CREATE TABLE IF NOT EXISTS tipos_novedad (
    id    SERIAL PRIMARY KEY,
    clave TEXT    UNIQUE NOT NULL,
    label TEXT    NOT NULL,
    color TEXT    NOT NULL DEFAULT '#6366f1',
    orden INTEGER NOT NULL DEFAULT 0
);

-- Estado actual de mantenimiento por bus × tipo
CREATE TABLE IF NOT EXISTS estado_mantenimiento (
    id              SERIAL PRIMARY KEY,
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

-- Historial de novedades de mantenimiento
CREATE TABLE IF NOT EXISTS registros_mantenimiento (
    id              SERIAL PRIMARY KEY,
    bus_id          INTEGER NOT NULL REFERENCES buses(id),
    tipo_novedad_id INTEGER NOT NULL REFERENCES tipos_novedad(id),
    observacion     TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id),
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registros de pasajeros por bus y ruta
CREATE TABLE IF NOT EXISTS registros_pasajeros (
    id         SERIAL PRIMARY KEY,
    bus_id     INTEGER NOT NULL REFERENCES buses(id),
    ruta_id    INTEGER NOT NULL REFERENCES rutas(id),
    pasajeros  INTEGER NOT NULL CHECK(pasajeros > 0),
    usuario_id INTEGER REFERENCES usuarios(id),
    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Movilidad diaria por bus (resumen por fecha)
CREATE TABLE IF NOT EXISTS registros_movilidad (
    id            SERIAL PRIMARY KEY,
    bus_id        INTEGER NOT NULL REFERENCES buses(id),
    fecha         DATE    NOT NULL,
    vueltas       INTEGER NOT NULL DEFAULT 0,
    pasajeros     INTEGER NOT NULL DEFAULT 0,
    km_recorridos REAL    NOT NULL DEFAULT 0,
    novedades     TEXT    NOT NULL DEFAULT '',
    ruta_id       INTEGER REFERENCES rutas(id),
    usuario_id    INTEGER REFERENCES usuarios(id),
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bus_id, fecha)
);

-- Foreign key diferida en buses → propietarios
ALTER TABLE buses
    ADD CONSTRAINT fk_buses_propietario
    FOREIGN KEY (propietario_id) REFERENCES propietarios(id)
    ON DELETE SET NULL
    NOT VALID;

-- Índices para rendimiento
CREATE INDEX IF NOT EXISTS idx_reg_pax_timestamp  ON registros_pasajeros(timestamp);
CREATE INDEX IF NOT EXISTS idx_reg_mant_timestamp ON registros_mantenimiento(timestamp);
CREATE INDEX IF NOT EXISTS idx_estado_mant_bus    ON estado_mantenimiento(bus_id);
CREATE INDEX IF NOT EXISTS idx_movilidad_fecha    ON registros_movilidad(fecha);
CREATE INDEX IF NOT EXISTS idx_movilidad_bus      ON registros_movilidad(bus_id);
