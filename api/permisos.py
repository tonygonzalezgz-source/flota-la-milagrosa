"""Permisos por usuario: qué módulos ve cada cuenta y si solo ve o también modifica.

Pedido del usuario (2026-11-05): crear usuarios desde Catálogo y elegir con casillas
sus módulos. Reglas:
- Una cuenta SIN filas en `usuario_permisos` usa los permisos estándar de su rol
  (ROLE_VIEWS / require_role), exactamente como antes. Así siguen todas las cuentas
  que ya existían.
- Una cuenta CON filas solo entra a lo marcado. El servidor decide con VISTA_API:
  cada endpoint que no sea solo del Administrador pasa únicamente si una vista
  marcada lo usa; con nivel "ver", solo los que leen.
- El rol sigue siendo el "tipo de cuenta": decide de quién son los datos (un
  propietario solo ve sus buses, el recaudador no cambia la registradora…).
- El Administrador no se personaliza: siempre tiene todo.

Al agregar una pantalla o un endpoint que una cuenta personalizada deba usar,
anotarlo aquí; si no, esa cuenta recibe 403 (falla cerrado, nunca abierto)."""

VER, MODIFICAR = "ver", "modificar"
NIVELES = (VER, MODIFICAR)


def _api(*rutas):
    """'GET /api/x' → ('GET', '/api/x'). Las rutas van con la sintaxis de Flask."""
    return frozenset(tuple(r.split(" ", 1)) for r in rutas)


BUSES = ("GET /api/buses", "GET /api/buses/<int:bus_id>")

# Endpoints de cada vista. "ver" = lo que la pantalla lee; "modificar" = lo que
# guarda o borra. Lo que es solo del Administrador (anular, reabrir, tarifas,
# cuentas…) no va aquí: require_role("Administrador") lo sigue cerrando.
VISTA_API = {
    "dashboard": {
        VER: _api(*BUSES, "GET /api/despacho", "GET /api/documentos/alertas",
                  "GET /api/mantenimiento/alertas", "GET /api/movilidad/rango",
                  "GET /api/gps/localizables", "GET /api/gps/localizar",
                  "GET /api/alistamiento/reporte"),
        # Desde el reporte de alistamientos se envían novedades a mantenimiento.
        MODIFICAR: _api("POST /api/mantenimiento/registro"),
    },
    "historial": {
        VER: _api(*BUSES, "GET /api/conductores", "GET /api/despacho", "GET /api/propietarios",
                  "GET /api/movilidad", "GET /api/movilidad/rango", "GET /api/movilidad/fechas",
                  "GET /api/movilidad/recaudo-sensores"),
        MODIFICAR: _api("PUT /api/movilidad/batch", "DELETE /api/movilidad/fecha/<fecha>",
                        "POST /api/movilidad/enviar-whatsapp"),
    },
    "mant": {
        VER: _api(*BUSES, "GET /api/mantenimiento/alertas", "GET /api/mantenimiento/config/<int:bus_id>",
                  "GET /api/mantenimiento/estado/<int:bus_id>",
                  "GET /api/mantenimiento/historial/<int:bus_id>", "GET /api/alistamiento/reporte"),
        MODIFICAR: _api("POST /api/mantenimiento/config", "PUT /api/mantenimiento/estado",
                        "POST /api/mantenimiento/historial", "POST /api/mantenimiento/registro"),
    },
    "propietario": {
        VER: _api(*BUSES, "GET /api/dashboard/propietario", "GET /api/documentos/alertas",
                  "GET /api/mantenimiento/estado-flota", "GET /api/movilidad", "GET /api/movilidad/rango",
                  "GET /api/movilidad/fechas", "GET /api/despacho/historial",
                  "GET /api/recaudo/propietario", "GET /api/recaudo/propietario/resumen",
                  "GET /api/recaudo/propietario/diario",
                  "GET /api/gps/localizables", "GET /api/gps/localizar"),
    },
    "gastos": {
        VER: _api(*BUSES, "GET /api/gastos", "GET /api/gastos/<int:gasto_id>/comprobante"),
        MODIFICAR: _api("POST /api/gastos", "DELETE /api/gastos/<int:gasto_id>"),
    },
    "tecnologia": {
        VER: _api(*BUSES, "GET /api/tecnologia"),
        MODIFICAR: _api("POST /api/tecnologia", "DELETE /api/tecnologia/<int:int_id>"),
    },
    "eds": {
        VER: _api("GET /api/eds", "GET /api/eds/<int:act_id>/fotos"),
        MODIFICAR: _api("POST /api/eds"),
    },
    "lavada": {
        VER: _api(*BUSES, "GET /api/lavada", "GET /api/lavada/<int:act_id>/fotos"),
        MODIFICAR: _api("POST /api/lavada"),
    },
    "despacho": {
        VER: _api(*BUSES, "GET /api/despacho", "GET /api/conductores", "GET /api/alistamiento",
                  "GET /api/alistamiento/historial"),
        # El despachador también llena el alistamiento desde la tarjeta del bus.
        MODIFICAR: _api("PUT /api/despacho/batch", "PUT /api/despacho/relevos", "POST /api/alistamiento"),
    },
    # Corregir el historial (registradora, relevos de días pasados) es del Administrador.
    "historial-despacho": {
        VER: _api(*BUSES, "GET /api/despacho/historial", "GET /api/conductores"),
    },
    "alistamiento": {
        VER: _api("GET /api/despacho", "GET /api/alistamiento", "GET /api/alistamiento/historial"),
        MODIFICAR: _api("POST /api/alistamiento"),
    },
    "chequeo": {
        VER: _api("GET /api/chequeo/historial"),
        MODIFICAR: _api("GET /api/chequeo/hoy", "POST /api/chequeo/llegada", "POST /api/chequeo/salida"),
    },
    # Config GPS: cambiar el dispositivo de un bus es del Administrador.
    "mapa": {
        VER: _api(*BUSES, "GET /api/gps/dispositivos", "GET /api/gps/traccar/devices"),
    },
    # Asignar puntos de control a los buses: en pantalla solo lo hace el Administrador.
    "relojes": {
        VER: _api(*BUSES, "GET /api/gps/localizables", "GET /api/gps/relojes/reporte",
                  "GET /api/gps/geocercas", "GET /api/gps/bus-relojes"),
    },
    "mb-mapa": {
        VER: _api(*BUSES, "GET /api/monitoreo/vivo", "GET /api/monitoreo/vivo/<int:bus_id>/dia",
                  "GET /api/monitoreo/encierros", "GET /api/monitoreo/mapa-config",
                  "GET /api/monitoreo/rutas", "GET /api/monitoreo/rutas/geometria"),
    },
    "mb-reportes": {
        VER: _api(*BUSES, "GET /api/monitoreo/mapa-config", "GET /api/monitoreo/reportes",
                  "GET /api/monitoreo/reportes/recorrido", "GET /api/monitoreo/rutas",
                  "GET /api/monitoreo/rutas/geometria"),
    },
    "recaudo-diario": {
        VER: _api("GET /api/recaudo/dia", "GET /api/recaudo/tarifas", "GET /api/recaudo/tipos-gasto"),
        MODIFICAR: _api("POST /api/recaudo", "POST /api/recaudo/relevo", "POST /api/recaudo/pendiente",
                        "POST /api/recaudo/<int:recaudo_id>/reimpresion"),
    },
    "recaudo-pagos": {
        VER: _api("GET /api/recaudo/pagos", "GET /api/recaudo/terceros", "GET /api/recaudo/conceptos"),
        MODIFICAR: _api("POST /api/recaudo/pagos", "POST /api/recaudo/pagos/<int:pago_id>/reimpresion",
                        "POST /api/recaudo/terceros"),
    },
    # Catálogo sin las cuentas de acceso: crear o editar usuarios, sus permisos y sus
    # buses o rutas (/api/admin/...) es SOLO del Administrador (pedido del usuario 2026-11-05).
    "catalogo": {
        VER: _api(*BUSES, "GET /api/propietarios", "GET /api/conductores",
                  "GET /api/recaudo/conceptos", "GET /api/recaudo/terceros"),
        MODIFICAR: _api("POST /api/buses", "PUT /api/buses/<int:bus_id>", "DELETE /api/buses/<int:bus_id>",
                        "PUT /api/tarifas/<int:tarifa_id>",
                        "POST /api/rutas", "PUT /api/rutas/<int:ruta_id>", "DELETE /api/rutas/<int:ruta_id>",
                        "POST /api/conductores", "PUT /api/conductores/<int:cid>",
                        "DELETE /api/conductores/<int:cid>",
                        "POST /api/puestos", "PUT /api/puestos/<int:pid>", "DELETE /api/puestos/<int:pid>",
                        "POST /api/recaudo/conceptos", "PUT /api/recaudo/conceptos/<int:concepto_id>",
                        "PUT /api/recaudo/config-contable",
                        "POST /api/recaudo/terceros", "PUT /api/recaudo/terceros/<int:tercero_id>"),
    },
    "recaudo-caja": {
        VER: _api("GET /api/recaudo/caja", "GET /api/recaudo/cierres", "GET /api/recaudo/cierres/<int:cierre_id>"),
        MODIFICAR: _api("POST /api/recaudo/caja/cerrar"),
    },
}

# Cómo se muestran en Catálogo, en orden. `ayuda` explica qué agrega "Modificar"
# (o por qué no existe). El orden es también el de allowedViews (la primera vista
# es la que abre al entrar).
GRUPOS = (
    ("Operación", (
        ("despacho", "Despacho", "Modificar: despachar los buses, anotar relevos y el alistamiento"),
        ("historial-despacho", "Historial Despacho", "Corregir días pasados es solo del administrador"),
        ("alistamiento", "Alistamiento", "Modificar: llenar el alistamiento del bus"),
        ("chequeo", "Chequeo Despachadores", "Modificar: marcar llegada y salida en el puesto"),
    )),
    ("Movilidad", (
        ("dashboard", "Dashboard", "Modificar: enviar novedades del reporte de alistamientos a mantenimiento"),
        ("historial", "Historial Movilidad", "Modificar: guardar o borrar la movilidad y enviarla por WhatsApp"),
    )),
    ("Recaudo", (
        ("recaudo-diario", "Recaudo diario", "Modificar: liquidar y reimprimir tirillas (anular es del administrador)"),
        ("recaudo-pagos", "Pagos diarios", "Modificar: registrar pagos y terceros (anular es del administrador)"),
        ("recaudo-caja", "Cierre de caja", "Modificar: cerrar su caja (reabrir es del administrador)"),
    )),
    ("Monitoreo GPS", (
        ("mb-mapa", "Mapa en vivo", ""),
        ("mb-reportes", "Reportes de recorrido", ""),
        ("relojes", "Puntos de Control", "Asignar puntos de control es solo del administrador"),
        ("mapa", "Config GPS", "Cambiar equipos es solo del administrador"),
    )),
    ("Mantenimiento y flota", (
        ("mant", "Mantenimiento", "Modificar: registrar mantenimientos y cambiar el estado del bus"),
        ("tecnologia", "Disp. Tecnológicos", "Modificar: registrar y borrar intervenciones"),
        ("eds", "Operador EDS", "Modificar: registrar el aseo de la estación"),
        ("lavada", "Lavada Primeriada", "Modificar: registrar lavadas"),
    )),
    ("Propietarios", (
        ("propietario", "Mis Buses", "Un propietario solo ve sus buses; los demás ven toda la flota"),
        ("gastos", "Gastos y Facturas", "Modificar: subir y borrar gastos"),
    )),
    ("Administración", (
        ("catalogo", "Catálogo", "Modificar: buses, tarifas, rutas, conductores, puestos y recaudo. "
                                 "Las cuentas de acceso son solo del administrador"),
    )),
)

# Nunca se delegan: la auditoría y los equipos y trazados del monitoreo. Las cuentas
# de acceso (dentro de Catálogo) tampoco: ver NUNCA_DELEGABLE.
SOLO_ADMIN = (
    ("cuentas", "Cuentas de acceso (crear y editar usuarios)"),
    ("auditoria", "Historial de modificaciones"),
    ("mb-rutas", "Rutas Geográficas"),
    ("mb-equipos", "Equipos GPS"),
)

# Endpoints que ninguna cuenta personalizada usa, aunque un módulo marcado los
# nombrara por error: cuentas de acceso y auditoría.
NUNCA_DELEGABLE = ("/api/admin/", "/api/auditoria")

ORDEN = tuple(v for _, vistas in GRUPOS for v, _, _ in vistas)
DELEGABLES = frozenset(ORDEN)
CON_MODIFICAR = frozenset(v for v in ORDEN if VISTA_API[v].get(MODIFICAR))

# Plantilla de cada tipo de cuenta: lo que hoy puede hacer ese rol en el servidor.
PLANTILLAS = {
    "Analista": {"despacho": MODIFICAR, "historial-despacho": VER, "alistamiento": MODIFICAR,
                 "chequeo": VER, "dashboard": MODIFICAR, "historial": MODIFICAR, "tecnologia": VER},
    "Técnico Mant.": {"mant": MODIFICAR},
    "Técnico Cámaras": {"tecnologia": MODIFICAR},
    "Jefe Op. Tecnológicas": {"tecnologia": MODIFICAR},
    "Operador EDS": {"eds": MODIFICAR},
    "Operador Lavada": {"lavada": MODIFICAR},
    "Propietario": {"propietario": VER, "gastos": MODIFICAR, "tecnologia": VER, "lavada": VER, "mb-mapa": VER},
    "Despachador": {"despacho": MODIFICAR, "historial-despacho": VER, "chequeo": MODIFICAR,
                    "mb-mapa": VER, "mb-reportes": VER, "relojes": VER, "mapa": VER},
    "Jefe de Ruta": {"despacho": MODIFICAR, "historial-despacho": VER, "alistamiento": MODIFICAR,
                     "chequeo": MODIFICAR, "dashboard": MODIFICAR, "mb-mapa": VER, "mb-reportes": VER,
                     "relojes": VER},
    "Conductor": {"alistamiento": MODIFICAR},
    "Recaudador": {"recaudo-diario": MODIFICAR, "recaudo-pagos": MODIFICAR, "recaudo-caja": MODIFICAR,
                   "historial": VER, "despacho": VER, "historial-despacho": VER, "chequeo": VER,
                   "alistamiento": VER},
}

# Cuentas que se filtran por SUS buses (usuario_buses): solo pueden recibir los
# módulos que respetan ese filtro y nunca más nivel del que trae su plantilla.
# Darle a un propietario, p. ej., el despacho le mostraría los buses de otros.
TOPES = {rol: PLANTILLAS[rol] for rol in ("Propietario", "Técnico Mant.")}


def _rango(nivel):
    return NIVELES.index(nivel)


def limpiar(rol, permisos):
    """Valida lo que manda Catálogo. Devuelve (permisos_limpios, error).
    permisos_limpios = {} significa "permisos estándar del rol" (cuando lo marcado
    es igual a la plantilla, no se guarda: la cuenta sigue el rol)."""
    if rol == "Administrador":
        return {}, None   # el administrador siempre tiene todo
    if not isinstance(permisos, dict):
        return None, "Los permisos no tienen el formato esperado."
    tope = TOPES.get(rol)
    limpios = {}
    for vista, nivel in permisos.items():
        if vista not in DELEGABLES:
            return None, f"El módulo «{vista}» no se puede asignar."
        if nivel not in NIVELES:
            return None, f"Nivel no válido para «{vista}»."
        if nivel == MODIFICAR and vista not in CON_MODIFICAR:
            nivel = VER
        if tope is not None:
            if vista not in tope:
                return None, (f"Una cuenta de {rol} solo puede tener módulos con sus propios buses: "
                              + ", ".join(nombre(v) for v in tope) + ".")
            if _rango(nivel) > _rango(tope[vista]):
                nivel = tope[vista]
        limpios[vista] = nivel
    if not limpios:
        return None, "Marca al menos un módulo."
    if limpios == PLANTILLAS.get(rol):
        return {}, None
    return limpios, None


def ajustar_a_rol(rol, permisos):
    """Al cambiar el rol de una cuenta personalizada: quita lo que el nuevo rol no
    admite. Devuelve los permisos a guardar ({} = estándar del rol)."""
    if rol == "Administrador" or not permisos:
        return {}
    tope = TOPES.get(rol)
    if tope is not None:
        permisos = {v: min(n, tope[v], key=_rango) for v, n in permisos.items() if v in tope}
    if not permisos or permisos == PLANTILLAS.get(rol):
        return {}
    return permisos


def vistas(permisos):
    """(allowedViews, soloLectura) de una cuenta personalizada, en el orden del menú."""
    permitidas = [v for v in ORDEN if v in permisos]
    return permitidas, [v for v in permitidas if permisos[v] == VER]


def api_permitida(permisos, metodo, regla):
    """None si una vista marcada permite el endpoint; si no, el motivo del 403."""
    if regla.startswith(NUNCA_DELEGABLE):
        return "No autorizado para esta acción"
    if metodo == "HEAD":
        metodo = "GET"
    clave = (metodo, regla)
    solo_ver = False
    for vista, nivel in permisos.items():
        acceso = VISTA_API.get(vista)
        if not acceso:
            continue
        if clave in acceso.get(VER, ()):
            return None
        if clave in acceso.get(MODIFICAR, ()):
            if nivel == MODIFICAR:
                return None
            solo_ver = True
    if solo_ver:
        return "Solo tienes permiso para ver este módulo."
    return "No autorizado para esta acción"


_NOMBRES = {v: n for _, vistas_ in GRUPOS for v, n, _ in vistas_}


def nombre(vista):
    return _NOMBRES.get(vista, vista)


def resumen(perms):
    """"Despacho (modificar), Chequeo Despachadores (ver)…" en el orden del menú."""
    return ", ".join(f"{nombre(v)} ({perms[v]})" for v in ORDEN if v in perms)


def describir_cambio(antes, despues):
    """Texto corto para el historial de modificaciones."""
    if not despues:
        return "volvió a los permisos estándar del rol"
    partes = []
    for v in ORDEN:
        a, d = (antes or {}).get(v), despues.get(v)
        if a == d:
            continue
        if d is None:
            partes.append(f"quitó {nombre(v)}")
        elif a is None:
            partes.append(f"agregó {nombre(v)} ({d})")
        else:
            partes.append(f"{nombre(v)}: {a} → {d}")
    if not antes:
        partes.insert(0, "personalizó los permisos")
    return "; ".join(partes) or "sin cambios"


def catalogo():
    """Lo que necesita la pantalla de Catálogo para armar la tabla de casillas."""
    return {
        "grupos": [{"nombre": g, "vistas": [{"clave": v, "nombre": n, "ayuda": a,
                                             "modificar": v in CON_MODIFICAR}
                                            for v, n, a in vistas_]}
                   for g, vistas_ in GRUPOS],
        "solo_admin": [{"clave": v, "nombre": n} for v, n in SOLO_ADMIN],
        "plantillas": PLANTILLAS,
        "topes": TOPES,
    }
