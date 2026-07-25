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

-- Alistamiento vehicular pre-turno (30 ítems exactos del formulario oficial)
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
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_reg_pax_timestamp ON registros_pasajeros(timestamp);
CREATE INDEX IF NOT EXISTS idx_reg_mant_timestamp ON registros_mantenimiento(timestamp);
CREATE INDEX IF NOT EXISTS idx_estado_mant_bus ON estado_mantenimiento(bus_id);
CREATE INDEX IF NOT EXISTS idx_despacho_fecha ON despacho_diario(fecha);
CREATE INDEX IF NOT EXISTS idx_despacho_bus ON despacho_diario(bus_id);
CREATE INDEX IF NOT EXISTS idx_alist_fecha ON alistamiento_vehicular(fecha);
CREATE INDEX IF NOT EXISTS idx_alist_bus  ON alistamiento_vehicular(bus_id);

-- ── Chequeo de despachadores (llegada/salida con GPS) ──
CREATE TABLE IF NOT EXISTS puestos_trabajo (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre      TEXT NOT NULL UNIQUE,
    descripcion TEXT,
    activo      INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chequeos_despachador (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id         INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    puesto_id          INTEGER REFERENCES puestos_trabajo(id),
    fecha              DATE NOT NULL,
    hora_llegada       TEXT NOT NULL,           -- 'HH:MM:SS' hora Bogotá (servidor)
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
);
CREATE INDEX IF NOT EXISTS idx_chequeos_fecha ON chequeos_despachador(fecha);

-- ── Rastreo GPS (vínculo bus↔dispositivo Traccar; la ubicación se consulta en vivo) ──
CREATE TABLE IF NOT EXISTS gps_dispositivos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT NOT NULL UNIQUE,          -- uniqueId del dispositivo en Traccar
    bus_id      INTEGER REFERENCES buses(id) ON DELETE SET NULL,
    activo      INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
