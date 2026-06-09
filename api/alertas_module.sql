-- ══════════════════════════════════════════════════════
--  LA MILAGROSA — Módulo de Alertas Preventivas
--  Ejecutar en: Supabase → SQL Editor
--  Requiere: tabla `buses` ya creada
-- ══════════════════════════════════════════════════════

-- ── 1. Documentos del bus (SOAT, Técnico-Mecánica) ───────
CREATE TABLE IF NOT EXISTS documentos_bus (
    id                 SERIAL PRIMARY KEY,
    bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    tipo               TEXT NOT NULL CHECK (tipo IN ('SOAT','TECNOMECANICA')),
    numero             TEXT,
    fecha_emision      DATE,
    fecha_vencimiento  DATE NOT NULL,
    archivo_url        TEXT,
    activo             INTEGER NOT NULL DEFAULT 1,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_venc
    ON documentos_bus(fecha_vencimiento)
    WHERE activo = 1;

CREATE INDEX IF NOT EXISTS idx_doc_bus_tipo
    ON documentos_bus(bus_id, tipo)
    WHERE activo = 1;


-- ── 2. Mantenimientos preventivos programados ────────────
CREATE TABLE IF NOT EXISTS mantenimientos_preventivos (
    id                 SERIAL PRIMARY KEY,
    bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    tipo               TEXT NOT NULL,            -- "Cambio de aceite", "Sincronización", etc.
    fecha_programada   DATE NOT NULL,
    km_programado      INTEGER,
    notas              TEXT,
    estado             TEXT NOT NULL DEFAULT 'PENDIENTE'
                       CHECK (estado IN ('PENDIENTE','REALIZADO','CANCELADO')),
    realizado_at       TIMESTAMP,
    realizado_por      TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prev_fecha
    ON mantenimientos_preventivos(fecha_programada)
    WHERE estado = 'PENDIENTE';


-- ── 3. Fallas reportadas (persisten en BD, no en memoria) ─
CREATE TABLE IF NOT EXISTS fallas_reportadas (
    id                 SERIAL PRIMARY KEY,
    bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    componente         TEXT NOT NULL,            -- aceite, frenos, motor, llantas, batería, luces
    severidad          TEXT NOT NULL CHECK (severidad IN ('LOW','MID','HIGH')),
    observaciones      TEXT,
    estado             TEXT NOT NULL DEFAULT 'ABIERTA'
                       CHECK (estado IN ('ABIERTA','EN_PROCESO','RESUELTA')),
    reportado_por      TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resuelta_at        TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fallas_abiertas
    ON fallas_reportadas(bus_id, severidad)
    WHERE estado = 'ABIERTA';


-- ── 4. Alertas generadas por el cron ─────────────────────
--      Esta es la tabla central del módulo.
--      Una fila por cada alerta detectada (7 o 2 días).
--      `confirmada` es la bandera que detiene el escalamiento.
CREATE TABLE IF NOT EXISTS alertas (
    id                 SERIAL PRIMARY KEY,
    bus_id             INTEGER NOT NULL REFERENCES buses(id) ON DELETE CASCADE,
    tipo               TEXT NOT NULL CHECK (tipo IN ('SOAT','TECNOMECANICA','PREVENTIVO','FALLA')),
    referencia_id      INTEGER NOT NULL,         -- id del documento/preventivo/falla
    ventana            TEXT NOT NULL CHECK (ventana IN ('7_DIAS','2_DIAS')),
    fecha_objetivo     DATE NOT NULL,            -- fecha de vencimiento/mantenimiento
    mensaje            TEXT,
    generada_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enviada_whatsapp   INTEGER NOT NULL DEFAULT 0,
    whatsapp_at        TIMESTAMP,
    confirmada         INTEGER NOT NULL DEFAULT 0,   -- ⭐ frena el escalamiento de 2 días
    confirmada_at      TIMESTAMP,
    confirmada_por     TEXT,
    -- evita duplicados del mismo cron
    CONSTRAINT uq_alerta UNIQUE (bus_id, tipo, referencia_id, ventana)
);

CREATE INDEX IF NOT EXISTS idx_alertas_pendientes
    ON alertas(confirmada, fecha_objetivo);

CREATE INDEX IF NOT EXISTS idx_alertas_no_enviadas
    ON alertas(enviada_whatsapp, confirmada);


-- ══════════════════════════════════════════════════════
--  Datos demo opcionales (descomenta para probar la UI)
-- ══════════════════════════════════════════════════════
-- INSERT INTO documentos_bus (bus_id, tipo, fecha_vencimiento) VALUES
--   (1, 'SOAT', CURRENT_DATE + INTERVAL '2 days'),
--   (2, 'TECNOMECANICA', CURRENT_DATE + INTERVAL '7 days'),
--   (3, 'SOAT', CURRENT_DATE + INTERVAL '5 days');
--
-- INSERT INTO mantenimientos_preventivos (bus_id, tipo, fecha_programada) VALUES
--   (1, 'Cambio de aceite', CURRENT_DATE + INTERVAL '7 days'),
--   (4, 'Sincronización', CURRENT_DATE + INTERVAL '2 days');
