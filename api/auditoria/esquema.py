"""Tabla `auditoria` — SCHEMA_VERSION 16.

Inmutable a nivel de base de datos: triggers que rechazan UPDATE, DELETE (y en
Postgres también TRUNCATE). Así ni un Administrador desde la app, ni un error de
código, pueden alterar el historial. Sin llave foránea a `usuarios`: se guarda
una copia del nombre/rol para que el rastro sobreviva aunque se borre la cuenta.

Igual que las demás tablas nuevas: RLS activo y sin privilegios para `anon` /
`authenticated` de Supabase.
"""
from .comun import EMPRESA_POR_DEFECTO, es_pg

MENSAJE = "El historial de modificaciones no se puede modificar ni borrar"

_PG = [
    f"""CREATE TABLE IF NOT EXISTS auditoria (
        id              BIGSERIAL PRIMARY KEY,
        empresa_id      INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        creado_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
        usuario_id      INTEGER,
        usuario_nombre  TEXT,
        usuario_login   TEXT,
        usuario_rol     TEXT,
        modulo          TEXT NOT NULL,
        entidad         TEXT NOT NULL,
        entidad_id      TEXT,
        accion          TEXT NOT NULL,
        descripcion     TEXT NOT NULL,
        cambios         TEXT,
        ip              TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_creado ON auditoria(creado_at)",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria(modulo, entidad, entidad_id)",
    f"""CREATE OR REPLACE FUNCTION auditoria_inmutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{MENSAJE}';
        END;
    $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_auditoria_inmutable ON auditoria",
    """CREATE TRIGGER trg_auditoria_inmutable
        BEFORE UPDATE OR DELETE ON auditoria
        FOR EACH ROW EXECUTE FUNCTION auditoria_inmutable()""",
    "DROP TRIGGER IF EXISTS trg_auditoria_sin_truncate ON auditoria",
    """CREATE TRIGGER trg_auditoria_sin_truncate
        BEFORE TRUNCATE ON auditoria
        FOR EACH STATEMENT EXECUTE FUNCTION auditoria_inmutable()""",
    "ALTER TABLE auditoria ENABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON auditoria FROM anon, authenticated",
]

_SQLITE = [
    f"""CREATE TABLE IF NOT EXISTS auditoria (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        empresa_id      INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO},
        creado_at       TEXT NOT NULL,
        usuario_id      INTEGER,
        usuario_nombre  TEXT,
        usuario_login   TEXT,
        usuario_rol     TEXT,
        modulo          TEXT NOT NULL,
        entidad         TEXT NOT NULL,
        entidad_id      TEXT,
        accion          TEXT NOT NULL,
        descripcion     TEXT NOT NULL,
        cambios         TEXT,
        ip              TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_creado ON auditoria(creado_at)",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria(usuario_id)",
    "CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria(modulo, entidad, entidad_id)",
    f"""CREATE TRIGGER IF NOT EXISTS trg_auditoria_sin_update BEFORE UPDATE ON auditoria
        BEGIN SELECT RAISE(ABORT, '{MENSAJE}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS trg_auditoria_sin_delete BEFORE DELETE ON auditoria
        BEGIN SELECT RAISE(ABORT, '{MENSAJE}'); END""",
]


def migrar(db):
    """Idempotente. En Postgres hace commit/rollback por sentencia."""
    if not es_pg():
        for sql in _SQLITE:
            db.execute(sql)
        db.commit()
        return
    for sql in _PG:
        try:
            db.execute(sql)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[auditoria.migrar] {e}")
