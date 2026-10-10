"""Tablas del módulo Recaudo — SCHEMA_VERSION 16.

- `recaudo_tarifas`: valor del pasaje por grupo de vehículo (A buses, B micros).
- `recaudo_tipos_gasto`: gastos que el conductor puede reportar (ACPM, Taller…).
  No se borran, se desactivan, para no perder el historial.
- `recaudos`: liquidación por bus y día (encabezado con los totales). Una vez
  guardada no se edita ni se borra: el Administrador solo puede ANULARLA (queda
  con `anulado_at`, quién y el motivo) y el bus vuelve a quedar por liquidar.
  Por eso la unicidad (bus, fecha) es solo entre las no anuladas.
    producido  = pasajeros × tarifa
    neto       = producido − total_gastos   (lo que el conductor debe entregar)
    diferencia = recaudado − neto           (negativa = faltante, positiva = sobrante)
- `recaudo_conductores`: de 1 a 3 conductores por liquidación (relevos); cada uno
  con su tramo de registradora y sus propios totales.
- `recaudo_gastos`: los gastos de cada liquidación (por conductor), con copia del
  nombre del tipo para que la tirilla no cambie si después se renombra.
- `recaudo_cierres`: cierre de caja POR RECAUDADOR. Cada recaudador tiene una "caja
  abierta" con sus liquidaciones vigentes sin `cierre_id`; al cerrar, se marcan con el
  cierre y quedan bloqueadas (no se pueden anular). Solo el Administrador reabre un
  cierre: queda como historial (`reabierto_at`) y las liquidaciones vuelven a la caja
  abierta. `liquidacion_ids` guarda qué liquidaciones entraron, para el reporte.
- `recaudo_conceptos`: conceptos contables de la caja (cuenta, tercero, signo débito/
  crédito, centro de costo…) para el archivo plano que importa el programa contable.
  `uso` marca los que usa el sistema: CIERRE_CAJA (débito del total) y
  RECAUDO_VEHICULO (crédito por cada liquidación); esos no se pueden desactivar.
- `recaudo_config`: datos contables fijos (NIT de la compañía, tipo de comprobante, moneda).
- En `buses`: propietario según la tarjeta de propiedad (nombre y documento), que es
  el tercero (NIT) de las líneas de recaudo del archivo plano.

El dinero se guarda en pesos enteros (INTEGER): en Postgres un NUMERIC llega
como Decimal y Flask lo serializa como texto. La tarifa se copia en cada
liquidación para que un cambio de tarifa no altere las ya hechas.

Igual que Monitoreo: RLS activo y sin privilegios para `anon` / `authenticated`.
"""
from .comun import (CONCEPTOS_INICIALES, CONFIG_CONTABLE_INICIAL, EMPRESA_POR_DEFECTO,
                    TARIFAS_INICIALES, TIPOS_GASTO_INICIALES, es_pg)

TABLAS_PROTEGIDAS = ("recaudo_tarifas", "recaudo_tipos_gasto", "recaudo_cierres", "recaudos",
                     "recaudo_conductores", "recaudo_gastos", "recaudo_conceptos", "recaudo_config")


def _sql_txt(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


_SEMILLA_CONCEPTOS = (
    "INSERT INTO recaudo_conceptos (empresa_id, nombre, cuenta, tercero, nit_fijo, signo, centro_costo, "
    "descripcion, referencia, uso, orden) VALUES "
    + ", ".join(
        f"({EMPRESA_POR_DEFECTO}, {_sql_txt(c['nombre'])}, {_sql_txt(c['cuenta'])}, {_sql_txt(c['tercero'])}, "
        f"{_sql_txt(c.get('nit_fijo'))}, {c['signo']}, {_sql_txt(c.get('centro_costo'))}, "
        f"{_sql_txt(c.get('descripcion'))}, {_sql_txt(c.get('referencia', ''))}, {_sql_txt(c.get('uso'))}, {i})"
        for i, c in enumerate(CONCEPTOS_INICIALES, 1))
    + " ON CONFLICT DO NOTHING"
)

_SEMILLA_CONFIG = (
    "INSERT INTO recaudo_config (empresa_id, clave, valor) VALUES "
    + ", ".join(f"({EMPRESA_POR_DEFECTO}, {_sql_txt(k)}, {_sql_txt(v)})" for k, v in CONFIG_CONTABLE_INICIAL.items())
    + " ON CONFLICT DO NOTHING"
)

_SEMILLA_TARIFAS = (
    "INSERT INTO recaudo_tarifas (empresa_id, grupo, valor) VALUES "
    + ", ".join(f"({EMPRESA_POR_DEFECTO}, '{g}', {v})" for g, v in TARIFAS_INICIALES.items())
    + " ON CONFLICT DO NOTHING"
)

_SEMILLA_TIPOS = (
    "INSERT INTO recaudo_tipos_gasto (empresa_id, nombre, orden) VALUES "
    + ", ".join(f"({EMPRESA_POR_DEFECTO}, '{n}', {i})" for i, n in enumerate(TIPOS_GASTO_INICIALES, 1))
    + " ON CONFLICT DO NOTHING"
)

# Una sola liquidación vigente por bus y día; las anuladas se conservan aparte.
_UNICA_ACTIVA = ("CREATE UNIQUE INDEX IF NOT EXISTS uq_recaudos_bus_fecha_vigente "
                 "ON recaudos(bus_id, fecha) WHERE anulado_at IS NULL")

# Columnas de dinero de un encabezado o de un tramo de conductor.
_TOTALES = """
        producido            INTEGER NOT NULL,
        total_gastos         INTEGER NOT NULL DEFAULT 0,
        neto                 INTEGER NOT NULL,
        recaudado            INTEGER NOT NULL,
        diferencia           INTEGER NOT NULL,"""


def _tablas(serial, ts, ts_default, ref_empresa):
    """Sentencias comunes a ambos motores, con los tipos de cada uno."""
    return [
        f"""CREATE TABLE IF NOT EXISTS recaudo_tarifas (
            empresa_id  INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            grupo       TEXT    NOT NULL CHECK (grupo IN ('A', 'B')),
            valor       INTEGER NOT NULL CHECK (valor >= 0),
            usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            updated_at  {ts} {ts_default},
            PRIMARY KEY (empresa_id, grupo)
        )""",
        _SEMILLA_TARIFAS,

        f"""CREATE TABLE IF NOT EXISTS recaudo_tipos_gasto (
            id          {serial},
            empresa_id  INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            nombre      TEXT    NOT NULL,
            orden       INTEGER NOT NULL DEFAULT 0,
            activo      INTEGER NOT NULL DEFAULT 1,
            created_at  {ts} {ts_default},
            UNIQUE (empresa_id, nombre)
        )""",
        _SEMILLA_TIPOS,

        f"""CREATE TABLE IF NOT EXISTS recaudo_cierres (
            id                      {serial},
            empresa_id              INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            usuario_id              INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            usuario_nombre          TEXT,
            cerrado_por             INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            cerrado_at              {ts} {ts_default},
            desde_at                {ts},
            hasta_at                {ts},
            liquidaciones           INTEGER NOT NULL,
            pasajeros               INTEGER NOT NULL,
            producido               INTEGER NOT NULL,
            total_gastos            INTEGER NOT NULL,
            neto                    INTEGER NOT NULL,
            recaudado               INTEGER NOT NULL,
            diferencia_conductores  INTEGER NOT NULL,
            efectivo                INTEGER NOT NULL,
            diferencia_caja         INTEGER NOT NULL,
            planilla                TEXT,
            observacion             TEXT,
            liquidacion_ids         TEXT NOT NULL,
            reabierto_at            {ts},
            reabierto_por           INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            motivo_reapertura       TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_recaudo_cierres_usuario ON recaudo_cierres(usuario_id, cerrado_at)",

        f"""CREATE TABLE IF NOT EXISTS recaudos (
            id                   {serial},
            empresa_id           INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            fecha                DATE    NOT NULL,
            bus_id               INTEGER NOT NULL REFERENCES buses(id),
            registradora_inicio  INTEGER NOT NULL,
            registradora_fin     INTEGER NOT NULL,
            pasajeros            INTEGER NOT NULL,
            tarifa               INTEGER NOT NULL,{_TOTALES}
            observacion          TEXT,
            usuario_id           INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            created_at           {ts} {ts_default},
            anulado_at           {ts},
            anulado_por          INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            motivo_anulacion     TEXT,
            cierre_id            INTEGER REFERENCES recaudo_cierres(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_recaudos_fecha ON recaudos(fecha)",
        _UNICA_ACTIVA,

        f"""CREATE TABLE IF NOT EXISTS recaudo_conductores (
            id                   {serial},
            recaudo_id           INTEGER NOT NULL REFERENCES recaudos(id) ON DELETE CASCADE,
            orden                INTEGER NOT NULL CHECK (orden BETWEEN 1 AND 3),
            conductor_id         INTEGER NOT NULL REFERENCES conductores(id),
            ruta_id              INTEGER REFERENCES rutas(id),
            viajes               INTEGER,
            registradora_inicio  INTEGER NOT NULL,
            registradora_fin     INTEGER NOT NULL,
            pasajeros            INTEGER NOT NULL,{_TOTALES}
            observacion          TEXT,
            UNIQUE (recaudo_id, orden)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_recaudo_conductores_conductor ON recaudo_conductores(conductor_id)",

        f"""CREATE TABLE IF NOT EXISTS recaudo_gastos (
            id               {serial},
            recaudo_id       INTEGER NOT NULL REFERENCES recaudos(id) ON DELETE CASCADE,
            orden_conductor  INTEGER NOT NULL DEFAULT 1 CHECK (orden_conductor BETWEEN 1 AND 3),
            tipo_gasto_id    INTEGER NOT NULL REFERENCES recaudo_tipos_gasto(id),
            tipo_nombre      TEXT    NOT NULL,
            valor            INTEGER NOT NULL CHECK (valor > 0),
            observacion      TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_recaudo_gastos_recaudo ON recaudo_gastos(recaudo_id)",

        f"""CREATE TABLE IF NOT EXISTS recaudo_conceptos (
            id            {serial},
            empresa_id    INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            nombre        TEXT    NOT NULL,
            cuenta        TEXT    NOT NULL,
            tercero       TEXT    NOT NULL CHECK (tercero IN ('PROPIETARIO', 'PAGADOR', 'NINGUNO', 'FIJO')),
            nit_fijo      TEXT,
            signo         INTEGER NOT NULL CHECK (signo IN (1, 2)),
            centro_costo  TEXT,
            descripcion   TEXT,
            referencia    TEXT    NOT NULL DEFAULT '' CHECK (referencia IN ('', 'VEHICULO')),
            uso           TEXT,
            orden         INTEGER NOT NULL DEFAULT 0,
            activo        INTEGER NOT NULL DEFAULT 1,
            created_at    {ts} {ts_default},
            UNIQUE (empresa_id, nombre)
        )""",
        _SEMILLA_CONCEPTOS,

        f"""CREATE TABLE IF NOT EXISTS recaudo_config (
            empresa_id  INTEGER NOT NULL DEFAULT {EMPRESA_POR_DEFECTO}{ref_empresa},
            clave       TEXT    NOT NULL,
            valor       TEXT,
            PRIMARY KEY (empresa_id, clave)
        )""",
        _SEMILLA_CONFIG,
    ]


# Columnas agregadas después: cierre de caja en `recaudos` y propietario según la
# tarjeta de propiedad en `buses` (tercero de las líneas de recaudo del archivo plano).
_COLUMNAS_PG = [
    "ALTER TABLE recaudos ADD COLUMN IF NOT EXISTS cierre_id INTEGER REFERENCES recaudo_cierres(id)",
    "ALTER TABLE buses ADD COLUMN IF NOT EXISTS tp_propietario_nombre TEXT",
    "ALTER TABLE buses ADD COLUMN IF NOT EXISTS tp_propietario_documento TEXT",
]
_COLUMNAS_SQLITE = [
    "ALTER TABLE recaudos ADD COLUMN cierre_id INTEGER REFERENCES recaudo_cierres(id)",
    "ALTER TABLE buses ADD COLUMN tp_propietario_nombre TEXT",
    "ALTER TABLE buses ADD COLUMN tp_propietario_documento TEXT",
]
_INDICES = ["CREATE INDEX IF NOT EXISTS idx_recaudos_caja ON recaudos(usuario_id, cierre_id)"]

_PG = _tablas("SERIAL PRIMARY KEY", "TIMESTAMPTZ", "NOT NULL DEFAULT now()", " REFERENCES empresas(id)")
_SQLITE = _tablas("INTEGER PRIMARY KEY AUTOINCREMENT", "TEXT", "DEFAULT CURRENT_TIMESTAMP", "")


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
        for sql in _COLUMNAS_SQLITE:
            try:
                db.execute(sql)
            except Exception:
                pass   # la columna ya existe
        for sql in _INDICES:
            db.execute(sql)
        db.commit()
        return

    for sql in _PG + _COLUMNAS_PG + _INDICES:
        try:
            db.execute(sql)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[recaudo.migrar] {e}")
    for tabla in TABLAS_PROTEGIDAS:
        try:
            _proteger(db, tabla)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[recaudo.migrar] RLS {tabla}: {e}")
