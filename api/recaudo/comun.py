"""Utilidades compartidas del módulo Recaudo.

Igual que Monitoreo, vive fuera de app.py: app.py le inyecta sus dependencias
con `configurar()` al arrancar, lo que evita la importación circular."""
from functools import wraps

# Mientras exista una sola empresa, todo lo nuevo queda en la #1 (La Milagrosa).
EMPRESA_POR_DEFECTO = 1

# Escritura y lectura del recaudo. Eliminar y cambiar tarifas: solo Administrador.
ROLES_RECAUDO = ("Administrador", "Recaudador")

# Tarifa inicial por grupo de vehículo (A = buses, B = micros), en pesos.
TARIFAS_INICIALES = {"A": 3050, "B": 3200}

# Gastos que el conductor reporta al liquidar (el Administrador agrega más desde Recaudo).
TIPOS_GASTO_INICIALES = ("ACPM", "Varios", "Taller", "Auxilio de transporte")

# Conceptos contables de la caja (tabla que pasó el usuario el 2026-10-09).
# tercero: PROPIETARIO (del vehículo, según la tarjeta de propiedad), PAGADOR (quien
# paga, p. ej. el arrendador del local), NINGUNO o FIJO (nit_fijo). signo: 1 débito,
# 2 crédito. `uso` = los que arma el sistema en el archivo plano del cierre.
CONCEPTOS_INICIALES = (
    {"nombre": "CIERRE DE CAJA", "cuenta": "138005", "tercero": "FIJO", "nit_fijo": "1001577609",
     "signo": 1, "centro_costo": "1", "uso": "CIERRE_CAJA"},
    {"nombre": "RECAUDOS CU", "cuenta": "28050504", "tercero": "PROPIETARIO", "signo": 2,
     "descripcion": "RECAUDO CU VH X", "referencia": "VEHICULO", "uso": "RECAUDO_VEHICULO"},
    {"nombre": "PAGO ADMON", "cuenta": "28050501", "tercero": "PROPIETARIO", "signo": 2},
    {"nombre": "PAGO SERVICIOS", "cuenta": "28150530", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO LOCALES", "cuenta": "28150530", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO PARQUEOS", "cuenta": "28150530", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO LAVADAS", "cuenta": "28150530", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO FICHO", "cuenta": "28150595", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO TABLA", "cuenta": "28150595", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "PAGO EXAMEN MEDICO", "cuenta": "425050", "tercero": "PAGADOR", "signo": 2, "centro_costo": "1"},
    {"nombre": "ABONO SINIESTRO", "cuenta": "132507", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "ABONO PRESTAMO PROPIETARIO", "cuenta": "28050504", "tercero": "PROPIETARIO", "signo": 2},
    {"nombre": "ABONO PRESTAMO EMPRESA", "cuenta": "138095", "tercero": "PAGADOR", "signo": 2},
    {"nombre": "ANTICIPO VEHICULOS", "cuenta": "28050504", "tercero": "PROPIETARIO", "signo": 1,
     "descripcion": "CREADA POR XIMENA"},
    {"nombre": "REEMBOLSO CAJA OFICINA", "cuenta": "11050501", "tercero": "NINGUNO", "signo": 1},
    {"nombre": "OTROS PAGOS DE CAJA XIMENA", "cuenta": "11050501", "tercero": "NINGUNO", "signo": 1,
     "descripcion": "CREADA POR XIMENA"},
)

# Datos fijos del comprobante contable (archivo plano).
CONFIG_CONTABLE_INICIAL = {"nit_compania": "890901489", "tipo_comprobante": "CU", "moneda": "1"}

# Máximo de conductores que pueden liquidar un mismo bus en el día (relevos).
MAX_CONDUCTORES = 3

# Puesta en marcha (2026-10-10): mientras se prueba con datos reales, todo el
# recaudo responde solo al Administrador; Recaudador y Propietario reciben 403 y
# no ven las vistas. Para abrirlo a los demás roles basta con ponerlo en False.
SOLO_ADMIN = True

_deps = {}


def configurar(get_db, require_role, database_url, hoy_bogota, sync_pax_movilidad):
    _deps.update(get_db=get_db, require_role=require_role, database_url=database_url or "",
                 hoy_bogota=hoy_bogota, sync_pax_movilidad=sync_pax_movilidad)


def db():
    return _deps["get_db"]()


def es_pg():
    return bool(_deps.get("database_url"))


def hoy_bogota():
    return _deps["hoy_bogota"]()


def sync_pax_movilidad(conn, fecha, pax_por_bus):
    return _deps["sync_pax_movilidad"](conn, fecha, pax_por_bus)


def rol(*roles):
    """Igual que require_role de app.py, resuelto en tiempo de request."""
    def wrapper(f):
        @wraps(f)
        def inner(*args, **kwargs):
            permitidos = tuple(r for r in roles if r == "Administrador") if SOLO_ADMIN else roles
            return _deps["require_role"](*permitidos)(f)(*args, **kwargs)
        return inner
    return wrapper
