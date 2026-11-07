"""Recaudo diario: consulta del día, liquidación por bus, anulación, tarifas,
tipos de gasto y la vista del propietario.

Reglas:
- El servidor recalcula todo; no confía en el cliente:
    producido  = pasajeros × tarifa
    neto       = producido − gastos      (lo que el conductor debe entregar), aproximado a la
                 mil más cercana: desde $500 sube, por debajo baja (326.900 → 327.000;
                 326.400 → 326.000). Con relevo, cada conductor por aparte; el del bus es la suma.
    diferencia = recaudado − neto        (negativa = faltante, positiva = sobrante)
    Si los gastos superan el producido, el neto del conductor queda negativo: la empresa
    le debe esa plata (queda debiendo, no sale de la caja). Entonces no tiene nada por
    entregar y la diferencia se cuenta contra $0 (pedido del usuario 2026-11-03: antes
    salía como "sobrante"). El neto del bus es solo lo que hay por entregar.
- Pasajeros por conductor = su tramo de registradora (el conductor 1 va de la
  lectura inicial del bus a la del relevo, el último termina en la final).
- La registradora del recaudo corrige también el despacho del mismo (bus, fecha)
  y, con él, los pasajeros de movilidad diaria: una sola fuente de verdad.
- Una liquidación guardada NO se edita ni se borra. Solo el Administrador puede
  anularla (con motivo); queda en el historial y el bus vuelve a quedar por liquidar.
- Buses con sensores (sin registradora): el recaudador digita los pasajeros del día; la
  movilidad sigue siendo la de la analista y Movilidad diaria muestra la diferencia.
- Recaudador liquida los últimos 7 días (hora Bogotá; domingos y festivos se ponen al día
  después). Administrador: cualquier día ya ocurrido.
- Recaudador no cambia la registradora que trae el despacho: solo llena la que falta
  (ver _lecturas_del_despacho). El Administrador sí la corrige.
- Si la inicial no sigue el consecutivo (marcaron la registradora con el bus en taller o
  descanso), se liquida igual desde la inicial del día y el salto queda en el historial.
- El propietario ve las liquidaciones vigentes de SUS buses (filtro por el token).
- Todo cambio queda en el historial de modificaciones (auditoría).
"""
import re
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

import auditoria

from . import bp
from .comun import (EMPRESA_POR_DEFECTO, MAX_CONDUCTORES, ROLES_RECAUDO, db, es_pg, hoy_bogota,
                    relevos_por_bus, rol, sync_pax_movilidad)

ADMIN = ("Administrador",)
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TARIFA_MAXIMA = 100000
_GASTO_MAXIMO = 10_000_000
_GRUPO_NOMBRE = {"A": "buses", "B": "micros"}


class _Rechazo(Exception):
    """Error de validación con su código HTTP."""
    def __init__(self, mensaje, status=400):
        super().__init__(mensaje)
        self.status = status


def _fecha_valida(valor):
    if not valor or not _RE_FECHA.match(str(valor)):
        return None
    try:
        date.fromisoformat(valor)
    except ValueError:
        return None
    return valor


def _entero(valor, etiqueta, requerido=True):
    """Entero >= 0. Vacío → None si no es requerido; si no, _Rechazo."""
    if valor in (None, "", "null"):
        if requerido:
            raise _Rechazo(f"Falta llenar: {etiqueta[0].lower()}{etiqueta[1:]}")
        return None
    if isinstance(valor, bool) or (isinstance(valor, float) and not valor.is_integer()):
        raise _Rechazo(f"{etiqueta} debe ser un número entero")
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise _Rechazo(f"{etiqueta} debe ser un número entero")
    if n < 0:
        raise _Rechazo(f"{etiqueta} no puede ser negativo")
    return n


def _texto(valor, largo=500):
    """Texto libre del recaudo: todo queda en mayúscula (pedido del usuario 2026-11-02)."""
    return (str(valor or "").strip().upper()[:largo]) or None


def aproximar_mil(valor):
    """Lo que entrega el conductor, a la mil más cercana (pedido del usuario 2026-10-27):
    desde $500 sube y por debajo baja. Mismo resultado que ROUND(valor; -3) de Excel."""
    signo = -1 if valor < 0 else 1
    return signo * ((abs(valor) + 500) // 1000 * 1000)


def _ahora():
    dt = datetime.now(timezone.utc)
    return dt if es_pg() else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hora_utc(v):
    """Marca de tiempo de la BD → 'AAAA-MM-DDTHH:MM:SSZ' (UTC); el frontend la muestra en hora Bogotá."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.replace(" ", "T")
        return s if s.endswith("Z") or "+" in s[10:] else s + "Z"
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fecha_iso(v):
    """En Postgres DATE llega como objeto date; el frontend espera 'AAAA-MM-DD'."""
    return v if v is None or isinstance(v, str) else v.isoformat()


def _dia_bogota(v):
    """Marca de tiempo de la BD → día 'AAAA-MM-DD' en hora Bogotá (UTC-5 todo el año)."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.strip().replace(" ", "T").replace("Z", "+00:00"))
        except ValueError:
            return v[:10]
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return (v.astimezone(timezone.utc) - timedelta(hours=5)).date().isoformat()


def _fila(r):
    d = dict(r)
    d["fecha"] = _fecha_iso(d.get("fecha"))
    # Día de la caja: el día en que se recibió la plata (las de la base demo no lo traen)
    d["caja_fecha"] = _fecha_iso(d.get("caja_fecha")) or _dia_bogota(d.get("created_at"))
    for k in ("created_at", "anulado_at"):
        if k in d:
            d[k] = _hora_utc(d[k])
    return d


def dia_de_caja(conn, usuario_id, bus_id, fecha, parte=1):
    """Día de la caja en que entra una liquidación nueva: hoy, el día en que se recibe la
    plata (pedido del usuario 2026-11-05: no el día de la tarjeta). Si reemplaza a una
    anulada del mismo recaudador (mismo bus, día de tarjeta y parte) cuyo día de caja sigue
    abierto —reabierto para corregirlo, o aún sin cerrar—, entra a ese día: esa plata se
    recibió entonces, y así el día reabierto se vuelve a cerrar con la corrección."""
    hoy = hoy_bogota()
    fila = conn.execute(
        """SELECT caja_fecha, created_at FROM recaudos
            WHERE bus_id = ? AND fecha = ? AND usuario_id = ? AND parte = ? AND anulado_at IS NOT NULL
         ORDER BY id DESC LIMIT 1""",
        (bus_id, fecha, usuario_id, parte),
    ).fetchone()
    if not fila:
        return hoy
    f = dict(fila)
    dia = _fecha_iso(f["caja_fecha"]) or _dia_bogota(f["created_at"])
    if not dia or dia >= hoy:
        return hoy
    ultimo = conn.execute(
        "SELECT reabierto_at FROM recaudo_cierres WHERE usuario_id = ? AND fecha = ? ORDER BY id DESC LIMIT 1",
        (usuario_id, dia),
    ).fetchone()
    if ultimo is not None:
        return dia if dict(ultimo)["reabierto_at"] else hoy
    return dia if dia_sin_cerrar(conn, usuario_id, dia) else hoy


def dia_sin_cerrar(conn, usuario_id, dia):
    """True si la caja de ese día del recaudador nunca se ha cerrado y todavía tiene
    movimientos (liquidaciones o pagos) sin cerrar: sigue abierta. Un día sin
    movimientos no cuenta (no hay caja), ni uno que ya tuvo un cierre (para registrar
    ahí, el Administrador lo reabre)."""
    if conn.execute("SELECT 1 FROM recaudo_cierres WHERE usuario_id = ? AND fecha = ? LIMIT 1",
                    (usuario_id, dia)).fetchone():
        return False
    return bool(conn.execute(
        """SELECT 1 FROM recaudos WHERE usuario_id = ? AND caja_fecha = ?
              AND anulado_at IS NULL AND cierre_id IS NULL LIMIT 1""",
        (usuario_id, dia),
    ).fetchone() or conn.execute(
        """SELECT 1 FROM recaudo_pagos WHERE usuario_id = ? AND fecha = ?
              AND anulado_at IS NULL AND cierre_id IS NULL LIMIT 1""",
        (usuario_id, dia),
    ).fetchone())


def _miles(n):
    return f"{n:,}".replace(",", ".")


def por_entregar(neto):
    """Lo que el conductor debe entregar: nada si los gastos superan el producido."""
    return max(neto, 0)


def debe_conductor(neto):
    """Lo que la empresa le queda debiendo al conductor (gastos mayores que el producido)."""
    return max(-neto, 0)


def _resultado(diferencia):
    if diferencia < 0:
        return f"faltante {auditoria.pesos(-diferencia)}"
    if diferencia > 0:
        return f"sobrante {auditoria.pesos(diferencia)}"
    return "cuadrado"


def _tarifas(conn):
    filas = conn.execute(
        "SELECT grupo, valor FROM recaudo_tarifas WHERE empresa_id = ?", (EMPRESA_POR_DEFECTO,)
    ).fetchall()
    return {dict(f)["grupo"]: int(dict(f)["valor"]) for f in filas}


def _tipos_gasto(conn, solo_activos=True):
    filtro = " AND activo = 1" if solo_activos else ""
    filas = conn.execute(
        f"""SELECT id, nombre, orden, activo, fijo, requiere_detalle FROM recaudo_tipos_gasto
             WHERE empresa_id = ?{filtro} ORDER BY orden, nombre""",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()
    return [dict(f) for f in filas]


# Días hacia atrás que puede liquidar quien no es Administrador. Domingos y festivos no
# se liquida: se ponen al día después (domingo + lunes festivo, puentes, Semana Santa).
# Antes era solo hoy y ayer; ampliado por pedido del usuario 2026-11-03.
DIAS_ATRAS_RECAUDADOR = 7


def _puede_liquidar(fecha):
    """(True, None) o (False, motivo) según el rol y el día."""
    hoy = hoy_bogota()
    if fecha > hoy:
        return False, "No se puede liquidar un día que aún no ha llegado."
    if getattr(request, "jwt_user_rol", None) == "Administrador":
        return True, None
    limite = (date.fromisoformat(hoy) - timedelta(days=DIAS_ATRAS_RECAUDADOR)).isoformat()
    if fecha < limite:
        return False, (f"Este día ya está cerrado: se pueden liquidar los últimos "
                       f"{DIAS_ATRAS_RECAUDADOR} días. Solo el administrador puede liquidar días más antiguos.")
    return True, None


def _cargar(conn, where, params):
    """Liquidaciones completas (encabezado + bus + conductores con cédula + gastos)."""
    encabezados = conn.execute(
        f"""SELECT r.*, b.numero AS bus_numero, b.placa AS bus_placa, b.grupo AS bus_grupo,
                   u.nombre AS usuario_nombre, ua.nombre AS anulado_por_nombre
              FROM recaudos r
              JOIN buses b ON b.id = r.bus_id
         LEFT JOIN usuarios u  ON u.id  = r.usuario_id
         LEFT JOIN usuarios ua ON ua.id = r.anulado_por
             WHERE {where}
          ORDER BY b.numero, r.id""",
        params,
    ).fetchall()
    por_id = {}
    for e in encabezados:
        e = _fila(e)
        e["conductores"], e["gastos"] = [], []
        por_id[e["id"]] = e
    if por_id:
        marcas = ",".join("?" * len(por_id))
        for t in conn.execute(
            f"""SELECT rc.*, c.nombre AS conductor_nombre, c.cedula AS conductor_cedula,
                       ru.nombre AS ruta_nombre
                  FROM recaudo_conductores rc
             LEFT JOIN conductores c ON c.id = rc.conductor_id
             LEFT JOIN rutas ru ON ru.id = rc.ruta_id
                 WHERE rc.recaudo_id IN ({marcas})
              ORDER BY rc.recaudo_id, rc.orden""",
            list(por_id),
        ).fetchall():
            t = dict(t)
            por_id[t["recaudo_id"]]["conductores"].append(t)
        for g in conn.execute(
            f"""SELECT * FROM recaudo_gastos WHERE recaudo_id IN ({marcas})
              ORDER BY recaudo_id, orden_conductor, id""",
            list(por_id),
        ).fetchall():
            g = dict(g)
            por_id[g["recaudo_id"]]["gastos"].append(g)
    return list(por_id.values())


_SUMAS_PARTES = ("pasajeros", "producido", "total_gastos", "neto", "recaudado", "diferencia")


def _combinar(partes):
    """La liquidación del bus en el día con todas sus partes vigentes (la original y el
    relevo agregado, ver agregar_relevo): conductores y gastos juntos (cada conductor con
    su número en el bus) y los totales sumados. El encabezado es el de la parte 1; la
    registradora va de la inicial de la primera parte a la final de la última. `partes`
    lleva cada fila tal cual (su número, caja, tirilla y quién la liquidó)."""
    partes = sorted(partes, key=lambda p: (p.get("parte") or 1, p["id"]))
    total = sum(len(p["conductores"]) for p in partes)
    for p in partes:
        p["total_conductores"] = total
    if len(partes) == 1:
        unica = partes[0]
        return {**unica, "partes": [dict(unica)]}
    base = dict(partes[0])
    base["partes"] = [dict(p) for p in partes]
    base["conductores"] = [c for p in partes for c in p["conductores"]]
    base["gastos"] = [g for p in partes for g in p["gastos"]]
    for k in _SUMAS_PARTES:
        base[k] = sum(int(p[k] or 0) for p in partes)
    base["registradora_fin"] = partes[-1]["registradora_fin"]
    return base


def _liquidaciones_del_dia(conn, fecha, bus_id=None):
    """(vigentes, anuladas): vigentes = bus_id → liquidación (con sus partes juntas, ver
    _combinar); anuladas = bus_id → [liquidaciones]."""
    where, params = "r.fecha = ?", [fecha]
    if bus_id is not None:
        where, params = "r.fecha = ? AND r.bus_id = ?", [fecha, bus_id]
    partes, anuladas = {}, {}
    for e in _cargar(conn, where, params):
        if e["anulado_at"]:
            anuladas.setdefault(e["bus_id"], []).append(e)
        else:
            partes.setdefault(e["bus_id"], []).append(e)
    veces = reimpresiones(conn, "liquidacion", [e["id"] for lista in partes.values() for e in lista])
    for lista in partes.values():
        for e in lista:
            e["reimpresiones"] = veces.get(e["id"], 0)
    return {b: _combinar(lista) for b, lista in partes.items()}, anuladas


# ──────────────────────────────────────────
#  Reimprimir (tirilla de liquidación y recibo de pago diario)
# ──────────────────────────────────────────

# Si al guardar no salió la tirilla (papel, impresora apagada, se canceló), quien la
# registró puede reimprimirla UNA vez; las demás copias, el Administrador (pedido del
# usuario 2026-11-03). Cada reimpresión queda en la auditoría, que es la que se cuenta.
REIMPRESIONES_RECAUDADOR = 1


def reimpresiones(conn, entidad, ids):
    """{id: veces que se reimprimió} según la auditoría (entidad 'liquidacion' o 'pago')."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    filas = conn.execute(
        f"""SELECT entidad_id, COUNT(*) AS n FROM auditoria
             WHERE modulo = 'recaudo' AND entidad = ? AND accion = 'reimprimir'
               AND entidad_id IN ({marcas})
          GROUP BY entidad_id""",
        (entidad, *[str(i) for i in ids]),
    ).fetchall()
    return {int(dict(f)["entidad_id"]): int(dict(f)["n"]) for f in filas}


def autorizar_reimpresion(conn, entidad, registro_id, usuario_id, descripcion):
    """Anota la reimpresión o lanza _Rechazo. Quien no es Administrador solo reimprime lo
    que registró él y solo REIMPRESIONES_RECAUDADOR veces."""
    hechas = reimpresiones(conn, entidad, [registro_id]).get(registro_id, 0)
    if not _es_admin():
        if usuario_id != getattr(request, "jwt_user_id", None):
            raise _Rechazo("Solo quien la registró puede reimprimirla. Pide la copia al administrador.", 403)
        if hechas >= REIMPRESIONES_RECAUDADOR:
            raise _Rechazo("Ya se reimprimió una vez. Para otra copia, pide al administrador.", 403)
    auditoria.registrar(conn, "recaudo", entidad, registro_id, "reimprimir",
                        f"{descripcion} (reimpresión {hechas + 1})", {"reimpresion": hechas + 1})
    conn.commit()
    return hechas + 1


@bp.route("/api/recaudo/<int:recaudo_id>/reimpresion", methods=["POST"])
@rol(*ROLES_RECAUDO)
def reimprimir_liquidacion(recaudo_id):
    """Body: {orden?} (solo la tirilla de ese conductor). Devuelve las veces reimpresa."""
    data = request.get_json(silent=True) or {}
    conn = db()
    filas = _cargar(conn, "r.id = ?", [recaudo_id])
    if not filas:
        conn.close()
        return jsonify({"error": "Liquidación no encontrada"}), 404
    r = filas[0]
    orden = data.get("orden")
    cual = f", conductor {orden}" if orden else ""
    try:
        veces = autorizar_reimpresion(
            conn, "liquidacion", recaudo_id, r.get("usuario_id"),
            f"Reimprimió la tirilla de la liquidación N° {str(recaudo_id).zfill(6)} "
            f"(bus {r['bus_numero']} del {_fecha_iso(r['fecha'])}{cual})")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    conn.close()
    return jsonify({"ok": True, "reimpresiones": veces})


# ──────────────────────────────────────────
#  Consulta del día
# ──────────────────────────────────────────

@bp.route("/api/recaudo/dia", methods=["GET"])
@rol(*ROLES_RECAUDO)
def recaudo_dia():
    """Todos los buses con lo que trae el despacho del día, su liquidación vigente
    (si existe) y las anuladas."""
    fecha = _fecha_valida(request.args.get("fecha") or hoy_bogota())
    if not fecha:
        return jsonify({"error": "Fecha inválida (use AAAA-MM-DD)"}), 400

    conn = db()
    # ultima_reg_fin: lectura con la que cerró el torniquete el último día con
    # datos (respaldo de la lectura inicial cuando el despacho no la trae).
    buses = conn.execute(
        """SELECT b.id, b.numero, b.placa, b.modelo, b.grupo,
                  COALESCE(b.cuenta_pasajeros, 'registradora') AS cuenta_pasajeros,
                  m.pasajeros AS movilidad_pasajeros,
                  d.id AS despacho_id, d.estado, d.conductor_id, d.ruta_id,
                  d.viajes_realizados, d.registradora_inicio, d.registradora_fin,
                  (SELECT dp.registradora_fin
                     FROM despacho_diario dp
                    WHERE dp.bus_id = b.id
                      AND dp.fecha  < ?
                      AND dp.registradora_fin IS NOT NULL
                    ORDER BY dp.fecha DESC
                    LIMIT 1) AS ultima_reg_fin,
                  (SELECT dp.fecha
                     FROM despacho_diario dp
                    WHERE dp.bus_id = b.id
                      AND dp.fecha  < ?
                      AND dp.registradora_fin IS NOT NULL
                    ORDER BY dp.fecha DESC
                    LIMIT 1) AS ultima_reg_fecha
             FROM buses b
        LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = ?
        LEFT JOIN registros_movilidad m ON m.bus_id = b.id AND m.fecha = ?
         ORDER BY b.numero""",
        (fecha, fecha, fecha, fecha),
    ).fetchall()
    rutas = conn.execute(
        "SELECT id, nombre, grupo, color, activa FROM rutas ORDER BY grupo, nombre"
    ).fetchall()
    conductores = conn.execute(
        "SELECT id, nombre, cedula, activo FROM conductores ORDER BY nombre"
    ).fetchall()
    tarifas = _tarifas(conn)
    tipos = _tipos_gasto(conn)
    vigentes, anuladas = _liquidaciones_del_dia(conn, fecha)
    relevos = relevos_por_bus(conn, fecha)
    conn.close()

    salida = []
    for b in buses:
        b = dict(b)
        b["ultima_reg_fecha"] = _fecha_iso(b["ultima_reg_fecha"])
        b["relevos"] = relevos.get(b["id"], [])   # los anotó el despachador; el formulario los precarga
        b["recaudo"] = vigentes.get(b["id"])
        b["anulados"] = anuladas.get(b["id"], [])
        salida.append(b)

    editable, motivo = _puede_liquidar(fecha)
    return jsonify({
        "fecha":       fecha,
        "hoy":         hoy_bogota(),
        "editable":    editable,
        "motivo":      motivo,
        # Quien no es Administrador no cambia la registradora del despacho.
        "bloquea_registradora": not _es_admin(),
        "tarifas":     tarifas,
        "tipos_gasto": tipos,
        "rutas":       [dict(r) for r in rutas],
        "conductores": [dict(c) for c in conductores],
        "buses":       salida,
    })


# ──────────────────────────────────────────
#  Liquidar (solo crea: una liquidación guardada no se modifica)
# ──────────────────────────────────────────

def _armar_gastos(conn, gastos_in, n_conductores, primero=1):
    """Valida los gastos reportados: tipo activo, valor > 0, sin repetir tipo por conductor,
    salvo los que piden descripción (p. ej. "Otros"): esos pueden ir varias veces, cada uno
    con lo que fue (pedido del usuario 2026-11-03). `orden_conductor` es el número del
    conductor en el bus; en un relevo agregado los conductores van de `primero` en adelante."""
    if gastos_in in (None, ""):
        return []
    if not isinstance(gastos_in, list) or len(gastos_in) > 40:
        raise _Rechazo("Lista de gastos inválida")
    tipos = {t["id"]: t for t in _tipos_gasto(conn)}
    gastos, vistos = [], set()
    for g in gastos_in:
        g = g if isinstance(g, dict) else {}
        tipo_id = _entero(g.get("tipo_gasto_id"), "El tipo de gasto")
        if tipo_id not in tipos:
            raise _Rechazo("Hay un tipo de gasto que no existe o está desactivado")
        nombre = tipos[tipo_id]["nombre"]
        orden = _entero(g.get("orden_conductor"), "El conductor del gasto", requerido=False) or primero
        if not primero <= orden < primero + n_conductores:
            raise _Rechazo(f"El gasto {nombre} apunta a un conductor que no está en la liquidación")
        if (orden, tipo_id) in vistos and not tipos[tipo_id]["requiere_detalle"]:
            raise _Rechazo(f"El gasto {nombre} está repetido")
        vistos.add((orden, tipo_id))
        valor = _entero(g.get("valor"), f"El valor de {nombre}")
        if valor == 0:
            continue   # un gasto en cero es lo mismo que no reportarlo
        if valor > _GASTO_MAXIMO:
            raise _Rechazo(f"El valor de {nombre} es demasiado alto")
        observacion = _texto(g.get("observacion"), 200)
        if tipos[tipo_id]["requiere_detalle"] and not observacion:
            raise _Rechazo(f"Falta llenar: la descripción del gasto {nombre}")
        gastos.append({"orden_conductor": orden, "tipo_gasto_id": tipo_id, "tipo_nombre": nombre,
                       "valor": valor, "observacion": observacion})
    return gastos


def _armar_tramos(conn, conductores_in, reg_inicio, reg_fin, tarifa, gastos, pax_total=None,
                  primero=1, previos=()):
    """Valida los conductores y calcula el tramo de registradora y los totales de cada uno.
    Obligatorios por conductor: conductor, ruta, viajes (>= 1), pasajeros (>= 1) y recaudo.
    Los gastos son opcionales. Bus con sensores (`pax_total`, los que digitó el recaudador):
    sin registradora; con relevo, cada conductor lleva sus pasajeros y el último lo que falta.
    Relevo agregado a un bus ya liquidado: los conductores se numeran desde `primero` y no
    pueden repetir a los ya liquidados (`previos`)."""
    tramos, vistos, inicio, repartidos = [], set(previos), reg_inicio, 0
    for i, c in enumerate(conductores_in):
        n = primero + i
        ultimo = i == len(conductores_in) - 1
        c = c if isinstance(c, dict) else {}
        # Con un solo conductor en el bus los mensajes no necesitan número.
        cual = f" del conductor {n}" if primero - 1 + len(conductores_in) > 1 else ""

        conductor_id = _entero(c.get("conductor_id"), "El conductor" + (f" {n}" if cual else ""))
        if conductor_id in vistos:
            raise _Rechazo("Un mismo conductor no puede aparecer dos veces en la liquidación del bus"
                           + (" (ya está en lo liquidado)" if conductor_id in previos else ""))
        vistos.add(conductor_id)
        conductor = conn.execute(
            "SELECT nombre, cedula FROM conductores WHERE id = ?", (conductor_id,)
        ).fetchone()
        if not conductor:
            raise _Rechazo(f"El conductor {n} no existe")
        conductor = dict(conductor)

        ruta_id = _entero(c.get("ruta_id"), f"La ruta{cual}")
        if not conn.execute("SELECT id FROM rutas WHERE id = ?", (ruta_id,)).fetchone():
            raise _Rechazo(f"La ruta{cual} no existe")

        viajes = _entero(c.get("viajes"), f"Los viajes{cual}")
        if viajes < 1:
            raise _Rechazo(f"Los viajes{cual} deben ser al menos 1")

        if pax_total is not None:
            inicio = fin = None
            if ultimo:
                pasajeros = pax_total - repartidos
                if pasajeros < 1:
                    raise _Rechazo(f"Los pasajeros repartidos ({_miles(repartidos)}) no dejan pasajeros al "
                                   f"conductor {n}: el total del bus es {_miles(pax_total)}")
            else:
                pasajeros = _entero(c.get("pasajeros"), f"Los pasajeros del conductor {n}")
                if pasajeros < 1:
                    raise _Rechazo(f"Los pasajeros del conductor {n} deben ser al menos 1")
                repartidos += pasajeros
        else:
            # El último conductor termina en la lectura final del bus; los demás en su relevo.
            if ultimo:
                fin = reg_fin
            else:
                fin = _entero(c.get("registradora_fin"), f"La registradora al relevo del conductor {n}")
                if fin < inicio or fin > reg_fin:
                    raise _Rechazo(f"La registradora al relevo del conductor {n} debe estar "
                                   f"entre {inicio} y {reg_fin}")
            pasajeros = fin - inicio
            if pasajeros < 1:
                raise _Rechazo(f"No hay pasajeros{cual}: la registradora final debe ser mayor que la inicial")

        recaudado = _entero(c.get("recaudado"), f"El recaudo entregado{cual}")
        producido = pasajeros * tarifa
        total_gastos = sum(g["valor"] for g in gastos if g["orden_conductor"] == n)
        neto = aproximar_mil(producido - total_gastos)
        tramos.append({
            "orden": n, "conductor_id": conductor_id, "conductor_nombre": conductor["nombre"],
            "conductor_cedula": conductor.get("cedula"), "ruta_id": ruta_id, "viajes": viajes,
            "registradora_inicio": inicio, "registradora_fin": fin, "pasajeros": pasajeros,
            "producido": producido, "total_gastos": total_gastos, "neto": neto,
            "recaudado": recaudado, "diferencia": recaudado - por_entregar(neto),
            "observacion": _texto(c.get("observacion")),
        })
        inicio = fin
    return tramos


def _es_admin():
    return getattr(request, "jwt_user_rol", None) == "Administrador"


def _ultima_lectura(conn, bus_id, fecha):
    """(lectura, fecha) final de la registradora del último día anterior a `fecha` que la tiene."""
    f = conn.execute(
        """SELECT registradora_fin, fecha FROM despacho_diario
            WHERE bus_id = ? AND fecha < ? AND registradora_fin IS NOT NULL
            ORDER BY fecha DESC LIMIT 1""",
        (bus_id, fecha),
    ).fetchone()
    return (dict(f)["registradora_fin"], _fecha_iso(dict(f)["fecha"])) if f else (None, None)


def _lecturas_del_despacho(conn, bus_id, fecha, despacho, reg_inicio, reg_fin, conductores_in):
    """Quien no es Administrador no cambia la registradora: manda la que anotó el
    despachador (pedido del usuario 2026-10-29; como en un punto de venta, quien recibe
    la plata no anota los datos que dicen cuánta debe llegar). Solo llena la que falta.
    La inicial es la del despacho o, si no la trae, la final del último día con lectura.
    Si el despacho arranca en otra (salto: marcaron la registradora mientras el bus estaba
    en taller o descanso), se liquida desde la del despacho y el salto queda en el
    historial (pedido del usuario 2026-11-03; ver _salto_registradora).
    Devuelve las lecturas que digitó en recaudo."""
    corregir = "Si está mal, pide al despachador o al administrador que la corrija antes de liquidar."
    ultima, ultima_fecha = _ultima_lectura(conn, bus_id, fecha)
    desp_inicio = despacho["registradora_inicio"] if despacho else None
    desp_fin = despacho["registradora_fin"] if despacho else None

    digitadas = []
    inicio = desp_inicio if desp_inicio is not None else ultima
    if inicio is None:
        digitadas.append("inicial")
    elif reg_inicio != inicio:
        origen = "la del despacho" if desp_inicio is not None else f"la final del {ultima_fecha}"
        raise _Rechazo(f"La registradora inicial es {_miles(inicio)} ({origen}) y no se puede cambiar. "
                       f"Si acaba de cambiar, vuelve a cargar. {corregir}", 409)
    if desp_fin is None:
        digitadas.append("final")
    elif reg_fin != desp_fin:
        raise _Rechazo(f"La registradora final es {_miles(desp_fin)} (la del despacho) y no se puede "
                       f"cambiar. Si acaba de cambiar, vuelve a cargar. {corregir}", 409)

    anotados = relevos_por_bus(conn, fecha, bus_id).get(bus_id, [])
    if len(conductores_in) <= len(anotados):
        raise _Rechazo(f"El despachador anotó {len(anotados)} relevo(s) y no se pueden quitar. {corregir}", 409)
    for r in anotados:
        c = conductores_in[r["orden"] - 2]
        valor = c.get("registradora_fin") if isinstance(c, dict) else None
        try:
            valor = int(valor)
        except (TypeError, ValueError):
            valor = None
        if valor != r["registradora"]:
            raise _Rechazo(f"La registradora al relevo del conductor {r['orden'] - 1} es "
                           f"{_miles(r['registradora'])} (la anotó el despachador) y no se puede "
                           f"cambiar. {corregir}", 409)
    if len(conductores_in) - 1 > len(anotados):
        digitadas.append("relevo")
    return digitadas


def _salto_registradora(conn, bus_id, fecha, reg_inicio):
    """Si la lectura inicial no sigue el consecutivo (la final del último día con
    lectura), devuelve (última final, su fecha). Pasa cuando marcan la registradora con
    el bus en taller o descanso: esas marcas no se liquidan, pero quedan anotadas."""
    ultima, ultima_fecha = _ultima_lectura(conn, bus_id, fecha)
    if ultima is None or reg_inicio is None or ultima == reg_inicio:
        return None
    return ultima, ultima_fecha


def _pasajeros_movilidad(conn, bus_id, fecha):
    """Pasajeros que registró la analista en movilidad ese día (buses con sensores)."""
    f = conn.execute("SELECT pasajeros FROM registros_movilidad WHERE bus_id = ? AND fecha = ?",
                     (bus_id, fecha)).fetchone()
    return dict(f)["pasajeros"] if f else None


def _vigente(conn, bus_id, fecha):
    return conn.execute(
        "SELECT id FROM recaudos WHERE bus_id = ? AND fecha = ? AND anulado_at IS NULL",
        (bus_id, fecha),
    ).fetchone()


@bp.route("/api/recaudo", methods=["POST"])
@rol(*ROLES_RECAUDO)
def liquidar():
    data = request.get_json(silent=True) or {}
    fecha = _fecha_valida(data.get("fecha"))
    if not fecha:
        return jsonify({"error": "Fecha inválida (use AAAA-MM-DD)"}), 400
    permitido, motivo = _puede_liquidar(fecha)
    if not permitido:
        return jsonify({"error": motivo}), 403

    conn = db()
    try:
        bus_id = _entero(data.get("bus_id"), "El vehículo")
        bus = conn.execute("SELECT * FROM buses WHERE id = ?", (bus_id,)).fetchone()
        if not bus:
            raise _Rechazo("El vehículo no existe", 404)
        bus = dict(bus)

        # Bus con sensores: el recaudador digita los pasajeros que reporta el conductor (los
        # de los sensores llegan al día siguiente). La movilidad sigue siendo la de la
        # analista y de ahí sale la diferencia (pedido del usuario 2026-11-03).
        sensores = (bus.get("cuenta_pasajeros") or "registradora") == "sensores"
        pax_total = None
        if sensores:
            reg_inicio = reg_fin = None
            pax_total = _entero(data.get("pasajeros"), "Los pasajeros del día")
            if pax_total < 1:
                raise _Rechazo("Los pasajeros del día deben ser al menos 1")
        else:
            reg_inicio = _entero(data.get("registradora_inicio"), "La registradora inicial")
            reg_fin = _entero(data.get("registradora_fin"), "La registradora final")
            if reg_fin < reg_inicio:
                raise _Rechazo("Lectura inválida: la registradora final es menor que la inicial")
            if reg_fin == reg_inicio:
                raise _Rechazo("No hay pasajeros: la registradora final es igual a la inicial")

        if _vigente(conn, bus_id, fecha):
            raise _Rechazo(f"El bus {bus['numero']} ya está liquidado ese día. Una liquidación "
                           "guardada no se modifica: solo el administrador puede anularla. Si le "
                           "faltó un relevo, agrégalo desde la liquidación (+ Agregar relevo).", 409)

        despacho = conn.execute(
            """SELECT id, estado, registradora_inicio, registradora_fin
                 FROM despacho_diario WHERE bus_id = ? AND fecha = ?""",
            (bus_id, fecha),
        ).fetchone()
        despacho = dict(despacho) if despacho else None
        if despacho and despacho["estado"] in ("taller", "descanso"):
            raise _Rechazo(f"El despacho marca el bus {bus['numero']} en {despacho['estado']}. "
                           "Si trabajó, primero hay que corregirlo en el despacho.", 409)

        tarifa = _tarifas(conn).get(bus["grupo"])
        if not tarifa:
            raise _Rechazo("No hay tarifa configurada para este tipo de vehículo", 409)

        conductores_in = data.get("conductores")
        if not isinstance(conductores_in, list) or not 1 <= len(conductores_in) <= MAX_CONDUCTORES:
            raise _Rechazo(f"Debe haber entre 1 y {MAX_CONDUCTORES} conductores")
        es_admin = _es_admin()
        digitadas = [] if es_admin or sensores else _lecturas_del_despacho(
            conn, bus_id, fecha, despacho, reg_inicio, reg_fin, conductores_in)
        salto = None if sensores else _salto_registradora(conn, bus_id, fecha, reg_inicio)
        gastos = _armar_gastos(conn, data.get("gastos"), len(conductores_in))
        tramos = _armar_tramos(conn, conductores_in, reg_inicio, reg_fin, tarifa, gastos, pax_total)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    pasajeros = pax_total if sensores else reg_fin - reg_inicio
    producido = sum(t["producido"] for t in tramos)
    total_gastos = sum(g["valor"] for g in gastos)
    # Cada conductor ya viene aproximado; el del bus es solo lo que hay por entregar
    # (lo que la empresa le debe a un conductor no se descuenta de lo que entrega otro).
    neto = sum(por_entregar(t["neto"]) for t in tramos)
    recaudado = sum(t["recaudado"] for t in tramos)
    diferencia = sum(t["diferencia"] for t in tramos)
    debe = sum(debe_conductor(t["neto"]) for t in tramos)
    uid = getattr(request, "jwt_user_id", None)

    try:
        caja_fecha = dia_de_caja(conn, uid, bus_id, fecha)
        cur = conn.execute(
            """INSERT INTO recaudos
                   (empresa_id, fecha, bus_id, registradora_inicio, registradora_fin, pasajeros,
                    tarifa, producido, total_gastos, neto, recaudado, diferencia, observacion,
                    usuario_id, caja_fecha)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (EMPRESA_POR_DEFECTO, fecha, bus_id, reg_inicio, reg_fin, pasajeros, tarifa,
             producido, total_gastos, neto, recaudado, diferencia,
             _texto(data.get("observacion")), uid, caja_fecha),
        )
        recaudo_id = cur.lastrowid
        for t in tramos:
            conn.execute(
                """INSERT INTO recaudo_conductores
                       (recaudo_id, orden, conductor_id, ruta_id, viajes, registradora_inicio,
                        registradora_fin, pasajeros, producido, total_gastos, neto, recaudado,
                        diferencia, observacion)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (recaudo_id, t["orden"], t["conductor_id"], t["ruta_id"], t["viajes"],
                 t["registradora_inicio"], t["registradora_fin"], t["pasajeros"], t["producido"],
                 t["total_gastos"], t["neto"], t["recaudado"], t["diferencia"], t["observacion"]),
            )
        for g in gastos:
            conn.execute(
                """INSERT INTO recaudo_gastos
                       (recaudo_id, orden_conductor, tipo_gasto_id, tipo_nombre, valor, observacion)
                   VALUES (?,?,?,?,?,?)""",
                (recaudo_id, g["orden_conductor"], g["tipo_gasto_id"], g["tipo_nombre"],
                 g["valor"], g["observacion"]),
            )

        # Una sola fuente de verdad: la registradora del recaudo corrige el despacho.
        # Conductor, ruta y viajes del despacho solo se completan si estaban vacíos
        # (lo que anotó el despachador manda); sin despacho, se crea con el conductor 1.
        primero = tramos[0]
        viajes = [t["viajes"] for t in tramos if t["viajes"] is not None]
        viajes_total = sum(viajes) if viajes else None
        correccion = None
        if despacho:
            antes = (despacho["registradora_inicio"], despacho["registradora_fin"])
            # Quien no es admin solo llena lo que faltaba: eso va como "digitadas".
            if es_admin and not sensores and antes != (reg_inicio, reg_fin):
                correccion = antes
            conn.execute(
                """UPDATE despacho_diario
                      SET registradora_inicio = COALESCE(?, registradora_inicio),
                          registradora_fin    = COALESCE(?, registradora_fin),
                          conductor_id      = COALESCE(conductor_id, ?),
                          ruta_id           = COALESCE(ruta_id, ?),
                          viajes_realizados = COALESCE(viajes_realizados, ?),
                          updated_at        = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                (reg_inicio, reg_fin, primero["conductor_id"], primero["ruta_id"], viajes_total,
                 despacho["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO despacho_diario
                       (bus_id, fecha, estado, conductor_id, ruta_id, viajes_realizados,
                        registradora_inicio, registradora_fin, despachador_id, updated_at)
                   VALUES (?,?,'trabajando',?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (bus_id, fecha, primero["conductor_id"], primero["ruta_id"], viajes_total,
                 reg_inicio, reg_fin, uid),
            )
        if not sensores:   # con sensores la movilidad es la de la analista: no se reescribe
            sync_pax_movilidad(conn, fecha, {bus_id: pasajeros})

        nombres = ", ".join(t["conductor_nombre"] for t in tramos)
        detalle_gastos = ", ".join(f"{g['tipo_nombre']} {auditoria.pesos(g['valor'])}" for g in gastos)
        descripcion = (
            f"Liquidó el bus {bus['numero']} ({bus['placa'] or 's/placa'}) del {fecha} — {nombres}: "
            f"{_miles(pasajeros)} pasajeros × {auditoria.pesos(tarifa)} = producido "
            f"{auditoria.pesos(producido)}; gastos {auditoria.pesos(total_gastos)}"
            + (f" ({detalle_gastos})" if gastos else "")
            + f"; por entregar {auditoria.pesos(neto)}; recaudado {auditoria.pesos(recaudado)}; "
              f"{_resultado(diferencia)}."
            + (" La empresa le debe " + ", ".join(
                   f"{auditoria.pesos(debe_conductor(t['neto']))} a {t['conductor_nombre']}"
                   for t in tramos if debe_conductor(t["neto"])) + " (los gastos superan el producido)."
               if debe else "")
        )
        if len(tramos) > 1:
            descripcion += " Relevo: " + "; ".join(
                f"{t['orden']}) {t['conductor_nombre']}"
                + (f" {t['registradora_inicio']}→{t['registradora_fin']}" if not sensores else "") + ": "
                f"{_miles(t['pasajeros'])} pax, producido {auditoria.pesos(t['producido'])}, "
                f"gastos {auditoria.pesos(t['total_gastos'])}, entregó {auditoria.pesos(t['recaudado'])}, "
                f"{_resultado(t['diferencia'])}"
                for t in tramos) + "."
        if correccion:
            descripcion += (f" Corrigió la registradora del despacho: "
                            f"{correccion[0] if correccion[0] is not None else '—'}–"
                            f"{correccion[1] if correccion[1] is not None else '—'} → "
                            f"{reg_inicio}–{reg_fin}.")
        elif not despacho:
            descripcion += " El bus no tenía despacho: se creó con estos datos."
        if sensores:
            pax_mov = _pasajeros_movilidad(conn, bus_id, fecha)
            descripcion += (" Bus con sensores (sin registradora): pasajeros digitados en recaudo; "
                            + (f"la movilidad tiene {_miles(pax_mov)}." if pax_mov
                               else "la movilidad aún no los tiene."))
        if salto:
            marcas = reg_inicio - salto[0]
            descripcion += (f" Salto en la registradora: cerró en {_miles(salto[0])} el {salto[1]} y "
                            f"arrancó en {_miles(reg_inicio)} "
                            f"({_miles(abs(marcas))} marcas {'sin liquidar' if marcas > 0 else 'de menos'}).")
        if digitadas:
            descripcion += (" Registradora digitada en recaudo (el despacho no la traía): "
                            + ", ".join(digitadas) + ".")
        auditoria.registrar(
            conn, "recaudo", "liquidacion", recaudo_id, "crear", descripcion,
            {"fecha": fecha, "bus": bus["numero"], "registradora": [reg_inicio, reg_fin],
             "pasajeros": pasajeros, "tarifa": tarifa, "producido": producido,
             "gastos": [f"{g['tipo_nombre']} {auditoria.pesos(g['valor'])}" for g in gastos],
             "total_gastos": total_gastos, "neto": neto, "recaudado": recaudado,
             "diferencia": diferencia, "debe_al_conductor": debe or None,
             "despacho_antes": list(correccion) if correccion else None,
             "digitadas_en_recaudo": digitadas or None,
             "salto_registradora": ({"ultima_final": salto[0], "fecha": salto[1]}
                                    if salto else None),
             "conductores": [{k: t[k] for k in ("conductor_nombre", "registradora_inicio",
                                                "registradora_fin", "pasajeros", "producido",
                                                "total_gastos", "recaudado", "diferencia")}
                             for t in tramos]},
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        # Dos personas liquidando el mismo bus a la vez: la segunda choca con el índice único.
        ya = _vigente(conn, bus_id, fecha)
        conn.close()
        if ya:
            return jsonify({"error": f"El bus {bus['numero']} ya fue liquidado ese día por otra persona."}), 409
        print(f"[recaudo.liquidar] {e}")
        return jsonify({"error": "No se pudo guardar la liquidación"}), 500

    vigentes, _ = _liquidaciones_del_dia(conn, fecha, bus_id)
    conn.close()
    return jsonify({"ok": True, "recaudo": vigentes.get(bus_id)}), 201


# ──────────────────────────────────────────
#  Relevo agregado a un bus ya liquidado
# ──────────────────────────────────────────

def _lecturas_relevo_agregado(conn, bus_id, fecha, despacho, ya, reg_inicio, reg_fin, conductores_in):
    """Quien no es Administrador tampoco cambia aquí la registradora del despacho (ver
    _lecturas_del_despacho): la final del bus es la del despacho si el despachador ya la
    anotó más allá de lo liquidado, y las lecturas de los relevos anotados no se cambian
    ni se quitan. Lo que el despacho no traía se digita y va al historial.
    Devuelve las lecturas que digitó en recaudo."""
    corregir = "Si está mal, pide al despachador o al administrador que la corrija antes de liquidar."
    digitadas = []
    desp_fin = despacho["registradora_fin"] if despacho else None
    if desp_fin is not None and desp_fin != reg_inicio:
        if reg_fin != desp_fin:
            raise _Rechazo(f"La registradora final del bus es {_miles(desp_fin)} (la del despacho) y no "
                           f"se puede cambiar. {corregir}", 409)
    else:
        digitadas.append("final")
    anotados = [r for r in relevos_por_bus(conn, fecha, bus_id).get(bus_id, []) if r["orden"] > ya]
    for r in anotados:
        if r["orden"] == ya + 1:
            # Recibe donde terminó lo liquidado: el despacho tiene que decir lo mismo.
            if r["registradora"] != reg_inicio:
                raise _Rechazo(f"El despachador anotó que el conductor {r['orden']} recibe el bus en "
                               f"{_miles(r['registradora'])}, pero lo liquidado termina en "
                               f"{_miles(reg_inicio)}. {corregir}", 409)
            continue
        k = r["orden"] - ya - 2   # el conductor nuevo que entrega el bus en esa lectura
        if k >= len(conductores_in) - 1:
            raise _Rechazo(f"El despachador anotó el relevo del conductor {r['orden']} y no se puede "
                           f"quitar. {corregir}", 409)
        c = conductores_in[k] if isinstance(conductores_in[k], dict) else {}
        try:
            valor = int(c.get("registradora_fin"))
        except (TypeError, ValueError):
            valor = None
        if valor != r["registradora"]:
            raise _Rechazo(f"La registradora al relevo del conductor {r['orden'] - 1} es "
                           f"{_miles(r['registradora'])} (la anotó el despachador) y no se puede "
                           f"cambiar. {corregir}", 409)
    if len(conductores_in) - 1 > len([r for r in anotados if r["orden"] > ya + 1]):
        digitadas.append("relevo")
    return digitadas


@bp.route("/api/recaudo/relevo", methods=["POST"])
@rol(*ROLES_RECAUDO)
def agregar_relevo():
    """Relevo que le faltó a un bus ya liquidado (pedido del usuario 2026-11-07): el bus se
    liquidó con un conductor y después aparecen los que lo recibieron. Lo ya liquidado no se
    toca (puede estar en una caja cerrada); los conductores que siguen se liquidan como otra
    PARTE de la liquidación del día (`recaudos.parte` = número de su primer conductor),
    con su tirilla, y su plata entra a la caja del día en que se recibe. El relevo lo anota
    el despachador en el despacho o, si no, el recaudador aquí; el despacho se completa.
    Body: {fecha, bus_id, registradora_fin (la final del bus; con sensores: pasajeros, los
    de los conductores nuevos), conductores: [los nuevos], gastos: [{orden_conductor (su
    número en el bus), tipo_gasto_id, valor, observacion}], observacion?}."""
    data = request.get_json(silent=True) or {}
    fecha = _fecha_valida(data.get("fecha"))
    if not fecha:
        return jsonify({"error": "Fecha inválida (use AAAA-MM-DD)"}), 400
    permitido, motivo = _puede_liquidar(fecha)
    if not permitido:
        return jsonify({"error": motivo}), 403

    conn = db()
    uid = getattr(request, "jwt_user_id", None)
    try:
        bus_id = _entero(data.get("bus_id"), "El vehículo")
        bus = conn.execute("SELECT * FROM buses WHERE id = ?", (bus_id,)).fetchone()
        if not bus:
            raise _Rechazo("El vehículo no existe", 404)
        bus = dict(bus)
        partes = sorted(_cargar(conn, "r.bus_id = ? AND r.fecha = ? AND r.anulado_at IS NULL", [bus_id, fecha]),
                        key=lambda p: (p.get("parte") or 1, p["id"]))
        if not partes:
            raise _Rechazo(f"El bus {bus['numero']} no está liquidado ese día: liquídalo con todos sus "
                           "conductores.", 409)
        ya = sum(len(p["conductores"]) for p in partes)
        if ya >= MAX_CONDUCTORES:
            raise _Rechazo(f"El bus {bus['numero']} ya tiene {MAX_CONDUCTORES} conductores liquidados ese día.", 409)
        conductores_in = data.get("conductores")
        if not isinstance(conductores_in, list) or not 1 <= len(conductores_in) <= MAX_CONDUCTORES - ya:
            raise _Rechazo(f"Al bus le caben {MAX_CONDUCTORES - ya} conductor(es) más "
                           f"(ya tiene {ya} liquidado(s)).")
        primero, ultima = ya + 1, partes[-1]
        tarifa = int(partes[0]["tarifa"])   # la del día, la misma de lo ya liquidado
        sensores = partes[0]["registradora_inicio"] is None

        pax_total = reg_inicio = reg_fin = None
        if sensores:
            pax_total = _entero(data.get("pasajeros"), "Los pasajeros de los conductores del relevo")
            if pax_total < 1:
                raise _Rechazo("Los pasajeros de los conductores del relevo deben ser al menos 1")
        else:
            reg_inicio = ultima["registradora_fin"]   # el relevo recibe donde terminó lo liquidado
            reg_fin = _entero(data.get("registradora_fin"), "La registradora final del bus")
            if reg_fin <= reg_inicio:
                raise _Rechazo(f"La registradora final del bus debe ser mayor que {_miles(reg_inicio)}, "
                               f"donde terminó el conductor {ya} (ya liquidado).")

        despacho = conn.execute(
            """SELECT id, estado, registradora_inicio, registradora_fin, viajes_realizados
                 FROM despacho_diario WHERE bus_id = ? AND fecha = ?""",
            (bus_id, fecha),
        ).fetchone()
        despacho = dict(despacho) if despacho else None
        digitadas = [] if _es_admin() or sensores else _lecturas_relevo_agregado(
            conn, bus_id, fecha, despacho, ya, reg_inicio, reg_fin, conductores_in)
        gastos = _armar_gastos(conn, data.get("gastos"), len(conductores_in), primero=primero)
        previos = [c["conductor_id"] for p in partes for c in p["conductores"]]
        tramos = _armar_tramos(conn, conductores_in, reg_inicio, reg_fin, tarifa, gastos, pax_total,
                               primero=primero, previos=previos)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    pasajeros = pax_total if sensores else reg_fin - reg_inicio
    producido = sum(t["producido"] for t in tramos)
    total_gastos = sum(g["valor"] for g in gastos)
    neto = sum(por_entregar(t["neto"]) for t in tramos)
    recaudado = sum(t["recaudado"] for t in tramos)
    diferencia = sum(t["diferencia"] for t in tramos)
    debe = sum(debe_conductor(t["neto"]) for t in tramos)

    try:
        caja_fecha = dia_de_caja(conn, uid, bus_id, fecha, parte=primero)
        cur = conn.execute(
            """INSERT INTO recaudos
                   (empresa_id, fecha, bus_id, registradora_inicio, registradora_fin, pasajeros,
                    tarifa, producido, total_gastos, neto, recaudado, diferencia, observacion,
                    usuario_id, caja_fecha, parte)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (EMPRESA_POR_DEFECTO, fecha, bus_id, reg_inicio, reg_fin, pasajeros, tarifa,
             producido, total_gastos, neto, recaudado, diferencia,
             _texto(data.get("observacion")), uid, caja_fecha, primero),
        )
        recaudo_id = cur.lastrowid
        for t in tramos:
            conn.execute(
                """INSERT INTO recaudo_conductores
                       (recaudo_id, orden, conductor_id, ruta_id, viajes, registradora_inicio,
                        registradora_fin, pasajeros, producido, total_gastos, neto, recaudado,
                        diferencia, observacion)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (recaudo_id, t["orden"], t["conductor_id"], t["ruta_id"], t["viajes"],
                 t["registradora_inicio"], t["registradora_fin"], t["pasajeros"], t["producido"],
                 t["total_gastos"], t["neto"], t["recaudado"], t["diferencia"], t["observacion"]),
            )
        for g in gastos:
            conn.execute(
                """INSERT INTO recaudo_gastos
                       (recaudo_id, orden_conductor, tipo_gasto_id, tipo_nombre, valor, observacion)
                   VALUES (?,?,?,?,?,?)""",
                (recaudo_id, g["orden_conductor"], g["tipo_gasto_id"], g["tipo_nombre"],
                 g["valor"], g["observacion"]),
            )

        # El despacho queda con todo el día: la final del bus y, si el despachador no los
        # anotó, los relevos nuevos (con sus viajes sumados al total del bus).
        if despacho:
            anotados = {r["orden"] for r in relevos_por_bus(conn, fecha, bus_id).get(bus_id, [])}
            nuevos = [t for t in tramos if t["orden"] not in anotados and not sensores]
            for t in nuevos:
                conn.execute(
                    """INSERT INTO despacho_relevos
                           (fecha, bus_id, orden, conductor_id, ruta_id, registradora, viajes, usuario_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (fecha, bus_id, t["orden"], t["conductor_id"], t["ruta_id"],
                     t["registradora_inicio"], t["viajes"], uid),
                )
            viajes_nuevos = sum(t["viajes"] for t in nuevos)
            conn.execute(
                """UPDATE despacho_diario
                      SET registradora_fin  = COALESCE(?, registradora_fin),
                          viajes_realizados = CASE WHEN viajes_realizados IS NULL THEN viajes_realizados
                                                   ELSE viajes_realizados + ? END,
                          updated_at        = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                (reg_fin, viajes_nuevos, despacho["id"]),
            )
        if not sensores:
            sync_pax_movilidad(conn, fecha, {bus_id: reg_fin - partes[0]["registradora_inicio"]})

        detalle = "; ".join(
            f"{t['orden']}) {t['conductor_nombre']}"
            + (f" {t['registradora_inicio']}→{t['registradora_fin']}" if not sensores else "") + ": "
            f"{_miles(t['pasajeros'])} pax, producido {auditoria.pesos(t['producido'])}, "
            f"gastos {auditoria.pesos(t['total_gastos'])}, entregó {auditoria.pesos(t['recaudado'])}, "
            f"{_resultado(t['diferencia'])}"
            for t in tramos)
        descripcion = (
            f"Agregó el relevo al bus {bus['numero']} ({bus['placa'] or 's/placa'}) del {fecha}, que ya "
            f"estaba liquidado con {ya} conductor(es) (liquidación N° {str(partes[0]['id']).zfill(6)}). "
            f"Conductores {detalle}. Total del relevo: {_miles(pasajeros)} pasajeros × "
            f"{auditoria.pesos(tarifa)} = producido {auditoria.pesos(producido)}; gastos "
            f"{auditoria.pesos(total_gastos)}; por entregar {auditoria.pesos(neto)}; recaudado "
            f"{auditoria.pesos(recaudado)}; {_resultado(diferencia)}. Entra a la caja del {caja_fecha}."
            + (" La empresa le debe " + ", ".join(
                   f"{auditoria.pesos(debe_conductor(t['neto']))} a {t['conductor_nombre']}"
                   for t in tramos if debe_conductor(t["neto"])) + " (los gastos superan el producido)."
               if debe else "")
            + (" Registradora digitada en recaudo (el despacho no la traía): " + ", ".join(digitadas) + "."
               if digitadas else "")
        )
        auditoria.registrar(
            conn, "recaudo", "liquidacion", recaudo_id, "crear", descripcion,
            {"fecha": fecha, "bus": bus["numero"], "relevo_agregado": True, "parte": primero,
             "liquidacion_original": partes[0]["id"], "registradora": [reg_inicio, reg_fin],
             "pasajeros": pasajeros, "tarifa": tarifa, "producido": producido,
             "gastos": [f"{g['tipo_nombre']} {auditoria.pesos(g['valor'])}" for g in gastos],
             "total_gastos": total_gastos, "neto": neto, "recaudado": recaudado,
             "diferencia": diferencia, "caja_fecha": caja_fecha,
             "digitadas_en_recaudo": digitadas or None,
             "conductores": [{k: t[k] for k in ("conductor_nombre", "registradora_inicio",
                                                "registradora_fin", "pasajeros", "producido",
                                                "total_gastos", "recaudado", "diferencia")}
                             for t in tramos]},
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        # Dos personas agregando el mismo relevo a la vez: la segunda choca con el índice único.
        ya_esta = conn.execute(
            "SELECT 1 FROM recaudos WHERE bus_id = ? AND fecha = ? AND parte = ? AND anulado_at IS NULL",
            (bus_id, fecha, primero),
        ).fetchone()
        conn.close()
        if ya_esta:
            return jsonify({"error": f"El relevo del bus {bus['numero']} ya fue liquidado por otra persona."}), 409
        print(f"[recaudo.agregar_relevo] {e}")
        return jsonify({"error": "No se pudo guardar el relevo"}), 500

    vigentes, _ = _liquidaciones_del_dia(conn, fecha, bus_id)
    conn.close()
    combinada = vigentes.get(bus_id) or {}
    nueva = next((p for p in combinada.get("partes", []) if p["id"] == recaudo_id), None)
    return jsonify({"ok": True, "recaudo": combinada, "parte": nueva}), 201


@bp.route("/api/recaudo/<int:recaudo_id>/anular", methods=["POST"])
@rol(*ADMIN)
def anular(recaudo_id):
    """Anula una liquidación (no la borra): queda en el historial con quién y por
    qué, y el bus vuelve a quedar por liquidar. El despacho no se modifica. Si el bus tiene
    un relevo agregado (otra parte), se anula primero la última parte: el relevo arranca
    donde terminó la anterior."""
    data = request.get_json(silent=True) or {}
    motivo = _texto(data.get("motivo"), 500)
    if not motivo or len(motivo) < 5:
        return jsonify({"error": "Escribe el motivo de la anulación (mínimo 5 caracteres)"}), 400

    conn = db()
    filas = _cargar(conn, "r.id = ?", [recaudo_id])
    if not filas:
        conn.close()
        return jsonify({"error": "Liquidación no encontrada"}), 404
    r = filas[0]
    if r["anulado_at"]:
        conn.close()
        return jsonify({"error": "Esta liquidación ya estaba anulada"}), 409
    if r.get("cierre_id"):
        # Una caja cerrada bloquea sus liquidaciones: primero hay que reabrirla.
        conn.close()
        return jsonify({"error": f"Esta liquidación está en la caja cerrada N° {r['cierre_id']}. "
                                 "Primero reabre esa caja en Recaudo › Cierre de caja."}), 409
    despues = conn.execute(
        """SELECT id FROM recaudos WHERE bus_id = ? AND fecha = ? AND parte > ? AND anulado_at IS NULL
         ORDER BY parte DESC LIMIT 1""",
        (r["bus_id"], r["fecha"], r.get("parte") or 1),
    ).fetchone()
    if despues:
        conn.close()
        return jsonify({"error": f"Este bus tiene un relevo agregado después (liquidación N° "
                                 f"{str(dict(despues)['id']).zfill(6)}): primero anula ese relevo."}), 409

    relevo = (r.get("parte") or 1) > 1
    conn.execute(
        "UPDATE recaudos SET anulado_at = ?, anulado_por = ?, motivo_anulacion = ? WHERE id = ?",
        (_ahora(), getattr(request, "jwt_user_id", None), motivo, recaudo_id),
    )
    auditoria.registrar(
        conn, "recaudo", "liquidacion", recaudo_id, "anular",
        (f"Anuló {'el relevo agregado (conductores desde el ' + str(r['parte']) + ') de ' if relevo else ''}"
         f"la liquidación del bus {r['bus_numero']} ({r['bus_placa'] or 's/placa'}) del "
         f"{r['fecha']}: producido {auditoria.pesos(r['producido'])}, gastos "
         f"{auditoria.pesos(r['total_gastos'])}, por entregar {auditoria.pesos(r['neto'])}, "
         f"recaudado {auditoria.pesos(r['recaudado'])}, {_resultado(r['diferencia'])}. "
         f"Motivo: {motivo}"),
        {"fecha": r["fecha"], "bus": r["bus_numero"], "producido": r["producido"],
         "total_gastos": r["total_gastos"], "neto": r["neto"], "recaudado": r["recaudado"],
         "diferencia": r["diferencia"], "motivo": motivo},
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Vista del propietario (Mis Buses): liquidación real de SUS buses
# ──────────────────────────────────────────

_MAX_DIAS_PROPIETARIO = 92


def _filtro_propietario(conn):
    """(filtro_sql, params) para limitar a los buses de la cuenta, o None si es un
    Propietario sin buses. Se decide por el rol del TOKEN (no por `activo` de la
    cuenta), así una sesión vieja nunca ve la flota completa."""
    if getattr(request, "jwt_user_rol", None) != "Propietario":
        return "", []
    ids = [dict(f)["bus_id"] for f in conn.execute(
        "SELECT bus_id FROM usuario_buses WHERE usuario_id = ?",
        (getattr(request, "jwt_user_id", None),),
    ).fetchall()]
    if not ids:
        return None
    return f" AND r.bus_id IN ({','.join('?' * len(ids))})", ids


def _rango_propietario(max_dias=None):
    """(desde, hasta) validados; por defecto el mes en curso (hora Bogotá)."""
    max_dias = max_dias or _MAX_DIAS_PROPIETARIO
    hoy = hoy_bogota()
    desde = request.args.get("desde") or hoy[:8] + "01"
    hasta = request.args.get("hasta") or hoy
    if not _fecha_valida(desde) or not _fecha_valida(hasta) or desde > hasta:
        raise _Rechazo("Rango de fechas inválido (use AAAA-MM-DD)")
    if (date.fromisoformat(hasta) - date.fromisoformat(desde)).days > max_dias:
        raise _Rechazo(f"El rango no puede pasar de {max_dias} días")
    return desde, hasta


@bp.route("/api/recaudo/propietario", methods=["GET"])
@rol("Propietario", "Administrador")
def recaudo_propietario():
    """Liquidaciones vigentes (con gastos y conductores) de los buses del
    propietario en un rango: ?desde=&hasta=[&bus_id=]. Para el detalle de cada bus."""
    try:
        desde, hasta = _rango_propietario()
        bus_id = _entero(request.args.get("bus_id"), "El bus", requerido=False)
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    conn = db()
    filtro = _filtro_propietario(conn)
    if filtro is None:
        conn.close()
        return jsonify({"desde": desde, "hasta": hasta, "liquidaciones": []})
    where, params = filtro
    if bus_id is not None:
        where += " AND r.bus_id = ?"
        params = params + [bus_id]
    por_dia = {}
    for e in _cargar(conn, f"r.fecha BETWEEN ? AND ? AND r.anulado_at IS NULL{where}", [desde, hasta] + params):
        por_dia.setdefault((e["bus_id"], e["fecha"]), []).append(e)
    conn.close()
    # Con relevo agregado el bus tiene varias partes ese día: se muestran como una sola.
    liquidaciones = [_combinar(p) for p in por_dia.values()]   # mismo orden: bus y luego id
    return jsonify({"desde": desde, "hasta": hasta, "liquidaciones": liquidaciones})


@bp.route("/api/recaudo/propietario/resumen", methods=["GET"])
@rol("Propietario", "Administrador")
def recaudo_propietario_resumen():
    """Totales por bus en un rango (por defecto el mes en curso): recaudo y gastos
    para las tarjetas de "Mis Buses"."""
    try:
        desde, hasta = _rango_propietario()
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    conn = db()
    filtro = _filtro_propietario(conn)
    if filtro is None:
        conn.close()
        return jsonify({"desde": desde, "hasta": hasta, "buses": []})
    where, params = filtro
    filas = conn.execute(
        f"""SELECT r.bus_id, COUNT(DISTINCT r.fecha) AS dias,
                   SUM(r.producido) AS producido, SUM(r.total_gastos) AS total_gastos,
                   SUM(r.recaudado) AS recaudado, SUM(r.diferencia) AS diferencia
              FROM recaudos r
             WHERE r.fecha BETWEEN ? AND ? AND r.anulado_at IS NULL{where}
          GROUP BY r.bus_id""",
        [desde, hasta] + params,
    ).fetchall()
    conn.close()
    # SUM de INTEGER en Postgres llega como Decimal: a int para que el JSON sea numérico.
    buses = [{k: (int(v) if k != "bus_id" and v is not None else v) for k, v in dict(f).items()}
             for f in filas]
    return jsonify({"desde": desde, "hasta": hasta, "buses": buses})


# Los reportes de la app piden hasta un año; por eso esta consulta es compacta.
_MAX_DIAS_DIARIO = 366


@bp.route("/api/recaudo/propietario/diario", methods=["GET"])
@rol("Propietario", "Administrador")
def recaudo_propietario_diario():
    """Recaudo compacto por bus, día y conductor (una fila por conductor de cada
    liquidación vigente; con relevo, varias por día) de los buses del propietario:
    ?desde=&hasta= (hasta 366 días). Para Mis Buses y los reportes de la app."""
    try:
        desde, hasta = _rango_propietario(_MAX_DIAS_DIARIO)
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    conn = db()
    filtro = _filtro_propietario(conn)
    if filtro is None:
        conn.close()
        return jsonify({"desde": desde, "hasta": hasta, "filas": []})
    where, params = filtro
    filas = conn.execute(
        f"""SELECT r.id AS recaudo_id, r.bus_id, r.fecha, rc.orden,
                   c.nombre AS conductor_nombre, ru.nombre AS ruta_nombre, rc.viajes,
                   rc.pasajeros, rc.producido, rc.total_gastos, rc.recaudado, rc.diferencia
              FROM recaudos r
              JOIN recaudo_conductores rc ON rc.recaudo_id = r.id
         LEFT JOIN conductores c ON c.id = rc.conductor_id
         LEFT JOIN rutas ru ON ru.id = rc.ruta_id
             WHERE r.fecha BETWEEN ? AND ? AND r.anulado_at IS NULL{where}
          ORDER BY r.fecha, r.bus_id, rc.orden""",
        [desde, hasta] + params,
    ).fetchall()
    conn.close()
    salida = []
    for f in filas:
        f = dict(f)
        f["fecha"] = _fecha_iso(f["fecha"])
        salida.append(f)
    return jsonify({"desde": desde, "hasta": hasta, "filas": salida})


# ──────────────────────────────────────────
#  Tarifas por grupo de vehículo
# ──────────────────────────────────────────

@bp.route("/api/recaudo/tarifas", methods=["GET"])
@rol(*ROLES_RECAUDO)
def ver_tarifas():
    conn = db()
    tarifas = _tarifas(conn)
    conn.close()
    return jsonify(tarifas)


@bp.route("/api/recaudo/tarifas", methods=["PUT"])
@rol(*ADMIN)
def editar_tarifas():
    """Body: {"A": 3050, "B": 3200} (se puede mandar solo uno). Solo Administrador."""
    data = request.get_json(silent=True) or {}
    cambios = {}
    try:
        for grupo, nombre in (("A", "La tarifa de buses"), ("B", "La tarifa de micros")):
            if grupo in data:
                valor = _entero(data[grupo], nombre)
                if not 0 < valor <= _TARIFA_MAXIMA:
                    raise _Rechazo(f"{nombre} debe estar entre $1 y {auditoria.pesos(_TARIFA_MAXIMA)}")
                cambios[grupo] = valor
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    if not cambios:
        return jsonify({"error": "No se envió ninguna tarifa"}), 400

    uid = getattr(request, "jwt_user_id", None)
    conn = db()
    actuales = _tarifas(conn)
    for grupo, valor in cambios.items():
        if actuales.get(grupo) == valor:
            continue
        conn.execute(
            """INSERT INTO recaudo_tarifas (empresa_id, grupo, valor, usuario_id, updated_at)
               VALUES (?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(empresa_id, grupo) DO UPDATE SET
                   valor = excluded.valor, usuario_id = excluded.usuario_id,
                   updated_at = CURRENT_TIMESTAMP""",
            (EMPRESA_POR_DEFECTO, grupo, valor, uid),
        )
        auditoria.registrar(
            conn, "recaudo", "tarifa", grupo, "editar",
            f"Cambió la tarifa de {_GRUPO_NOMBRE[grupo]}: "
            f"{auditoria.pesos(actuales.get(grupo))} → {auditoria.pesos(valor)}",
            {"valor": [actuales.get(grupo), valor]},
        )
    conn.commit()
    tarifas = _tarifas(conn)
    conn.close()
    return jsonify({"ok": True, "tarifas": tarifas})


# ──────────────────────────────────────────
#  Tipos de gasto (ACPM, Taller, …): solo el Administrador los crea o cambia
# ──────────────────────────────────────────

def _nombre_tipo(valor):
    nombre = " ".join(str(valor or "").split())[:60]
    if len(nombre) < 2:
        raise _Rechazo("Escribe el nombre del gasto")
    return nombre


def _si_no(v):
    return 1 if v in (1, True, "1", "true") else 0


_ETQ_TIPO = {"nombre": "Nombre", "activo": "Activo", "orden": "Orden",
             "fijo": "Siempre a la vista", "requiere_detalle": "Pide descripción"}


def _nombre_repetido(conn, nombre, excluir_id=0):
    for t in _tipos_gasto(conn, solo_activos=False):
        if t["id"] != excluir_id and t["nombre"].lower() == nombre.lower():
            return True
    return False


@bp.route("/api/recaudo/tipos-gasto", methods=["GET"])
@rol(*ROLES_RECAUDO)
def listar_tipos_gasto():
    conn = db()
    tipos = _tipos_gasto(conn, solo_activos=False)
    conn.close()
    return jsonify(tipos)


@bp.route("/api/recaudo/tipos-gasto", methods=["POST"])
@rol(*ADMIN)
def crear_tipo_gasto():
    data = request.get_json(silent=True) or {}
    conn = db()
    try:
        nombre = _nombre_tipo(data.get("nombre")).upper()   # los nuevos, en mayúscula
        if _nombre_repetido(conn, nombre):
            raise _Rechazo(f"Ya existe un gasto llamado «{nombre}»", 409)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    orden = max([t["orden"] for t in _tipos_gasto(conn, solo_activos=False)] or [0]) + 1
    fijo, detalle = _si_no(data.get("fijo")), _si_no(data.get("requiere_detalle"))
    cur = conn.execute(
        "INSERT INTO recaudo_tipos_gasto (empresa_id, nombre, orden, fijo, requiere_detalle) VALUES (?,?,?,?,?)",
        (EMPRESA_POR_DEFECTO, nombre, orden, fijo, detalle),
    )
    tipo_id = cur.lastrowid
    auditoria.registrar(conn, "recaudo", "tipo_gasto", tipo_id, "crear",
                        f"Creó el tipo de gasto «{nombre}»",
                        {"nombre": nombre, "fijo": fijo, "requiere_detalle": detalle})
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": tipo_id}), 201


@bp.route("/api/recaudo/tipos-gasto/<int:tipo_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_tipo_gasto(tipo_id):
    """Body: {nombre?, activo?, orden?, fijo?, requiere_detalle?}. No se borran: se desactivan."""
    data = request.get_json(silent=True) or {}
    conn = db()
    actual = next((t for t in _tipos_gasto(conn, solo_activos=False) if t["id"] == tipo_id), None)
    if not actual:
        conn.close()
        return jsonify({"error": "Tipo de gasto no encontrado"}), 404
    nuevo = dict(actual)
    try:
        if "nombre" in data:
            nuevo["nombre"] = _nombre_tipo(data["nombre"])
            if _nombre_repetido(conn, nuevo["nombre"], excluir_id=tipo_id):
                raise _Rechazo(f"Ya existe un gasto llamado «{nuevo['nombre']}»", 409)
        for campo in ("activo", "fijo", "requiere_detalle"):
            if campo in data:
                nuevo[campo] = _si_no(data[campo])
        if "orden" in data:
            nuevo["orden"] = _entero(data["orden"], "El orden")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    cambios = auditoria.diferencias(actual, nuevo, tuple(_ETQ_TIPO))
    if cambios:
        conn.execute(
            """UPDATE recaudo_tipos_gasto
                  SET nombre = ?, activo = ?, orden = ?, fijo = ?, requiere_detalle = ?
                WHERE id = ?""",
            (nuevo["nombre"], nuevo["activo"], nuevo["orden"], nuevo["fijo"],
             nuevo["requiere_detalle"], tipo_id),
        )
        if set(cambios) == {"activo"}:
            accion = "activar" if nuevo["activo"] else "desactivar"
            texto = f"{'Activó' if nuevo['activo'] else 'Desactivó'} el tipo de gasto «{actual['nombre']}»"
        else:
            accion = "editar"
            texto = (f"Editó el tipo de gasto «{actual['nombre']}»: "
                     f"{auditoria.describir(cambios, _ETQ_TIPO)}")
        auditoria.registrar(conn, "recaudo", "tipo_gasto", tipo_id, accion, texto, cambios)
        conn.commit()
    conn.close()
    return jsonify({"ok": True})
