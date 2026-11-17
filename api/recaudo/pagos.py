"""Pagos diarios de caja: la plata que entra o sale de la caja del recaudador por
fuera de las liquidaciones de los buses (pago de admon, locales, servicios,
parqueos, abonos, anticipos, reembolsos…).

- Se registran con los conceptos del catálogo que no usa el sistema (los de `uso`
  son RECAUDOS CU y CIERRE DE CAJA). El `signo` del concepto dice si la plata ENTRA
  (2, crédito) o SALE (1, débito) de la caja.
- A quién va la factura (NIT del archivo plano) depende del tercero del concepto:
    PROPIETARIO → el propietario según la tarjeta de propiedad del bus elegido; en las
                  entradas además se pide quién paga (conductor, tercero o el mismo
                  propietario): sale en el recibo, el cierre y la descripción del plano;
    PAGADOR     → un tercero de Catálogo › Recaudo › Terceros, o un conductor o
                  propietario de la flota, que queda como tercero (terceros.py);
    FIJO        → el NIT fijo del concepto;
    NINGUNO     → nadie (la observación es obligatoria: qué se pagó).
- La fecha es la de hoy en Bogotá (la pone el servidor), y es el día de la caja en que
  entra el pago. Excepciones, un día pasado cuya caja (la del que registra) sigue abierta:
    · reabierta por el Administrador: entra el pago corregido (o uno que se olvidó),
      porque esa plata entró a la caja ese día (pedido del usuario 2026-11-05);
    · sin cerrar todavía (tiene movimientos pendientes y nunca se cerró): el pago entra
      a esa caja antes de cerrarla (pedido del usuario 2026-11-07). Solo efectivo.
- Al guardar se copian el concepto, el bus y el tercero, para que el recibo y los
  cierres viejos no cambien si después se edita el catálogo.
- Igual que una liquidación: no se edita; solo el Administrador lo anula (con
  motivo) mientras no esté en una caja cerrada. Entra al cierre de caja (caja.py)
  y al archivo plano (contable.py).
"""
import re
from datetime import date

from flask import jsonify, request

import auditoria

from . import bp
from .comun import EMPRESA_POR_DEFECTO, ROLES_RECAUDO, db, hoy_bogota, rol
from .endpoints import (_ahora, _entero, _fecha_iso, _fecha_valida, _hora_utc, _Rechazo, _texto,
                        autorizar_reimpresion, dia_sin_cerrar, reimpresiones)
from .informe import MAX_DIAS, _orden_bus
from .terceros import (TIPOS_DOCUMENTO, _documento_catalogo, documento_con_dv, pagadores,
                       tercero_de_pagador)

ADMIN = ("Administrador",)
_PAGO_MAXIMO = 50_000_000


def _es_admin():
    return getattr(request, "jwt_user_rol", None) == "Administrador"


def numero_pago(pago_id):
    return "N° " + str(pago_id).zfill(6)


def conceptos_pago(conn):
    """Conceptos activos que se pueden usar en los pagos diarios (sin uso del sistema)."""
    return [dict(c) for c in conn.execute(
        """SELECT id, nombre, cuenta, tercero, nit_fijo, signo, centro_costo, descripcion, referencia
             FROM recaudo_conceptos
            WHERE empresa_id = ? AND activo = 1 AND (uso IS NULL OR uso = '')
         ORDER BY signo DESC, orden, nombre""",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()]


def _fila(r):
    d = dict(r)
    d["fecha"] = _fecha_iso(d.get("fecha"))
    for k in ("created_at", "anulado_at"):
        d[k] = _hora_utc(d.get(k))
    return d


def cargar_pagos(conn, where, params):
    """Pagos con lo congelado al guardar y, aparte (`*_actual`), lo que dice hoy el
    catálogo: el archivo plano toma la cuenta y el NIT actuales para poder corregir
    un error de digitación sin anular."""
    return [_fila(r) for r in conn.execute(
        f"""SELECT p.*, u.nombre AS usuario_nombre, ua.nombre AS anulado_por_nombre,
                   c.cuenta AS cuenta_actual, c.centro_costo AS centro_costo_actual,
                   c.referencia AS referencia_actual, c.nit_fijo AS nit_fijo_actual,
                   t.documento AS tercero_documento_actual, t.dv AS tercero_dv_actual,
                   b.tp_propietario_documento AS propietario_documento_actual
              FROM recaudo_pagos p
         LEFT JOIN usuarios u  ON u.id  = p.usuario_id
         LEFT JOIN usuarios ua ON ua.id = p.anulado_por
         LEFT JOIN recaudo_conceptos c ON c.id = p.concepto_id
         LEFT JOIN recaudo_terceros t ON t.id = p.tercero_id
         LEFT JOIN buses b ON b.id = p.bus_id
             WHERE {where}
          ORDER BY p.created_at, p.id""",
        params,
    ).fetchall()]


def totales_pagos(pagos):
    """Solo de los vigentes: entradas (signo 2) y salidas (signo 1)."""
    vigentes = [p for p in pagos if not p.get("anulado_at")]
    ingresos = sum(int(p["valor"]) for p in vigentes if p["signo"] == 2)
    egresos = sum(int(p["valor"]) for p in vigentes if p["signo"] == 1)
    return {"pagos": len(vigentes), "ingresos": ingresos, "egresos": egresos}


def quien(p):
    """'vehículo 12 · NOMBRE' o 'NOMBRE (NIT 900123456-7)' para textos y auditoría."""
    partes = []
    if p.get("bus_numero") is not None:
        partes.append(f"vehículo {p['bus_numero']}")
    if p.get("tercero_nombre"):
        doc = documento_con_dv({"documento": p.get("tercero_documento"), "dv": p.get("tercero_dv")})
        partes.append(p["tercero_nombre"] + (f" ({doc})" if doc else ""))
    if p.get("pagador_nombre"):
        doc = documento_con_dv({"documento": p.get("pagador_documento"), "dv": p.get("pagador_dv")})
        partes.append("pagó " + p["pagador_nombre"] + (f" ({doc})" if doc else ""))
    return " · ".join(partes)


# ──────────────────────────────────────────
#  Consulta del día
# ──────────────────────────────────────────

def caja_reabierta(conn, usuario_id, fecha):
    """El cierre reabierto del día de caja del recaudador, si el último cierre de ese día
    está reabierto (el día está abierto para corregir); si no, None."""
    fila = conn.execute(
        """SELECT id, reabierto_at, motivo_reapertura FROM recaudo_cierres
            WHERE usuario_id = ? AND fecha = ? ORDER BY id DESC LIMIT 1""",
        (usuario_id, fecha),
    ).fetchone()
    if not fila or not dict(fila)["reabierto_at"]:
        return None
    f = dict(fila)
    return {"id": f["id"], "reabierto_at": _hora_utc(f["reabierto_at"]),
            "motivo_reapertura": f["motivo_reapertura"]}


def dias_abiertos(conn, usuario_id, hoy):
    """Días pasados en los que el usuario todavía puede registrar pagos: su caja de ese
    día sigue sin cerrar o el Administrador la reabrió. Para avisarle en la caja de hoy."""
    candidatos = set()
    for sql in ("""SELECT DISTINCT caja_fecha AS d FROM recaudos
                    WHERE usuario_id = ? AND anulado_at IS NULL AND cierre_id IS NULL AND caja_fecha < ?""",
                """SELECT DISTINCT fecha AS d FROM recaudo_pagos
                    WHERE usuario_id = ? AND anulado_at IS NULL AND cierre_id IS NULL AND fecha < ?""",
                """SELECT DISTINCT fecha AS d FROM recaudo_cierres
                    WHERE usuario_id = ? AND reabierto_at IS NOT NULL AND fecha < ?"""):
        candidatos |= {_fecha_iso(dict(f)["d"]) for f in conn.execute(sql, (usuario_id, hoy)).fetchall()}
    return [d for d in sorted(c for c in candidatos if c)
            if caja_reabierta(conn, usuario_id, d) or dia_sin_cerrar(conn, usuario_id, d)]


@bp.route("/api/recaudo/pagos", methods=["GET"])
@rol(*ROLES_RECAUDO)
def pagos_del_dia():
    """?fecha=AAAA-MM-DD (hoy por defecto). El Recaudador ve solo los suyos."""
    fecha = _fecha_valida(request.args.get("fecha") or hoy_bogota())
    if not fecha:
        return jsonify({"error": "Fecha inválida (use AAAA-MM-DD)"}), 400
    where, params = "p.fecha = ? AND p.empresa_id = ?", [fecha, EMPRESA_POR_DEFECTO]
    if not _es_admin():
        where += " AND p.usuario_id = ?"
        params.append(getattr(request, "jwt_user_id", None))
    conn = db()
    pagos = cargar_pagos(conn, where, params)
    veces = reimpresiones(conn, "pago", [p["id"] for p in pagos])
    for p in pagos:
        p["reimpresiones"] = veces.get(p["id"], 0)
    buses = [dict(b) for b in conn.execute(
        """SELECT id, numero, placa, grupo, tp_propietario_nombre, tp_propietario_documento
             FROM buses ORDER BY numero"""
    ).fetchall()]
    hoy = hoy_bogota()
    uid = getattr(request, "jwt_user_id", None)
    # Un día pasado admite registrar pagos si la caja de quien consulta sigue abierta:
    # reabierta por el Administrador o todavía sin cerrar.
    reabierto = caja_reabierta(conn, uid, fecha) if fecha < hoy else None
    salida = {
        "fecha": fecha,
        "hoy": hoy,
        "dia_reabierto": reabierto,
        "dia_sin_cerrar": bool(fecha < hoy and not reabierto and dia_sin_cerrar(conn, uid, fecha)),
        "dias_abiertos": dias_abiertos(conn, uid, hoy) if fecha == hoy else [],
        "pagos": pagos,
        "totales": totales_pagos(pagos),
        "conceptos": conceptos_pago(conn),
        "pagadores": pagadores(conn),
        "tipos_documento": TIPOS_DOCUMENTO,
        "buses": buses,
    }
    conn.close()
    salida["totales"]["neto"] = salida["totales"]["ingresos"] - salida["totales"]["egresos"]
    return jsonify(salida)


# ──────────────────────────────────────────
#  Registrar (solo crea: un pago guardado no se modifica)
# ──────────────────────────────────────────

@bp.route("/api/recaudo/pagos", methods=["POST"])
@rol(*ROLES_RECAUDO)
def registrar_pago():
    """Body: {concepto_id, valor, bus_id?, pagador?, tercero_id?, observacion?, fecha?}.
    `fecha` solo si es un día pasado cuya caja (la del que registra) sigue abierta:
    reabierta por el Administrador o todavía sin cerrar."""
    data = request.get_json(silent=True) or {}
    conn = db()
    aviso = None
    uid = getattr(request, "jwt_user_id", None)
    hoy = fecha = hoy_bogota()
    try:
        if data.get("fecha") and data.get("fecha") != hoy:
            fecha = _fecha_valida(data.get("fecha"))
            if not fecha or fecha > hoy:
                raise _Rechazo("Fecha inválida")
            if not (caja_reabierta(conn, uid, fecha) or dia_sin_cerrar(conn, uid, fecha)):
                raise _Rechazo("La caja de ese día ya está cerrada (o no tiene movimientos): "
                               "solo se registra ahí si el administrador la reabre.", 409)
        concepto_id = _entero(data.get("concepto_id"), "El concepto")
        fila = conn.execute("SELECT * FROM recaudo_conceptos WHERE id = ? AND empresa_id = ?",
                            (concepto_id, EMPRESA_POR_DEFECTO)).fetchone()
        concepto = dict(fila) if fila else None
        if not concepto or concepto.get("uso") or not concepto.get("activo"):
            raise _Rechazo("Este concepto no está disponible para pagos diarios")
        valor = _entero(data.get("valor"), "El valor")
        if valor < 1:
            raise _Rechazo("El valor debe ser mayor que cero")
        if valor > _PAGO_MAXIMO:
            raise _Rechazo("El valor es demasiado alto")
        observacion = _texto(data.get("observacion"), 300)
        tipo = concepto["tercero"]
        entra = concepto["signo"] == 2

        bus, copia = None, {"nombre": None, "tipo_documento": None, "documento": None, "dv": None}
        tercero_id, pagador = None, None
        if tipo == "PROPIETARIO" or concepto.get("referencia") == "VEHICULO":
            bus_id = _entero(data.get("bus_id"), "El vehículo")
            fila = conn.execute(
                """SELECT id, numero, placa, tp_propietario_nombre, tp_propietario_documento
                     FROM buses WHERE id = ?""", (bus_id,)).fetchone()
            if not fila:
                raise _Rechazo("El vehículo no existe", 404)
            bus = dict(fila)
        if tipo == "PROPIETARIO":
            documento = re.sub(r"\D", "", str(bus.get("tp_propietario_documento") or ""))
            copia.update(nombre=bus.get("tp_propietario_nombre"), documento=documento or None)
            if not documento:
                aviso = (f"El bus {bus['numero']} no tiene el documento del propietario (tarjeta de "
                         "propiedad): complétalo en Catálogo › Buses antes del archivo plano.")
            if entra:
                # La factura va al propietario, pero la plata la pone quien paga (el conductor,
                # un tercero o el mismo propietario): se guarda aparte (pedido del usuario 2026-11-03).
                if not data.get("pagador"):
                    raise _Rechazo("Falta llenar: quién paga")
                pagador = tercero_de_pagador(conn, data["pagador"])
        elif tipo == "PAGADOR":
            # `pagador`: clave de la lista de "Quién paga" (tercero, conductor o propietario);
            # `tercero_id` se sigue aceptando.
            clave = data.get("pagador")
            if not clave:
                clave = "t%d" % _entero(data.get("tercero_id"),
                                        "Quién paga" if entra else "A quién se le paga")
            tercero = tercero_de_pagador(conn, clave)
            tercero_id = tercero["id"]
            copia.update(nombre=tercero["nombre"], tipo_documento=tercero["tipo_documento"],
                         documento=tercero["documento"], dv=tercero.get("dv"))
        elif tipo == "FIJO":
            copia.update(documento=concepto.get("nit_fijo"))
        elif not observacion:
            raise _Rechazo("Falta llenar: qué se pagó (observación)")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    cur = conn.execute(
        """INSERT INTO recaudo_pagos
               (empresa_id, fecha, concepto_id, concepto_nombre, cuenta, signo, centro_costo,
                concepto_tercero, referencia, valor, bus_id, bus_numero, bus_placa, tercero_id,
                tercero_nombre, tercero_tipo_documento, tercero_documento, tercero_dv,
                pagador_tercero_id, pagador_nombre, pagador_tipo_documento, pagador_documento,
                pagador_dv, observacion, usuario_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (EMPRESA_POR_DEFECTO, fecha, concepto_id, concepto["nombre"], concepto["cuenta"],
         concepto["signo"], concepto.get("centro_costo"), tipo, concepto.get("referencia") or "",
         valor, bus["id"] if bus else None, bus["numero"] if bus else None,
         bus.get("placa") if bus else None, tercero_id, copia["nombre"], copia["tipo_documento"],
         copia["documento"], copia["dv"],
         pagador["id"] if pagador else None, pagador["nombre"] if pagador else None,
         pagador["tipo_documento"] if pagador else None, pagador["documento"] if pagador else None,
         pagador.get("dv") if pagador else None, observacion, uid),
    )
    pago_id = cur.lastrowid
    pago = {"bus_numero": bus["numero"] if bus else None, "tercero_nombre": copia["nombre"],
            "tercero_documento": copia["documento"], "tercero_dv": copia["dv"],
            "pagador_nombre": pagador["nombre"] if pagador else None,
            "pagador_documento": pagador["documento"] if pagador else None,
            "pagador_dv": pagador.get("dv") if pagador else None}
    detalle = quien(pago)
    auditoria.registrar(
        conn, "recaudo", "pago", pago_id, "crear",
        (f"Registró el pago {numero_pago(pago_id)}: {concepto['nombre']} "
         f"({'entrada' if entra else 'salida'} de caja, cuenta {concepto['cuenta']}) por "
         f"{auditoria.pesos(valor)}" + (f" — {detalle}" if detalle else "")
         + (f". Obs: {observacion}" if observacion else "")
         + (f". Entra a la caja del día {fecha}" if fecha != hoy else "") + "."),
        {"fecha": fecha, "concepto": concepto["nombre"], "cuenta": concepto["cuenta"], "signo": concepto["signo"],
         "valor": valor, "bus": bus["numero"] if bus else None, "tercero": copia["nombre"],
         "documento": copia["documento"], "pagador": pagador["nombre"] if pagador else None,
         "observacion": observacion},
    )
    conn.commit()
    pago = cargar_pagos(conn, "p.id = ?", [pago_id])[0]
    conn.close()
    return jsonify({"ok": True, "pago": pago, "aviso": aviso}), 201


@bp.route("/api/recaudo/pagos/<int:pago_id>/reimpresion", methods=["POST"])
@rol(*ROLES_RECAUDO)
def reimprimir_pago(pago_id):
    """Una vez para quien lo registró; más copias, el Administrador (ver endpoints.py)."""
    conn = db()
    filas = cargar_pagos(conn, "p.id = ? AND p.empresa_id = ?", [pago_id, EMPRESA_POR_DEFECTO])
    if not filas:
        conn.close()
        return jsonify({"error": "Pago no encontrado"}), 404
    p = filas[0]
    try:
        veces = autorizar_reimpresion(
            conn, "pago", pago_id, p.get("usuario_id"),
            f"Reimprimió el recibo del pago {numero_pago(pago_id)} ({p['concepto_nombre']} "
            f"por {auditoria.pesos(p['valor'])})")
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status
    conn.close()
    return jsonify({"ok": True, "reimpresiones": veces})


# ──────────────────────────────────────────
#  Anular (solo Administrador, con motivo)
# ──────────────────────────────────────────

@bp.route("/api/recaudo/pagos/<int:pago_id>/anular", methods=["POST"])
@rol(*ADMIN)
def anular_pago(pago_id):
    """No se borra: queda con quién, cuándo y por qué, y sale de la caja abierta."""
    data = request.get_json(silent=True) or {}
    motivo = _texto(data.get("motivo"), 500)
    if not motivo or len(motivo) < 5:
        return jsonify({"error": "Escribe el motivo de la anulación (mínimo 5 caracteres)"}), 400

    conn = db()
    filas = cargar_pagos(conn, "p.id = ? AND p.empresa_id = ?", [pago_id, EMPRESA_POR_DEFECTO])
    if not filas:
        conn.close()
        return jsonify({"error": "Pago no encontrado"}), 404
    p = filas[0]
    if p["anulado_at"]:
        conn.close()
        return jsonify({"error": "Este pago ya estaba anulado"}), 409
    if p.get("cierre_id"):
        conn.close()
        return jsonify({"error": f"Este pago está en la caja cerrada N° {p['cierre_id']}. "
                                 "Primero reabre esa caja en Recaudo › Cierre de caja."}), 409

    # Solo si sigue abierto: si en este instante entró a un cierre, no se toca.
    cur = conn.execute(
        """UPDATE recaudo_pagos SET anulado_at = ?, anulado_por = ?, motivo_anulacion = ?
            WHERE id = ? AND anulado_at IS NULL AND cierre_id IS NULL""",
        (_ahora(), getattr(request, "jwt_user_id", None), motivo, pago_id),
    )
    if not cur.rowcount:
        conn.rollback()
        conn.close()
        return jsonify({"error": "El pago acaba de entrar a un cierre de caja. Recarga la página."}), 409
    detalle = quien(p)
    auditoria.registrar(
        conn, "recaudo", "pago", pago_id, "anular",
        (f"Anuló el pago {numero_pago(pago_id)} del {p['fecha']}: {p['concepto_nombre']} "
         f"({'entrada' if p['signo'] == 2 else 'salida'}) por {auditoria.pesos(p['valor'])}"
         + (f" — {detalle}" if detalle else "") + f". Motivo: {motivo}"),
        {"fecha": p["fecha"], "concepto": p["concepto_nombre"], "valor": p["valor"],
         "signo": p["signo"], "motivo": motivo},
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ──────────────────────────────────────────
#  Reporte de pagos (pantalla Reporte de pagos): un periodo, con filtros y Excel
# ──────────────────────────────────────────
#
# Un pago no guarda conductor_id ni propietario_id: solo copia el nombre y el documento
# de a quién va la factura (`tercero_*`) y de quién puso la plata (`pagador_*`). Por eso
# los filtros por persona se resuelven cruzando documentos NORMALIZADOS (los mismos que
# guarda el pago) contra el catálogo de hoy, y los del propietario además por sus buses.
# Límites conocidos, avisados en la pantalla: si cambian una cédula en el catálogo, los
# pagos viejos dejan de cruzar; y un bus que cambió de dueño arrastra los pagos del dueño
# anterior.

def _solo_digitos(valor):
    return re.sub(r"\D", "", str(valor or ""))


def _documentos_de(crudo, puede_ser_nit=False):
    """Documentos con los que puede estar guardado ese número en un pago: el normalizado
    del catálogo y, por si acaso, los dígitos tal cual (un NIT con el DV pegado, por
    ejemplo: `_documento_catalogo` lo devuelve sin DV y los pagos de concepto PROPIETARIO
    copian lo que diga la tarjeta de propiedad)."""
    _tipo, doc = _documento_catalogo(crudo, puede_ser_nit=puede_ser_nit)
    return {d for d in (doc, _solo_digitos(crudo)) if d}


def _marcadores(n):
    return ",".join("?" * n)


def _buses_del_propietario(conn, propietario_id, documentos):
    """Buses de ese propietario: los del catálogo (`propietario_id`) y los que lo tengan
    en la tarjeta de propiedad (`tp_propietario_documento`), que no siempre coinciden."""
    ids = {r["id"] for r in conn.execute(
        "SELECT id FROM buses WHERE propietario_id = ?", (propietario_id,)).fetchall()}
    if documentos:
        for r in conn.execute("SELECT id, tp_propietario_documento FROM buses").fetchall():
            if _solo_digitos(dict(r)["tp_propietario_documento"]) in documentos:
                ids.add(dict(r)["id"])
    return sorted(ids)


def _listas_reporte(conn):
    """Lo que llena los filtros de la pantalla. Van los inactivos también (marcados): un
    pago viejo puede ser de un conductor que ya no está."""
    conductores = [dict(r) for r in conn.execute(
        "SELECT id, nombre, cedula, activo FROM conductores ORDER BY activo DESC, nombre").fetchall()]
    propietarios = [dict(r) for r in conn.execute(
        "SELECT id, nombre, cedula, activo FROM propietarios ORDER BY activo DESC, nombre").fetchall()]
    buses = sorted(
        (dict(r) for r in conn.execute("SELECT id, numero, placa, grupo FROM buses").fetchall()),
        key=lambda b: _orden_bus(b["numero"]))
    return {"conductores": conductores, "propietarios": propietarios, "buses": buses,
            "conceptos": conceptos_pago(conn)}


def _resumenes(pagos):
    """Los tres cortes que ve la pantalla y que van al Excel, solo con los vigentes."""
    dias, conceptos, buses = {}, {}, {}
    for p in pagos:
        if p.get("anulado_at"):
            continue
        entra = p["signo"] == 2
        valor = int(p["valor"])
        d = dias.setdefault(p["fecha"], {"fecha": p["fecha"], "pagos": 0, "ingresos": 0, "egresos": 0})
        c = conceptos.setdefault(p["concepto_id"], {
            "concepto_id": p["concepto_id"], "concepto_nombre": p["concepto_nombre"],
            "cuenta": p["cuenta"], "signo": p["signo"], "pagos": 0, "total": 0})
        for x in (d, c):
            x["pagos"] += 1
        c["total"] += valor
        d["ingresos" if entra else "egresos"] += valor
        if p.get("bus_id"):
            b = buses.setdefault(p["bus_id"], {
                "bus_id": p["bus_id"], "numero": p.get("bus_numero"), "placa": p.get("bus_placa"),
                "propietario": p.get("tercero_nombre") if p["concepto_tercero"] == "PROPIETARIO" else None,
                "pagos": 0, "ingresos": 0, "egresos": 0})
            b["pagos"] += 1
            b["ingresos" if entra else "egresos"] += valor
            if not b["propietario"] and p["concepto_tercero"] == "PROPIETARIO":
                b["propietario"] = p.get("tercero_nombre")
    for d in dias.values():
        d["neto"] = d["ingresos"] - d["egresos"]
    return (sorted(dias.values(), key=lambda d: d["fecha"]),
            sorted(conceptos.values(), key=lambda c: (-c["signo"], c["concepto_nombre"])),
            sorted(buses.values(), key=lambda b: _orden_bus(b["numero"])))


@bp.route("/api/recaudo/pagos/reporte", methods=["GET"])
@rol(*ROLES_RECAUDO)
def reporte_pagos():
    """Pagos diarios de un periodo con filtros, para la pantalla Reporte de pagos (el Excel
    lo arma recaudo-reportes.html). A diferencia del listado del día, aquí el Recaudador ve
    los pagos de todos (decisión del usuario 2026-11-17): el reporte es para cuadrar la caja
    del periodo, no para operar."""
    a = request.args
    desde, hasta = _fecha_valida(a.get("desde")), _fecha_valida(a.get("hasta"))
    if not desde or not hasta:
        return jsonify({"error": "Fechas inválidas (use AAAA-MM-DD)"}), 400
    if desde > hasta:
        return jsonify({"error": "La fecha inicial no puede ser mayor que la final"}), 400
    if (date.fromisoformat(hasta) - date.fromisoformat(desde)).days >= MAX_DIAS:
        return jsonify({"error": f"El reporte abarca máximo {MAX_DIAS} días"}), 400

    estado = (a.get("estado") or "vigentes").lower()
    if estado not in ("vigentes", "anulados", "todos"):
        return jsonify({"error": "Estado inválido (vigentes, anulados o todos)"}), 400

    conn = db()
    try:
        where = ["p.fecha BETWEEN ? AND ?", "p.empresa_id = ?"]
        params = [desde, hasta, EMPRESA_POR_DEFECTO]
        if estado == "vigentes":
            where.append("p.anulado_at IS NULL")
        elif estado == "anulados":
            where.append("p.anulado_at IS NOT NULL")
        for campo, etiqueta in (("concepto_id", "El concepto"), ("bus_id", "El vehículo")):
            if a.get(campo):
                where.append(f"p.{campo} = ?")
                params.append(_entero(a.get(campo), etiqueta))
        if a.get("signo"):
            signo = _entero(a.get("signo"), "El tipo de movimiento")
            if signo not in (1, 2):
                raise _Rechazo("El tipo de movimiento debe ser 1 (salida) o 2 (entrada)")
            where.append("p.signo = ?")
            params.append(signo)

        aviso, conductor, propietario = None, None, None
        if a.get("conductor_id"):
            cid = _entero(a.get("conductor_id"), "El conductor")
            fila = conn.execute("SELECT id, nombre, cedula FROM conductores WHERE id = ?", (cid,)).fetchone()
            if not fila:
                raise _Rechazo("El conductor no existe", 404)
            conductor = dict(fila)
            docs = sorted(_documentos_de(conductor["cedula"]))
            if not docs:
                aviso = (f"{conductor['nombre']} no tiene cédula en el catálogo, así que sus pagos "
                         "no se pueden relacionar. Complétala en Catálogo › Conductores.")
                where.append("1 = 0")
            else:
                where.append(f"(p.pagador_documento IN ({_marcadores(len(docs))}) "
                             f"OR p.tercero_documento IN ({_marcadores(len(docs))}))")
                params.extend(docs + docs)

        if a.get("propietario_id"):
            pid = _entero(a.get("propietario_id"), "El propietario")
            fila = conn.execute("SELECT id, nombre, cedula FROM propietarios WHERE id = ?", (pid,)).fetchone()
            if not fila:
                raise _Rechazo("El propietario no existe", 404)
            propietario = dict(fila)
            docs = sorted(_documentos_de(propietario["cedula"], puede_ser_nit=True))
            buses_suyos = _buses_del_propietario(conn, pid, docs)
            ramas, vals = [], []
            if docs:
                ramas.append(f"p.tercero_documento IN ({_marcadores(len(docs))})")
                vals.extend(docs)
                ramas.append(f"p.pagador_documento IN ({_marcadores(len(docs))})")
                vals.extend(docs)
            if buses_suyos:
                ramas.append(f"p.bus_id IN ({_marcadores(len(buses_suyos))})")
                vals.extend(buses_suyos)
            if not ramas:
                aviso = (f"{propietario['nombre']} no tiene cédula ni buses asignados, así que sus "
                         "pagos no se pueden relacionar. Complétalo en Catálogo.")
                where.append("1 = 0")
            else:
                where.append("(" + " OR ".join(ramas) + ")")
                params.extend(vals)
    except _Rechazo as e:
        conn.close()
        return jsonify({"error": str(e)}), e.status

    pagos = cargar_pagos(conn, " AND ".join(where), params)
    pagos.sort(key=lambda p: (p["fecha"], p.get("created_at") or "", p["id"]))
    for p in pagos:
        p["numero"] = numero_pago(p["id"])
        p["tipo"] = "Entrada" if p["signo"] == 2 else "Salida"
        p["estado"] = "Anulado" if p.get("anulado_at") else "Vigente"
    totales = totales_pagos(pagos)
    totales["neto"] = totales["ingresos"] - totales["egresos"]
    totales["anulados"] = sum(1 for p in pagos if p.get("anulado_at"))
    por_dia, por_concepto, por_bus = _resumenes(pagos)
    uid = getattr(request, "jwt_user_id", None)
    quien_pide = conn.execute("SELECT nombre FROM usuarios WHERE id = ?", (uid,)).fetchone() if uid else None
    listas = _listas_reporte(conn)
    conn.close()
    return jsonify({
        "desde": desde, "hasta": hasta, "hoy": hoy_bogota(),
        "generado_por": dict(quien_pide)["nombre"] if quien_pide else None,
        "aviso": aviso,
        "filtros": {"conductor": conductor, "propietario": propietario, "estado": estado},
        "pagos": pagos, "totales": totales,
        "por_dia": por_dia, "por_concepto": por_concepto, "por_bus": por_bus,
        "listas": listas,
    })
