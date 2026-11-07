"""Cierre de caja POR RECAUDADOR Y POR DÍA DE TRABAJO.

- La "caja abierta" de un recaudador son sus liquidaciones y sus pagos diarios
  (pagos.py) vigentes sin cierre, separados por día de trabajo: el día en que se
  recibió la plata (`recaudos.caja_fecha`, hora Bogotá; el del pago es su `fecha`), no
  el día de la tarjeta. Un bus del lunes que se liquida el miércoles entra a la caja
  del miércoles (pedido del usuario 2026-11-05).
- Cada día se cierra aparte y el cierre guarda su día (`recaudo_cierres.fecha`); los
  cierres se buscan por ese día. Si el mismo día se vuelve a recibir plata después de
  cerrado, ese día tiene un segundo cierre.
- El faltante o sobrante de caja se arrastra como saldo acumulado: la suma de la
  diferencia de caja de los cierres vigentes del recaudador hasta ese día. No cambia
  lo que debe entregar cada día; se calcula al vuelo, así reabrir y volver a cerrar
  un día corrige el acumulado de los días siguientes.
- Un día reabierto vuelve a la caja abierta con su mismo día y se vuelve a cerrar ahí
  (con el efectivo y la planilla del cierre anterior ya escritos), CON EL MISMO NÚMERO de
  caja: es la misma caja corregida, no una nueva (pedido del usuario 2026-11-05). Lo que
  tenía antes queda en el historial de modificaciones. La liquidación que
  reemplaza a una anulada de ese día entra a ese día (endpoints.dia_de_caja).
- No hay consignaciones ni conteo de billetes: el recaudador escribe el efectivo que
  entrega a la transportadora de valores y el sistema calcula la diferencia de caja:
      debe haber (esperado) = recaudado + entradas − salidas de los pagos diarios
      diferencia de caja    = efectivo − esperado
- Al cerrar, esas liquidaciones y pagos quedan bloqueados: no se pueden anular. Solo el
  Administrador reabre un cierre (con motivo); el cierre queda como historial y todo
  vuelve a la caja abierta del recaudador.
- El Administrador ve las cajas abiertas de todos y puede cerrar la de un recaudador
  ausente (queda registrado quién la cerró).
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

import auditoria

from . import bp
from .comun import EMPRESA_POR_DEFECTO, ROLES_RECAUDO, db, es_pg, rol
from .endpoints import _ahora, _cargar, _entero, _fecha_iso, _hora_utc, _Rechazo, _texto
from .pagos import cargar_pagos, totales_pagos

ADMIN = ("Administrador",)
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOGOTA = timedelta(hours=5)   # Colombia es UTC-5 todo el año


def _es_admin():
    return getattr(request, "jwt_user_rol", None) == "Administrador"


def _usuario_objetivo():
    """De quién es la caja: la propia; el Administrador puede pedir la de otro (?usuario_id=)."""
    pedido = request.args.get("usuario_id") or (request.get_json(silent=True) or {}).get("usuario_id")
    if pedido and _es_admin():
        return _entero(pedido, "El recaudador")
    return getattr(request, "jwt_user_id", None)


def _pendientes(conn, usuario_id):
    """(liquidaciones, pagos) vigentes del recaudador que todavía no entran en un cierre."""
    liqs = _cargar(conn, "r.usuario_id = ? AND r.anulado_at IS NULL AND r.cierre_id IS NULL", [usuario_id])
    pagos = cargar_pagos(conn, "p.usuario_id = ? AND p.anulado_at IS NULL AND p.cierre_id IS NULL", [usuario_id])
    return liqs, pagos


def _dias_pendientes(conn, usuario_id):
    """Lo pendiente del recaudador por día de trabajo: {día: (liquidaciones, pagos)}.

    Regla general: el día en que se recibió la plata. Excepción, un cierre reabierto:
    todo lo que tenía vuelve JUNTO a su día, aunque se hubiera recibido en varios días
    (los cierres de antes del 2026-11-05 juntaban varios días), y la liquidación que
    reemplaza a una anulada de ese cierre (mismo bus, día de tarjeta y parte) también entra
    ahí mientras el día siga reabierto, aunque se haya liquidado hoy. Así el día se
    vuelve a cerrar completo, contra el efectivo que ya se había entregado."""
    liqs, pagos = _pendientes(conn, usuario_id)
    reabiertos = [dict(f) for f in conn.execute(
        """SELECT id, fecha, liquidacion_ids, pago_ids FROM recaudo_cierres
            WHERE usuario_id = ? AND reabierto_at IS NOT NULL ORDER BY id""",
        (usuario_id,),
    ).fetchall()]
    dia_liq, dia_pago = {}, {}
    if reabiertos:
        for c in reabiertos:   # de más viejo a más nuevo: manda el último cierre que lo tuvo
            dia = _fecha_iso(c["fecha"])
            for i in json.loads(c["liquidacion_ids"] or "[]"):
                dia_liq[i] = dia
            for i in json.loads(c["pago_ids"] or "[]"):
                dia_pago[i] = dia
        # Reabiertos que aún no se vuelven a cerrar: son el último cierre de su día
        ultimo = {_fecha_iso(dict(f)["fecha"]): dict(f)["id"] for f in conn.execute(
            "SELECT fecha, MAX(id) AS id FROM recaudo_cierres WHERE usuario_id = ? GROUP BY fecha",
            (usuario_id,),
        ).fetchall()}
        en_abiertos = {i: _fecha_iso(c["fecha"]) for c in reabiertos
                       if ultimo.get(_fecha_iso(c["fecha"])) == c["id"]
                       for i in json.loads(c["liquidacion_ids"] or "[]")}
        sueltas = [l for l in liqs if l["id"] not in dia_liq]
        if sueltas and en_abiertos:
            ids = list(en_abiertos)
            reemplazadas = {}
            for f in conn.execute(
                f"""SELECT id, bus_id, fecha, parte FROM recaudos
                     WHERE anulado_at IS NOT NULL AND id IN ({','.join('?' * len(ids))})""",
                ids,
            ).fetchall():
                f = dict(f)
                # La parte cuenta: un relevo agregado hoy no reemplaza a la liquidación original.
                reemplazadas[(f["bus_id"], _fecha_iso(f["fecha"]), f.get("parte") or 1)] = en_abiertos[f["id"]]
            for l in sueltas:
                dia = reemplazadas.get((l["bus_id"], l["fecha"], l.get("parte") or 1))
                if dia:
                    dia_liq[l["id"]] = dia
    dias = {}
    for l in liqs:
        dias.setdefault(dia_liq.get(l["id"], l["caja_fecha"]), ([], []))[0].append(l)
    for p in pagos:
        dias.setdefault(dia_pago.get(p["id"], p["fecha"]), ([], []))[1].append(p)
    return dict(sorted(dias.items()))


def _acumulado(conn, usuario_id, hasta_fecha):
    """Faltante (−) o sobrante (+) de caja arrastrado: suma de la diferencia de caja de
    los cierres vigentes (no reabiertos) del recaudador hasta ese día, inclusive."""
    fila = conn.execute(
        """SELECT COALESCE(SUM(diferencia_caja), 0) AS s FROM recaudo_cierres
            WHERE usuario_id = ? AND reabierto_at IS NULL AND fecha <= ?""",
        (usuario_id, hasta_fecha),
    ).fetchone()
    return int(dict(fila)["s"] or 0)


def _acumulados(conn, cierres):
    """{id: saldo acumulado del recaudador con ese cierre incluido} para los cierres vigentes."""
    usuarios = sorted({c["usuario_id"] for c in cierres if c.get("usuario_id") is not None})
    vigentes = [c for c in cierres if not c.get("reabierto_at")]
    if not usuarios or not vigentes:
        return {}
    hasta = max(c["fecha"] for c in vigentes if c.get("fecha"))
    filas = [dict(f) for f in conn.execute(
        f"""SELECT id, usuario_id, fecha, diferencia_caja FROM recaudo_cierres
             WHERE reabierto_at IS NULL AND fecha <= ? AND usuario_id IN ({','.join('?' * len(usuarios))})""",
        [hasta] + usuarios,
    ).fetchall()]
    saldo, acumulado = {}, {}
    for f in sorted(filas, key=lambda f: (f["usuario_id"], _fecha_iso(f["fecha"]) or "", f["id"])):
        saldo[f["usuario_id"]] = saldo.get(f["usuario_id"], 0) + int(f["diferencia_caja"] or 0)
        acumulado[f["id"]] = saldo[f["usuario_id"]]
    return acumulado


def _ultimo_cierre_del_dia(conn, usuario_id, fecha):
    fila = conn.execute(
        "SELECT * FROM recaudo_cierres WHERE usuario_id = ? AND fecha = ? ORDER BY id DESC LIMIT 1",
        (usuario_id, fecha),
    ).fetchone()
    return _fila_cierre(fila) if fila else None


def _dia_txt(fecha):
    try:
        return date.fromisoformat(fecha).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(fecha)


def _totales(liqs, pagos):
    suma = lambda k: sum(l[k] for l in liqs)   # noqa: E731
    t = {"liquidaciones": len(liqs), "pasajeros": suma("pasajeros"), "producido": suma("producido"),
         "total_gastos": suma("total_gastos"), "neto": suma("neto"), "recaudado": suma("recaudado"),
         "diferencia_conductores": suma("diferencia"), **totales_pagos(pagos)}
    t["esperado"] = t["recaudado"] + t["ingresos"] - t["egresos"]
    return t


def _nombre_usuario(conn, usuario_id):
    fila = conn.execute("SELECT nombre FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return dict(fila)["nombre"] if fila else None


def _fila_cierre(r):
    d = dict(r)
    d["fecha"] = _fecha_iso(d.get("fecha"))
    for k in ("cerrado_at", "desde_at", "hasta_at", "reabierto_at"):
        if k in d:
            d[k] = _hora_utc(d[k])
    for k in ("liquidacion_ids", "pago_ids"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    # Los cierres de antes de los pagos diarios (v20) quedan en 0.
    for k in ("pagos", "ingresos", "egresos"):
        d[k] = int(d.get(k) or 0)
    d["esperado"] = int(d.get("recaudado") or 0) + d["ingresos"] - d["egresos"]
    return d


def _n_liq(n):
    return f"{n} liquidación" if n == 1 else f"{n} liquidaciones"


def _n_pagos(n):
    return f"{n} pago diario" if n == 1 else f"{n} pagos diarios"


def _contenido(t):
    """'3 liquidaciones (recaudado $X) y 2 pagos diarios (entradas $Y, salidas $Z)'."""
    partes = []
    if t["liquidaciones"]:
        partes.append(f"{_n_liq(t['liquidaciones'])} (recaudado {auditoria.pesos(t['recaudado'])})")
    if t["pagos"]:
        partes.append(f"{_n_pagos(t['pagos'])} (entradas {auditoria.pesos(t['ingresos'])}, "
                      f"salidas {auditoria.pesos(t['egresos'])})")
    return " y ".join(partes) or "sin movimientos"


def _resultado_caja(dif):
    if dif < 0:
        return f"faltante de caja {auditoria.pesos(-dif)}"
    if dif > 0:
        return f"sobrante de caja {auditoria.pesos(dif)}"
    return "caja cuadrada"


# ──────────────────────────────────────────
#  Caja abierta
# ──────────────────────────────────────────

@bp.route("/api/recaudo/caja", methods=["GET"])
@rol(*ROLES_RECAUDO)
def caja_abierta():
    """Caja abierta (la propia o, para el Administrador, la de ?usuario_id=), separada por
    día de trabajo en `dias` (cada uno con sus totales, el saldo arrastrado hasta ese día y,
    si es un día reabierto, el cierre anterior). Al Administrador también le llega el
    resumen de las cajas abiertas de todos."""
    try:
        usuario_id = _usuario_objetivo()
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    conn = db()
    por_dia = _dias_pendientes(conn, usuario_id)
    liqs = [l for ls, _ in por_dia.values() for l in ls]
    pagos = [p for _, ps in por_dia.values() for p in ps]
    dias = []
    for fecha, (ls, ps) in por_dia.items():
        ultimo = _ultimo_cierre_del_dia(conn, usuario_id, fecha)
        reabierto = None
        if ultimo and ultimo["reabierto_at"]:
            reabierto = {k: ultimo.get(k) for k in ("id", "efectivo", "planilla", "observacion",
                                                    "motivo_reapertura", "reabierto_at")}
        dias.append({"fecha": fecha, "liquidaciones": ls, "pagos": ps, "totales": _totales(ls, ps),
                     "reabierto": reabierto,
                     # Ya tiene un cierre vigente: lo que llegó después va en un segundo cierre
                     "cerrado_antes": bool(ultimo and not ultimo["reabierto_at"]),
                     "acumulado_antes": _acumulado(conn, usuario_id, fecha)})
    salida = {"usuario": {"id": usuario_id, "nombre": _nombre_usuario(conn, usuario_id)},
              "liquidaciones": liqs, "pagos": pagos, "totales": _totales(liqs, pagos),
              "dias": dias, "acumulado": _acumulado(conn, usuario_id, "9999-12-31")}
    if _es_admin():
        # Cajas abiertas de todos: liquidaciones y pagos diarios sin cierre, por usuario.
        cajas = {}
        for f in conn.execute(
            """SELECT r.usuario_id, u.nombre, u.rol, COUNT(*) AS liquidaciones, SUM(r.recaudado) AS recaudado
                 FROM recaudos r LEFT JOIN usuarios u ON u.id = r.usuario_id
                WHERE r.anulado_at IS NULL AND r.cierre_id IS NULL
             GROUP BY r.usuario_id, u.nombre, u.rol"""
        ).fetchall():
            f = dict(f)
            cajas[f["usuario_id"]] = {**f, "recaudado": int(f["recaudado"] or 0)}
        for f in conn.execute(
            """SELECT p.usuario_id, u.nombre, u.rol, COUNT(*) AS pagos,
                      SUM(CASE WHEN p.signo = 2 THEN p.valor ELSE 0 END) AS ingresos,
                      SUM(CASE WHEN p.signo = 1 THEN p.valor ELSE 0 END) AS egresos
                 FROM recaudo_pagos p LEFT JOIN usuarios u ON u.id = p.usuario_id
                WHERE p.anulado_at IS NULL AND p.cierre_id IS NULL
             GROUP BY p.usuario_id, u.nombre, u.rol"""
        ).fetchall():
            f = dict(f)
            caja = cajas.setdefault(f["usuario_id"], {"usuario_id": f["usuario_id"], "nombre": f["nombre"],
                                                     "rol": f["rol"], "liquidaciones": 0, "recaudado": 0})
            caja.update(pagos=int(f["pagos"] or 0), ingresos=int(f["ingresos"] or 0), egresos=int(f["egresos"] or 0))
        # Cuántos días de trabajo tiene sin cerrar cada uno y cuántos son reabiertos
        # (el administrador los ve marcados para volver a cerrarlos)
        for caja in cajas.values():
            for k in ("pagos", "ingresos", "egresos"):
                caja.setdefault(k, 0)
            caja["esperado"] = caja["recaudado"] + caja["ingresos"] - caja["egresos"]
            dias_caja = list(_dias_pendientes(conn, caja["usuario_id"])) if caja["usuario_id"] else []
            caja["dias"] = len(dias_caja)
            caja["reabiertos"] = 0
            for d in dias_caja:
                ultimo = _ultimo_cierre_del_dia(conn, caja["usuario_id"], d)
                if ultimo and ultimo["reabierto_at"]:
                    caja["reabiertos"] += 1
        salida["cajas_abiertas"] = sorted(cajas.values(), key=lambda c: (c["nombre"] or "").lower())
    conn.close()
    return jsonify(salida)


@bp.route("/api/recaudo/caja/cerrar", methods=["POST"])
@rol(*ROLES_RECAUDO)
def cerrar_caja():
    """Cierra UN día de trabajo. Body: {fecha (día a cerrar; si solo hay uno pendiente
    puede omitirse), efectivo, planilla?, observacion?, usuario_id? (solo Administrador),
    esperado? (lo que la pantalla mostró: si entró un movimiento nuevo, 409)}."""
    data = request.get_json(silent=True) or {}
    try:
        usuario_id = _usuario_objetivo()
        efectivo = _entero(data.get("efectivo"), "El efectivo entregado")
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    planilla = _texto(data.get("planilla"), 80)
    observacion = _texto(data.get("observacion"), 500)

    conn = db()
    por_dia = _dias_pendientes(conn, usuario_id)
    if not por_dia:
        conn.close()
        return jsonify({"error": "No hay liquidaciones ni pagos pendientes por cerrar en esta caja"}), 400
    fecha = data.get("fecha")
    if not fecha:
        if len(por_dia) > 1:
            conn.close()
            return jsonify({"error": "Hay varios días por cerrar: elige cuál vas a cerrar."}), 400
        fecha = next(iter(por_dia))
    if not isinstance(fecha, str) or not _RE_FECHA.match(fecha) or fecha not in por_dia:
        conn.close()
        return jsonify({"error": "Ese día no tiene liquidaciones ni pagos pendientes por cerrar"}), 400
    liqs, pagos = por_dia[fecha]
    reabierto = _ultimo_cierre_del_dia(conn, usuario_id, fecha)
    reabierto = reabierto if reabierto and reabierto["reabierto_at"] else None
    t = _totales(liqs, pagos)
    esperado_pantalla = data.get("esperado")
    if esperado_pantalla is not None and str(esperado_pantalla).lstrip("-").isdigit() \
            and int(esperado_pantalla) != t["esperado"]:
        conn.close()
        return jsonify({"error": "La caja cambió mientras tanto (entró o se anuló un movimiento). "
                                 "Revisa de nuevo antes de cerrar."}), 409
    ids = [l["id"] for l in liqs]
    pago_ids = [p["id"] for p in pagos]
    creados = sorted(x["created_at"] for x in liqs + pagos if x.get("created_at"))
    nombre = _nombre_usuario(conn, usuario_id)
    yo = getattr(request, "jwt_user_id", None)
    diferencia_caja = efectivo - t["esperado"]
    a_bd = lambda iso: (datetime.fromisoformat(iso.replace("Z", "+00:00")) if es_pg() else iso) if iso else None  # noqa: E731

    valores = (yo, _ahora(), a_bd(creados[0] if creados else None), a_bd(creados[-1] if creados else None),
               t["liquidaciones"], t["pasajeros"], t["producido"], t["total_gastos"], t["neto"],
               t["recaudado"], t["diferencia_conductores"], efectivo, diferencia_caja, planilla,
               observacion, json.dumps(ids), t["pagos"], t["ingresos"], t["egresos"], json.dumps(pago_ids))
    try:
        if reabierto:
            # Es la MISMA caja: se vuelve a cerrar con su número (pedido del usuario 2026-11-05).
            # Lo que tenía antes queda en el historial de modificaciones (al reabrir y aquí);
            # `motivo_reapertura` y `reabierto_por` quedan como nota de la última corrección.
            cierre_id = reabierto["id"]
            conn.execute(
                """UPDATE recaudo_cierres
                      SET cerrado_por = ?, cerrado_at = ?, desde_at = ?, hasta_at = ?, liquidaciones = ?,
                          pasajeros = ?, producido = ?, total_gastos = ?, neto = ?, recaudado = ?,
                          diferencia_conductores = ?, efectivo = ?, diferencia_caja = ?, planilla = ?,
                          observacion = ?, liquidacion_ids = ?, pagos = ?, ingresos = ?, egresos = ?,
                          pago_ids = ?, reabierto_at = NULL
                    WHERE id = ?""",
                valores + (cierre_id,),
            )
        else:
            cur = conn.execute(
                """INSERT INTO recaudo_cierres
                       (empresa_id, usuario_id, usuario_nombre, cerrado_por, cerrado_at, desde_at, hasta_at,
                        liquidaciones, pasajeros, producido, total_gastos, neto, recaudado,
                        diferencia_conductores, efectivo, diferencia_caja, planilla, observacion, liquidacion_ids,
                        pagos, ingresos, egresos, pago_ids, fecha)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (EMPRESA_POR_DEFECTO, usuario_id, nombre) + valores + (fecha,),
            )
            cierre_id = cur.lastrowid
        if ids:
            marcas = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE recaudos SET cierre_id = ?, caja_fecha = ? WHERE id IN ({marcas}) AND cierre_id IS NULL",
                [cierre_id, fecha] + ids,
            )
        if pago_ids:
            marcas = ",".join("?" * len(pago_ids))
            conn.execute(
                f"""UPDATE recaudo_pagos SET cierre_id = ?
                     WHERE id IN ({marcas}) AND cierre_id IS NULL AND anulado_at IS NULL""",
                [cierre_id] + pago_ids,
            )
        por_otro = " (cerrada por el administrador)" if yo != usuario_id else ""
        antes = (f" (antes: debe haber {auditoria.pesos(reabierto['esperado'])}, efectivo "
                 f"{auditoria.pesos(reabierto['efectivo'])}, {_resultado_caja(reabierto['diferencia_caja'])})"
                 if reabierto else "")
        auditoria.registrar(
            conn, "recaudo", "cierre", cierre_id, "cerrar",
            (f"{'Volvió a cerrar' if reabierto else 'Cerró'} la caja N° {cierre_id} del día {_dia_txt(fecha)} de "
             f"{nombre or 'usuario #' + str(usuario_id)}{por_otro}{antes}: "
             f"{_contenido(t)}; debe haber {auditoria.pesos(t['esperado'])}, "
             f"efectivo entregado {auditoria.pesos(efectivo)}, {_resultado_caja(diferencia_caja)}."
             + (f" Planilla/precinto: {planilla}." if planilla else "")),
            {"fecha": fecha, "liquidaciones": t["liquidaciones"], "recaudado": t["recaudado"],
             "pagos": t["pagos"], "ingresos": t["ingresos"], "egresos": t["egresos"],
             "esperado": t["esperado"], "efectivo": efectivo, "diferencia_caja": diferencia_caja,
             "planilla": planilla, "observacion": observacion,
             "vuelve_a_cerrar": bool(reabierto),
             "antes": ({k: reabierto[k] for k in ("liquidaciones", "recaudado", "esperado", "efectivo",
                                                   "diferencia_caja", "planilla")} if reabierto else None)},
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[recaudo.cerrar_caja] {e}")
        return jsonify({"error": "No se pudo cerrar la caja"}), 500

    cierre = _fila_cierre(conn.execute("SELECT * FROM recaudo_cierres WHERE id = ?", (cierre_id,)).fetchone())
    cierre["liquidaciones_detalle"] = liqs
    cierre["pagos_detalle"] = pagos
    cierre["acumulado"] = _acumulado(conn, usuario_id, fecha)
    conn.close()
    return jsonify({"ok": True, "cierre": cierre}), 201


# ──────────────────────────────────────────
#  Corrección única: cajas re-cerradas con otro número
# ──────────────────────────────────────────

_SISTEMA = {"id": None, "nombre": "Sistema", "username": "sistema", "rol": "Sistema"}
_COPIAR = ("cerrado_por", "cerrado_at", "desde_at", "hasta_at", "liquidaciones", "pasajeros", "producido",
           "total_gastos", "neto", "recaudado", "diferencia_conductores", "efectivo", "diferencia_caja",
           "planilla", "observacion", "liquidacion_ids", "pagos", "ingresos", "egresos", "pago_ids")


def unir_recierres(conn):
    """Antes del 2026-11-05 (PR #173), volver a cerrar una caja reabierta creaba otra con
    número nuevo (p. ej. la N° 000002 de Ximena reabierta y la N° 000003 que la volvió a
    cerrar). Ahora es la misma caja: esta corrección une cada par así — la reabierta y el
    cierre posterior del mismo recaudador y día que tiene sus liquidaciones o pagos —
    dejando el número original con los valores del cierre más reciente, y borra el otro.
    Queda en el historial. Idempotente: si no hay pares, no hace nada. Devuelve cuántas unió."""
    unidas = 0
    while True:
        par = None
        for r in conn.execute(
            "SELECT * FROM recaudo_cierres WHERE reabierto_at IS NOT NULL ORDER BY id"
        ).fetchall():
            r = dict(r)
            ids_r = set(json.loads(r["liquidacion_ids"] or "[]"))
            pagos_r = set(json.loads(r["pago_ids"] or "[]"))
            for n in conn.execute(
                "SELECT * FROM recaudo_cierres WHERE usuario_id = ? AND fecha = ? AND id > ? ORDER BY id",
                (r["usuario_id"], r["fecha"], r["id"]),
            ).fetchall():
                n = dict(n)
                if ids_r & set(json.loads(n["liquidacion_ids"] or "[]")) or \
                        pagos_r & set(json.loads(n["pago_ids"] or "[]")):
                    par = (r, n)
                    break
            if par:
                break
        if not par:
            return unidas
        r, n = par
        # Si el posterior también se reabrió, la caja queda reabierta; si no, cerrada
        # (con el motivo de la última reapertura como nota).
        reab = n["reabierto_at"] is not None
        conn.execute(
            f"""UPDATE recaudo_cierres SET {', '.join(k + ' = ?' for k in _COPIAR)},
                       reabierto_at = ?, reabierto_por = ?, motivo_reapertura = ?
                 WHERE id = ?""",
            [n[k] for k in _COPIAR] + [n["reabierto_at"],
                                       n["reabierto_por"] if reab else r["reabierto_por"],
                                       n["motivo_reapertura"] if reab else r["motivo_reapertura"], r["id"]],
        )
        conn.execute("UPDATE recaudos SET cierre_id = ? WHERE cierre_id = ?", (r["id"], n["id"]))
        conn.execute("UPDATE recaudo_pagos SET cierre_id = ? WHERE cierre_id = ?", (r["id"], n["id"]))
        conn.execute("DELETE FROM recaudo_cierres WHERE id = ?", (n["id"],))
        pr, pn = _fila_cierre(r), _fila_cierre(n)
        auditoria.registrar(
            conn, "recaudo", "cierre", r["id"], "editar",
            (f"Unió la caja N° {n['id']} con la N° {r['id']} del día {_dia_txt(pr['fecha'])} de "
             f"{r['usuario_nombre'] or 'usuario #' + str(r['usuario_id'])}: era la misma caja reabierta y "
             f"vuelta a cerrar antes de que conservara su número. La N° {r['id']} queda con lo del último "
             f"cierre: {_contenido(pn)}; debe haber {auditoria.pesos(pn['esperado'])}, efectivo "
             f"{auditoria.pesos(pn['efectivo'])}, {_resultado_caja(pn['diferencia_caja'])}. Antes tenía: debe haber "
             f"{auditoria.pesos(pr['esperado'])}, efectivo {auditoria.pesos(pr['efectivo'])}."),
            {"caja": r["id"], "caja_borrada": n["id"], "fecha": pr["fecha"],
             "antes": {k: pr[k] for k in ("liquidaciones", "recaudado", "esperado", "efectivo", "diferencia_caja", "planilla")},
             "despues": {k: pn[k] for k in ("liquidaciones", "recaudado", "esperado", "efectivo", "diferencia_caja", "planilla")}},
            usuario=_SISTEMA,
        )
        unidas += 1


# ──────────────────────────────────────────
#  Cierres anteriores
# ──────────────────────────────────────────


@bp.route("/api/recaudo/cierres", methods=["GET"])
@rol(*ROLES_RECAUDO)
def listar_cierres():
    """?desde=&hasta= (DÍA DE TRABAJO del cierre, no el día en que se cerró; por defecto
    los últimos 30 días) [&usuario_id= solo Administrador]. El Recaudador solo ve los
    suyos. Cada cierre vigente trae `acumulado`: el saldo arrastrado con él incluido."""
    a = request.args
    hoy = (datetime.now(timezone.utc) - _BOGOTA).date()
    desde = a.get("desde") or (hoy - timedelta(days=30)).isoformat()
    hasta = a.get("hasta") or hoy.isoformat()
    if not _RE_FECHA.match(desde) or not _RE_FECHA.match(hasta):
        return jsonify({"error": "Fechas inválidas (use AAAA-MM-DD)"}), 400
    where, params = ["fecha >= ?", "fecha <= ?"], [desde, hasta]
    if not _es_admin():
        where.append("usuario_id = ?")
        params.append(getattr(request, "jwt_user_id", None))
    elif a.get("usuario_id"):
        where.append("usuario_id = ?")
        params.append(int(a["usuario_id"]) if a["usuario_id"].isdigit() else 0)
    conn = db()
    filas = conn.execute(
        f"""SELECT c.*, ur.nombre AS reabierto_por_nombre, uc.nombre AS cerrado_por_nombre
              FROM recaudo_cierres c
         LEFT JOIN usuarios ur ON ur.id = c.reabierto_por
         LEFT JOIN usuarios uc ON uc.id = c.cerrado_por
             WHERE {' AND '.join(where)}
          ORDER BY c.fecha DESC, c.id DESC""",
        params,
    ).fetchall()
    cierres = [_fila_cierre(f) for f in filas]
    acumulados = _acumulados(conn, cierres)
    # Un reabierto está "por cerrar" mientras siga siendo el último cierre de su día
    ultimos = {}
    usuarios = sorted({c["usuario_id"] for c in cierres if c["reabierto_at"] and c.get("usuario_id") is not None})
    if usuarios:
        for f in conn.execute(
            f"""SELECT usuario_id, fecha, MAX(id) AS id FROM recaudo_cierres
                 WHERE usuario_id IN ({','.join('?' * len(usuarios))}) GROUP BY usuario_id, fecha""",
            usuarios,
        ).fetchall():
            f = dict(f)
            ultimos[(f["usuario_id"], _fecha_iso(f["fecha"]))] = f["id"]
    for c in cierres:
        c["acumulado"] = acumulados.get(c["id"])   # None en los reabiertos: no cuentan
        c["por_cerrar"] = bool(c["reabierto_at"]) and ultimos.get((c["usuario_id"], c["fecha"])) == c["id"]
    conn.close()
    return jsonify({"desde": desde, "hasta": hasta, "cierres": cierres})


@bp.route("/api/recaudo/cierres/<int:cierre_id>", methods=["GET"])
@rol(*ROLES_RECAUDO)
def ver_cierre(cierre_id):
    """Un cierre con sus liquidaciones y pagos (para el PDF/Excel), aunque después lo hayan reabierto."""
    conn = db()
    fila = conn.execute(
        """SELECT c.*, ur.nombre AS reabierto_por_nombre, uc.nombre AS cerrado_por_nombre
             FROM recaudo_cierres c
        LEFT JOIN usuarios ur ON ur.id = c.reabierto_por
        LEFT JOIN usuarios uc ON uc.id = c.cerrado_por
            WHERE c.id = ?""",
        (cierre_id,),
    ).fetchone()
    if not fila:
        conn.close()
        return jsonify({"error": "Cierre no encontrado"}), 404
    cierre = _fila_cierre(fila)
    if not _es_admin() and cierre["usuario_id"] != getattr(request, "jwt_user_id", None):
        conn.close()
        return jsonify({"error": "No autorizado para ver este cierre"}), 403
    cierre["acumulado"] = _acumulados(conn, [cierre]).get(cierre["id"])
    ids = cierre["liquidacion_ids"]
    cierre["liquidaciones_detalle"] = (
        _cargar(conn, f"r.id IN ({','.join('?' * len(ids))})", ids) if ids else [])
    pids = cierre["pago_ids"]
    cierre["pagos_detalle"] = (
        cargar_pagos(conn, f"p.id IN ({','.join('?' * len(pids))})", pids) if pids else [])
    conn.close()
    return jsonify(cierre)


@bp.route("/api/recaudo/cierres/<int:cierre_id>/reabrir", methods=["POST"])
@rol(*ADMIN)
def reabrir_cierre(cierre_id):
    """Solo Administrador, con motivo. El cierre queda como historial y sus
    liquidaciones y pagos vuelven a la caja abierta del recaudador, en su mismo día de
    trabajo: ahí se pueden anular, corregir y volver a cerrar ese día."""
    motivo = _texto((request.get_json(silent=True) or {}).get("motivo"), 500)
    if not motivo or len(motivo) < 5:
        return jsonify({"error": "Escribe el motivo de la reapertura (mínimo 5 caracteres)"}), 400
    conn = db()
    fila = conn.execute("SELECT * FROM recaudo_cierres WHERE id = ?", (cierre_id,)).fetchone()
    if not fila:
        conn.close()
        return jsonify({"error": "Cierre no encontrado"}), 404
    c = _fila_cierre(fila)
    if c["reabierto_at"]:
        conn.close()
        return jsonify({"error": "Este cierre ya estaba reabierto"}), 409
    conn.execute(
        "UPDATE recaudo_cierres SET reabierto_at = ?, reabierto_por = ?, motivo_reapertura = ? WHERE id = ?",
        (_ahora(), getattr(request, "jwt_user_id", None), motivo, cierre_id),
    )
    conn.execute("UPDATE recaudos SET cierre_id = NULL WHERE cierre_id = ?", (cierre_id,))
    conn.execute("UPDATE recaudo_pagos SET cierre_id = NULL WHERE cierre_id = ?", (cierre_id,))
    auditoria.registrar(
        conn, "recaudo", "cierre", cierre_id, "reabrir",
        (f"Reabrió la caja N° {cierre_id} del día {_dia_txt(c['fecha'])} de "
         f"{c['usuario_nombre'] or 'usuario #' + str(c['usuario_id'])} "
         f"({_contenido(c)}; debe haber {auditoria.pesos(c['esperado'])}, "
         f"efectivo {auditoria.pesos(c['efectivo'])}). Motivo: {motivo}"),
        {"liquidaciones": c["liquidaciones"], "recaudado": c["recaudado"], "pagos": c["pagos"],
         "ingresos": c["ingresos"], "egresos": c["egresos"], "efectivo": c["efectivo"], "motivo": motivo},
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
