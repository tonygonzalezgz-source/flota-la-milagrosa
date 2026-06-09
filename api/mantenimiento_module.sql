-- ══════════════════════════════════════════════════════
--  LA MILAGROSA — Módulo de Mantenimiento Preventivo
--  Ejecutar en: Supabase → SQL Editor
--  Requiere: tabla `buses` ya creada
-- ══════════════════════════════════════════════════════

-- ── 1. Columna km_inicial en buses ──────────────────────
ALTER TABLE buses ADD COLUMN IF NOT EXISTS km_inicial INTEGER NOT NULL DEFAULT 0;


-- ── 2. Catálogo global de ítems de mantenimiento ────────
CREATE TABLE IF NOT EXISTS catalogo_mantenimiento (
    id              SERIAL PRIMARY KEY,
    sistema         TEXT    NOT NULL,
    nombre          TEXT    NOT NULL,
    tipo_intervalo  TEXT    NOT NULL CHECK (tipo_intervalo IN ('KM','FECHA')),
    orden           INTEGER NOT NULL DEFAULT 0,
    activo          INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sistema, nombre)
);

CREATE INDEX IF NOT EXISTS idx_cat_mant_sistema ON catalogo_mantenimiento(sistema) WHERE activo = 1;


-- ── 3. Configuración por bus (intervalos y umbrales) ────
CREATE TABLE IF NOT EXISTS bus_mantenimiento_config (
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
);

CREATE INDEX IF NOT EXISTS idx_bus_mant_cfg_bus ON bus_mantenimiento_config(bus_id) WHERE activo = 1;


-- ── 4. Historial: registros de mantenimientos realizados ─
CREATE TABLE IF NOT EXISTS bus_mantenimiento_historial (
    id              SERIAL PRIMARY KEY,
    bus_id          INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES catalogo_mantenimiento(id),
    fecha_realizado DATE    NOT NULL,
    km_realizado    INTEGER,
    realizado_por   TEXT,
    observaciones   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hist_mant_bus_item
    ON bus_mantenimiento_historial(bus_id, item_id, fecha_realizado DESC);


-- ── 5. Seed: 33 ítems del catálogo (Excel Libro1.xlsx) ──
INSERT INTO catalogo_mantenimiento (sistema, nombre, tipo_intervalo, orden) VALUES
  -- MOTOR
  ('MOTOR', 'Kit Cambio de aceite motor y filtro', 'KM', 10),
  ('MOTOR', 'Correas Alternador',                  'KM', 20),
  ('MOTOR', 'Filtro Aire (motor)',                 'KM', 30),
  ('MOTOR', 'Filtro Combustible',                  'KM', 40),
  ('MOTOR', 'Afinacion motor (Calibrar Valvulas)', 'KM', 50),
  ('MOTOR', 'Casquetes',                           'KM', 60),
  -- CARDAN / EJE CENTRAL
  ('CARDAN/EJE CENTRAL', 'Cardan',              'KM', 10),
  ('CARDAN/EJE CENTRAL', 'Cruceta cardan',      'KM', 20),
  ('CARDAN/EJE CENTRAL', 'Soportes y caucho',   'KM', 30),
  ('CARDAN/EJE CENTRAL', 'Tornilleria',         'KM', 40),
  -- FRENOS
  ('FRENOS', 'Revision de Bandas, rodamientos y retenedores', 'KM',    10),
  ('FRENOS', 'Fugas de Aire',                                 'FECHA', 20),
  ('FRENOS', 'Manguera Freno',                                'KM',    30),
  -- SUSPENSION
  ('SUSPENSION', 'Cambio de bujes de Muelle', 'KM', 10),
  ('SUSPENSION', 'Bujes y Pasadores',         'KM', 20),
  ('SUSPENSION', 'Grapas',                    'KM', 30),
  ('SUSPENSION', 'Amortiguadores',            'KM', 40),
  ('SUSPENSION', 'Barra Estabilizadora',      'KM', 50),
  -- ELECTRICO
  ('ELECTRICO', 'Luces',   'FECHA', 10),
  ('ELECTRICO', 'Bateria', 'FECHA', 20),
  -- REFRIGERACION
  ('REFRIGERACION', 'Mangueras',  'KM', 10),
  ('REFRIGERACION', 'Radiador',   'KM', 20),
  ('REFRIGERACION', 'Intercooler','KM', 30),
  -- LUBRICACION
  ('LUBRICACION', 'Engrase general (niveles aceite, transmision, diferencial y motor; refrigerante y liquidos de freno)', 'KM', 10),
  -- ACEITE
  ('ACEITE', 'Cambio de aceite de motor', 'KM', 10)
ON CONFLICT (sistema, nombre) DO NOTHING;
