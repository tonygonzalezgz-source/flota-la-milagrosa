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

-- Alistamiento vehicular pre-turno (30 ítems checklist)
CREATE TABLE IF NOT EXISTS alistamiento_vehicular (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha             DATE    NOT NULL,
    bus_id            INTEGER NOT NULL REFERENCES buses(id),
    conductor_id      INTEGER REFERENCES conductores(id),
    despachador_id    INTEGER REFERENCES usuarios(id),
    espejo_izq        TEXT CHECK(espejo_izq        IN ('buena','mala','otros')),
    espejo_der        TEXT CHECK(espejo_der        IN ('buena','mala','otros')),
    espejo_retro      TEXT CHECK(espejo_retro      IN ('buena','mala','otros')),
    luces_parqueo     TEXT CHECK(luces_parqueo     IN ('buena','mala','otros')),
    luces_altas       TEXT CHECK(luces_altas       IN ('buena','mala','otros')),
    luces_bajas       TEXT CHECK(luces_bajas       IN ('buena','mala','otros')),
    luces_reversa     TEXT CHECK(luces_reversa     IN ('buena','mala','otros')),
    direccionales     TEXT CHECK(direccionales     IN ('buena','mala','otros')),
    liquido_frenos    TEXT CHECK(liquido_frenos    IN ('buena','mala','otros')),
    liquido_hidra     TEXT CHECK(liquido_hidra     IN ('buena','mala','otros')),
    refrigerante      TEXT CHECK(refrigerante      IN ('buena','mala','otros')),
    aceite_motor      TEXT CHECK(aceite_motor      IN ('buena','mala','otros')),
    pito              TEXT CHECK(pito              IN ('buena','mala','otros')),
    frenos            TEXT CHECK(frenos            IN ('buena','mala','otros')),
    cinturones        TEXT CHECK(cinturones        IN ('buena','mala','otros')),
    salidas_emerg     TEXT CHECK(salidas_emerg     IN ('buena','mala','otros')),
    botiquin          TEXT CHECK(botiquin          IN ('buena','mala','otros')),
    presion_llantas   TEXT CHECK(presion_llantas   IN ('buena','mala','otros')),
    estado_llantas    TEXT CHECK(estado_llantas    IN ('buena','mala','otros')),
    resortes          TEXT CHECK(resortes          IN ('buena','mala','otros')),
    limpieza          TEXT CHECK(limpieza          IN ('buena','mala','otros')),
    logo_empresa      TEXT CHECK(logo_empresa      IN ('buena','mala','otros')),
    limpiaparabrisas  TEXT CHECK(limpiaparabrisas  IN ('buena','mala','otros')),
    bateria           TEXT CHECK(bateria           IN ('buena','mala','otros')),
    sistema_electrico TEXT CHECK(sistema_electrico IN ('buena','mala','otros')),
    fugas_aceite      TEXT CHECK(fugas_aceite      IN ('buena','mala','otros')),
    anclaje_asientos  TEXT CHECK(anclaje_asientos  IN ('buena','mala','otros')),
    fugas_diafragma   TEXT CHECK(fugas_diafragma   IN ('buena','mala','otros')),
    estado_lavado     TEXT CHECK(estado_lavado     IN ('buena','mala','otros')),
    extintor          TEXT CHECK(extintor          IN ('buena','mala','otros')),
    observaciones     TEXT    NOT NULL DEFAULT '',
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bus_id, fecha)
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_reg_pax_timestamp ON registros_pasajeros(timestamp);
CREATE INDEX IF NOT EXISTS idx_reg_mant_timestamp ON registros_mantenimiento(timestamp);
CREATE INDEX IF NOT EXISTS idx_estado_mant_bus ON estado_mantenimiento(bus_id);
CREATE INDEX IF NOT EXISTS idx_despacho_fecha ON despacho_diario(fecha);
CREATE INDEX IF NOT EXISTS idx_despacho_bus ON despacho_diario(bus_id);
CREATE INDEX IF NOT EXISTS idx_alist_fecha ON alistamiento_vehicular(fecha);
CREATE INDEX IF NOT EXISTS idx_alist_bus  ON alistamiento_vehicular(bus_id);
