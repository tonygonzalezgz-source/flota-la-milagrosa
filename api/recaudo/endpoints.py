"""Recaudo diario: consulta del día, liquidación por bus, anulación, tarifas,
tipos de gasto y la vista del propietario.

Reglas:
- El servidor recalcula todo; no confía en el cliente:
    producido  = pasajeros × tarifa
    neto       = producido − gastos      (lo que el conductor debe entregar)
    diferencia = recaudado − neto        (negativa = faltante, positiva = sobrante)
- Pasajeros por conductor = su tramo de registradora (el conductor 1 va de la
  lectura inicial del bus a la del relevo, el último termina en la final).
- La registradora del recaudo corrige también el despacho del mismo (bus, fecha)
  y, con él, los pasajeros de movilidad diaria: una sola fuente de verdad.
- Una liquidación guardada NO se edita ni se borra. Solo el Administrador puede
  anularla (con motivo); queda en el historial y el bus vuelve a quedar por liquidar.
- Recaudador liquida hoy y ayer (hora Bogotá). Administrador: cualquier día ya ocurrido.
- El propietario ve las liquidaciones vigentes de SUS buses (filtro por el token).
- Todo cambio queda en el historial de modificaciones (auditoría).
"""
import re
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

import auditoria

from . import bp
from .comun import (EMPRESA_POR_DEFECTO, MAX_CONDUCTORES, ROLES_RECAUDO, db, es_pg, hoy_bogota,
                    rol, sync_pax_movilidad)

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
    return (str(valor or "").strip()[:largo]) or None


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


def _fila(r):
    d = dict(r)
    d["fecha"] = _fecha_iso(d.get("fecha"))
    for k in ("created_at", "anulado_at"):
        if k in d:
            d[k] = _hora_utc(d[k])
    return d


def _miles(n):
    return f"{n:,}".replace(",", ".")


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
        f"""SELECT id, nombre, orden, activo FROM recaudo_tipos_gasto
             WHERE empresa_id = ?{filtro} ORDER BY orden, nombre""",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()
    return [dict(f) for f in filas]


def _puede_liquidar(fecha):
    """(True, None) o (False, motivo) según el rol y el día."""
    hoy = hoy_bogota()
    if fecha > hoy:
        return False, "No se puede liquidar un día que aún no ha llegado."
    if getattr(request, "jwt_user_rol", None) == "Administrador":
        return True, None
    ayer = (date.fromisoformat(hoy) - timedelta(days=1)).isoformat()
    if fecha < ayer:
        return False, ("Este día ya está cerrado. Solo el administrador puede "
                       "liquidar días anteriores.")
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


def _liquidaciones_del_dia(conn, fecha, bus_id=None):
    """(vigentes, anuladas): vigentes = bus_id → liquidación; anuladas = bus_id → [liquidaciones]."""
    where, params = "r.fecha = ?", [fecha]
    if bus_id is not None:
        where, params = "r.fecha = ? AND r.bus_id = ?", [fecha, bus_id]
    vigentes, anuladas = {}, {}
    for e in _cargar(conn, where, params):
        if e["anulado_at"]:
            anuladas.setdefault(e["bus_id"], []).append(e)
        else:
            vigentes[e["bus_id"]] = e
    return vigentes, anuladas


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
                  d.id AS despacho_id, d.estado, d.conductor_id, d.ruta_id,
                  d.viajes_realizados, d.registradora_inicio, d.registradora_fin,
                  (SELECT dp.registradora_fin
                     FROM despacho_diario dp
                    WHERE dp.bus_id = b.id
                      AND dp.fecha  < ?
                      AND dp.registradora_fin IS NOT NULL
                    ORDER BY dp.fecha DESC
                    LIMIT 1) AS ultima_reg_fin
             FROM buses b
        LEFT JOIN despacho_diario d ON d.bus_id = b.id AND d.fecha = ?
         ORDER BY b.numero""",
        (fecha, fecha),
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
    conn.close()

    salida = []
    for b in buses:
        b = dict(b)
        b["recaudo"] = vigentes.get(b["id"])
        b["anulados"] = anuladas.get(b["id"], [])
        salida.append(b)

    editable, motivo = _puede_liquidar(fecha)
    return jsonify({
        "fecha":       fecha,
        "hoy":         hoy_bogota(),
        "editable":    editable,
        "motivo":      motivo,
        "tarifas":     tarifas,
        "tipos_gasto": tipos,
        "rutas":       [dict(r) for r in rutas],
        "conductores": [dict(c) for c in conductores],
        "buses":       salida,
    })


# ──────────────────────────────────────────
#  Liquidar (solo crea: una liquidación guardada no se modifica)
# ──────────────────────────────────────────

def _armar_gastos(conn, gastos_in, n_conductores):
    """Valida los gastos reportados: tipo activo, valor > 0, sin repetir tipo por conductor."""
    if gastos_in in (None, ""):
        return []
    if not isinstance(gastos_in, list) or len(gastos_in) > 40:
        raise _Rechazo("Lista de gastos inválida")
    tipos = {t["id"]: t["nombre"] for t in _tipos_gasto(conn)}
    gastos, vistos = [], set()
    for g in gastos_in:
        g = g if isinstance(g, dict) else {}
        tipo_id = _entero(g.get("tipo_gasto_id"), "El tipo de gasto")
        if tipo_id not in tipos:
            raise _Rechazo("Hay un tipo de gasto que no existe o está desactivado")
        nombre = tipos[tipo_id]
        orden = _entero(g.get("orden_conductor"), "El conductor del gasto", requerido=False) or 1
        if not 1 <= orden <= n_conductores:
            raise _Rechazo(f"El gasto {nombre} apunta a un conductor que no está en la liquidación")
        if (orden, tipo_id) in vistos:
            raise _Rechazo(f"El gasto {nombre} está repetido")
        vistos.add((orden, tipo_id))
        valor = _entero(g.get("valor"), f"El valor de {nombre}")
        if valor == 0:
            continue   # un gasto en cero es lo mismo que no reportarlo
        if valor > _GASTO_MAXIMO:
            raise _Rechazo(f"El valor de {nombre} es demasiado alto")
        gastos.append({"orden_conductor": orden, "tipo_gasto_id": tipo_id, "tipo_nombre": nombre,
                       "valor": valor, "observacion": _texto(g.get("observacion"), 200)})
    return gastos


def _armar_tramos(conn, conductores_in, reg_inicio, reg_fin, tarifa, gastos):
    """Valida los conductores y calcula el tramo de registradora y los totales de cada uno.
    Obligatorios por conductor: conductor, ruta, viajes (>= 1), pasajeros (>= 1) y recaudo.
    Los gastos son opcionales."""
    tramos, vistos, inicio = [], set(), reg_inicio
    for i, c in enumerate(conductores_in):
        n = i + 1
        ultimo = n == len(conductores_in)
        c = c if isinstance(c, dict) else {}
        # Con un solo conductor los mensajes no necesitan número.
        cual = f" del conductor {n}" if len(conductores_in) > 1 else ""

        conductor_id = _entero(c.get("conductor_id"), "El conductor" + (f" {n}" if cual else ""))
        if conductor_id in vistos:
            raise _Rechazo("Un mismo conductor no puede aparecer dos veces en la liquidación")
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

        # El último conductor termina en la lectura final del bus; los demás en su relevo.
        if ultimo:
            fin = reg_fin
        else:
            fin = _entero(c.get("registradora_fin"), f"La registradora al relevo del conductor {n}")
            if fin < inicio or fin > reg_fin:
                raise _Rechazo(f"La registradora al relevo del conductor {n} debe estar "
                               f"entre {inicio} y {reg_fin}")

        recaudado = _entero(c.get("recaudado"), f"El recaudo entregado{cual}")
        pasajeros = fin - inicio
        if pasajeros < 1:
            raise _Rechazo(f"No hay pasajeros{cual}: la registradora final debe ser mayor que la inicial")
        producido = pasajeros * tarifa
        total_gastos = sum(g["valor"] for g in gastos if g["orden_conductor"] == n)
        neto = producido - total_gastos
        tramos.append({
            "orden": n, "conductor_id": conductor_id, "conductor_nombre": conductor["nombre"],
            "conductor_cedula": conductor.get("cedula"), "ruta_id": ruta_id, "viajes": viajes,
            "registradora_inicio": inicio, "registradora_fin": fin, "pasajeros": pasajeros,
            "producido": producido, "total_gastos": total_gastos, "neto": neto,
            "recaudado": recaudado, "diferencia": recaudado - neto,
            "observacion": _texto(c.get("observacion")),
        })
        inicio = fin
    return tramos


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
        reg_inicio = _entero(data.get("registradora_inicio"), "La registradora inicial")
        reg_fin = _entero(data.get("registradora_fin"), "La registradora final")
        if reg_fin < reg_inicio:
            raise _Rechazo("Lectura inválida: la registradora final es menor que la inicial")
        if reg_fin == reg_inicio:
            raise _Rechazo("No hay pasajeros: la registradora final es igual a la inicial")

        bus = conn.execute("SELECT id, numero, placa, grupo FROM buses WHERE id = ?",
                           (bus_id,)).fetchone()
        if not bus:
            raise _Rechazo("El vehículo no existe", 404)
        bus = dict(bus)

        if _vigente(conn, bus_id, fecha):
            raise _Rechazo(f"El bus {bus['numero']} ya está liquidado ese día. Una liquidación "
                           "guardada no se modifica: solo el administrador puede anularla.", 409)

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
        gastos = _armar_gastos(conn, data.get("gastos"), len(conductores_in))
        tramos = _armar_tramos(conn, conductores_in, reg_inicio, reg_fin, tarifa, gastos)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    pasajeros = reg_fin - reg_inicio
    producido = sum(t["producido"] for t in tramos)
    total_gastos = sum(g["valor"] for g in gastos)
    neto = producido - total_gastos
    recaudado = sum(t["recaudado"] for t in tramos)
    diferencia = recaudado - neto
    uid = getattr(request, "jwt_user_id", None)

    try:
        cur = conn.execute(
            """INSERT INTO recaudos
                   (empresa_id, fecha, bus_id, registradora_inicio, registradora_fin, pasajeros,
                    tarifa, producido, total_gastos, neto, recaudado, diferencia, observacion,
                    usuario_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (EMPRESA_POR_DEFECTO, fecha, bus_id, reg_inicio, reg_fin, pasajeros, tarifa,
             producido, total_gastos, neto, recaudado, diferencia,
             _texto(data.get("observacion")), uid),
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
            if antes != (reg_inicio, reg_fin):
                correccion = antes
            conn.execute(
                """UPDATE despacho_diario
                      SET registradora_inicio = ?, registradora_fin = ?,
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
        )
        if len(tramos) > 1:
            descripcion += " Relevo: " + "; ".join(
                f"{t['orden']}) {t['conductor_nombre']} {t['registradora_inicio']}→{t['registradora_fin']}: "
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
        auditoria.registrar(
            conn, "recaudo", "liquidacion", recaudo_id, "crear", descripcion,
            {"fecha": fecha, "bus": bus["numero"], "registradora": [reg_inicio, reg_fin],
             "pasajeros": pasajeros, "tarifa": tarifa, "producido": producido,
             "gastos": [f"{g['tipo_nombre']} {auditoria.pesos(g['valor'])}" for g in gastos],
             "total_gastos": total_gastos, "neto": neto, "recaudado": recaudado,
             "diferencia": diferencia,
             "despacho_antes": list(correccion) if correccion else None,
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


@bp.route("/api/recaudo/<int:recaudo_id>/anular", methods=["POST"])
@rol(*ADMIN)
def anular(recaudo_id):
    """Anula una liquidación (no la borra): queda en el historial con quién y por
    qué, y el bus vuelve a quedar por liquidar. El despacho no se modifica."""
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

    conn.execute(
        "UPDATE recaudos SET anulado_at = ?, anulado_por = ?, motivo_anulacion = ? WHERE id = ?",
        (_ahora(), getattr(request, "jwt_user_id", None), motivo, recaudo_id),
    )
    auditoria.registrar(
        conn, "recaudo", "liquidacion", recaudo_id, "anular",
        (f"Anuló la liquidación del bus {r['bus_numero']} ({r['bus_placa'] or 's/placa'}) del "
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


def _rango_propietario():
    """(desde, hasta) validados; por defecto el mes en curso (hora Bogotá)."""
    hoy = hoy_bogota()
    desde = request.args.get("desde") or hoy[:8] + "01"
    hasta = request.args.get("hasta") or hoy
    if not _fecha_valida(desde) or not _fecha_valida(hasta) or desde > hasta:
        raise _Rechazo("Rango de fechas inválido (use AAAA-MM-DD)")
    if (date.fromisoformat(hasta) - date.fromisoformat(desde)).days > _MAX_DIAS_PROPIETARIO:
        raise _Rechazo(f"El rango no puede pasar de {_MAX_DIAS_PROPIETARIO} días")
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
    liquidaciones = _cargar(
        conn, f"r.fecha BETWEEN ? AND ? AND r.anulado_at IS NULL{where}", [desde, hasta] + params
    )
    conn.close()
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
        f"""SELECT r.bus_id, COUNT(*) AS dias,
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
        nombre = _nombre_tipo(data.get("nombre"))
        if _nombre_repetido(conn, nombre):
            raise _Rechazo(f"Ya existe un gasto llamado «{nombre}»", 409)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    orden = max([t["orden"] for t in _tipos_gasto(conn, solo_activos=False)] or [0]) + 1
    cur = conn.execute(
        "INSERT INTO recaudo_tipos_gasto (empresa_id, nombre, orden) VALUES (?,?,?)",
        (EMPRESA_POR_DEFECTO, nombre, orden),
    )
    tipo_id = cur.lastrowid
    auditoria.registrar(conn, "recaudo", "tipo_gasto", tipo_id, "crear",
                        f"Creó el tipo de gasto «{nombre}»", {"nombre": nombre})
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": tipo_id}), 201


@bp.route("/api/recaudo/tipos-gasto/<int:tipo_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_tipo_gasto(tipo_id):
    """Body: {nombre?, activo?, orden?}. No se borran: se desactivan."""
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
        if "activo" in data:
            nuevo["activo"] = 1 if data["activo"] in (1, True, "1", "true") else 0
        if "orden" in data:
            nuevo["orden"] = _entero(data["orden"], "El orden")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    cambios = auditoria.diferencias(actual, nuevo, ("nombre", "activo", "orden"))
    if cambios:
        conn.execute(
            "UPDATE recaudo_tipos_gasto SET nombre = ?, activo = ?, orden = ? WHERE id = ?",
            (nuevo["nombre"], nuevo["activo"], nuevo["orden"], tipo_id),
        )
        if set(cambios) == {"activo"}:
            accion = "activar" if nuevo["activo"] else "desactivar"
            texto = f"{'Activó' if nuevo['activo'] else 'Desactivó'} el tipo de gasto «{actual['nombre']}»"
        else:
            accion = "editar"
            texto = (f"Editó el tipo de gasto «{actual['nombre']}»: "
                     f"{auditoria.describir(cambios, {'nombre': 'Nombre', 'activo': 'Activo', 'orden': 'Orden'})}")
        auditoria.registrar(conn, "recaudo", "tipo_gasto", tipo_id, accion, texto, cambios)
        conn.commit()
    conn.close()
    return jsonify({"ok": True})
