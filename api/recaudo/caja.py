"""Cierre de caja POR RECAUDADOR.

- La "caja abierta" de un recaudador son sus liquidaciones vigentes sin cierre: todo
  lo que ha recibido desde su último cierre, sin importar el día de operación (a las
  6 a. m. puede estar liquidando buses del día anterior).
- No hay consignaciones ni conteo de billetes: el recaudador escribe el efectivo que
  entrega a la transportadora de valores y el sistema calcula la diferencia de caja
  (efectivo − recaudado).
- Al cerrar, esas liquidaciones quedan bloqueadas: no se pueden anular. Solo el
  Administrador reabre un cierre (con motivo); el cierre queda como historial y sus
  liquidaciones vuelven a la caja abierta del recaudador.
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
from .endpoints import _ahora, _cargar, _entero, _hora_utc, _Rechazo, _texto

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
    """Liquidaciones vigentes del recaudador que todavía no entran en un cierre."""
    return _cargar(conn, "r.usuario_id = ? AND r.anulado_at IS NULL AND r.cierre_id IS NULL", [usuario_id])


def _totales(liqs):
    suma = lambda k: sum(l[k] for l in liqs)   # noqa: E731
    return {"liquidaciones": len(liqs), "pasajeros": suma("pasajeros"), "producido": suma("producido"),
            "total_gastos": suma("total_gastos"), "neto": suma("neto"), "recaudado": suma("recaudado"),
            "diferencia_conductores": suma("diferencia")}


def _nombre_usuario(conn, usuario_id):
    fila = conn.execute("SELECT nombre FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return dict(fila)["nombre"] if fila else None


def _fila_cierre(r):
    d = dict(r)
    for k in ("cerrado_at", "desde_at", "hasta_at", "reabierto_at"):
        if k in d:
            d[k] = _hora_utc(d[k])
    try:
        d["liquidacion_ids"] = json.loads(d.get("liquidacion_ids") or "[]")
    except ValueError:
        d["liquidacion_ids"] = []
    return d


def _n_liq(n):
    return f"{n} liquidación" if n == 1 else f"{n} liquidaciones"


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
    """Caja abierta (la propia o, para el Administrador, la de ?usuario_id=). Al
    Administrador también le llega el resumen de las cajas abiertas de todos."""
    try:
        usuario_id = _usuario_objetivo()
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    conn = db()
    liqs = _pendientes(conn, usuario_id)
    salida = {"usuario": {"id": usuario_id, "nombre": _nombre_usuario(conn, usuario_id)},
              "liquidaciones": liqs, "totales": _totales(liqs)}
    if _es_admin():
        filas = conn.execute(
            """SELECT r.usuario_id, u.nombre, u.rol, COUNT(*) AS liquidaciones, SUM(r.recaudado) AS recaudado
                 FROM recaudos r LEFT JOIN usuarios u ON u.id = r.usuario_id
                WHERE r.anulado_at IS NULL AND r.cierre_id IS NULL
             GROUP BY r.usuario_id, u.nombre, u.rol
             ORDER BY u.nombre"""
        ).fetchall()
        salida["cajas_abiertas"] = [{**dict(f), "recaudado": int(dict(f)["recaudado"] or 0)} for f in filas]
    conn.close()
    return jsonify(salida)


@bp.route("/api/recaudo/caja/cerrar", methods=["POST"])
@rol(*ROLES_RECAUDO)
def cerrar_caja():
    """Body: {efectivo, planilla?, observacion?, usuario_id? (solo Administrador)}."""
    data = request.get_json(silent=True) or {}
    try:
        usuario_id = _usuario_objetivo()
        efectivo = _entero(data.get("efectivo"), "El efectivo entregado")
    except _Rechazo as e:
        return jsonify({"error": str(e)}), e.status
    planilla = _texto(data.get("planilla"), 80)
    observacion = _texto(data.get("observacion"), 500)

    conn = db()
    liqs = _pendientes(conn, usuario_id)
    if not liqs:
        conn.close()
        return jsonify({"error": "No hay liquidaciones pendientes por cerrar en esta caja"}), 400
    t = _totales(liqs)
    ids = [l["id"] for l in liqs]
    creados = sorted(l["created_at"] for l in liqs if l.get("created_at"))
    nombre = _nombre_usuario(conn, usuario_id)
    yo = getattr(request, "jwt_user_id", None)
    diferencia_caja = efectivo - t["recaudado"]
    a_bd = lambda iso: (datetime.fromisoformat(iso.replace("Z", "+00:00")) if es_pg() else iso) if iso else None  # noqa: E731

    try:
        cur = conn.execute(
            """INSERT INTO recaudo_cierres
                   (empresa_id, usuario_id, usuario_nombre, cerrado_por, cerrado_at, desde_at, hasta_at,
                    liquidaciones, pasajeros, producido, total_gastos, neto, recaudado,
                    diferencia_conductores, efectivo, diferencia_caja, planilla, observacion, liquidacion_ids)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (EMPRESA_POR_DEFECTO, usuario_id, nombre, yo, _ahora(),
             a_bd(creados[0] if creados else None), a_bd(creados[-1] if creados else None),
             t["liquidaciones"], t["pasajeros"], t["producido"], t["total_gastos"], t["neto"],
             t["recaudado"], t["diferencia_conductores"], efectivo, diferencia_caja, planilla,
             observacion, json.dumps(ids)),
        )
        cierre_id = cur.lastrowid
        marcas = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE recaudos SET cierre_id = ? WHERE id IN ({marcas}) AND cierre_id IS NULL",
            [cierre_id] + ids,
        )
        por_otro = " (cerrada por el administrador)" if yo != usuario_id else ""
        auditoria.registrar(
            conn, "recaudo", "cierre", cierre_id, "cerrar",
            (f"Cerró la caja N° {cierre_id} de {nombre or 'usuario #' + str(usuario_id)}{por_otro}: "
             f"{_n_liq(t['liquidaciones'])}, recaudado {auditoria.pesos(t['recaudado'])}, "
             f"efectivo entregado {auditoria.pesos(efectivo)}, {_resultado_caja(diferencia_caja)}."
             + (f" Planilla/precinto: {planilla}." if planilla else "")),
            {"liquidaciones": t["liquidaciones"], "recaudado": t["recaudado"], "efectivo": efectivo,
             "diferencia_caja": diferencia_caja, "planilla": planilla, "observacion": observacion},
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[recaudo.cerrar_caja] {e}")
        return jsonify({"error": "No se pudo cerrar la caja"}), 500

    cierre = _fila_cierre(conn.execute("SELECT * FROM recaudo_cierres WHERE id = ?", (cierre_id,)).fetchone())
    cierre["liquidaciones_detalle"] = liqs
    conn.close()
    return jsonify({"ok": True, "cierre": cierre}), 201


# ──────────────────────────────────────────
#  Cierres anteriores
# ──────────────────────────────────────────

def _limite_utc(fecha_iso, dias_extra=0):
    d = date.fromisoformat(fecha_iso) + timedelta(days=dias_extra)
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + _BOGOTA
    return dt if es_pg() else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.route("/api/recaudo/cierres", methods=["GET"])
@rol(*ROLES_RECAUDO)
def listar_cierres():
    """?desde=&hasta= (fechas Bogotá del cierre, por defecto los últimos 30 días)
    [&usuario_id= solo Administrador]. El Recaudador solo ve los suyos."""
    a = request.args
    hoy = (datetime.now(timezone.utc) - _BOGOTA).date()
    desde = a.get("desde") or (hoy - timedelta(days=30)).isoformat()
    hasta = a.get("hasta") or hoy.isoformat()
    if not _RE_FECHA.match(desde) or not _RE_FECHA.match(hasta):
        return jsonify({"error": "Fechas inválidas (use AAAA-MM-DD)"}), 400
    where, params = ["cerrado_at >= ?", "cerrado_at < ?"], [_limite_utc(desde), _limite_utc(hasta, 1)]
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
          ORDER BY c.id DESC""",
        params,
    ).fetchall()
    conn.close()
    return jsonify({"desde": desde, "hasta": hasta, "cierres": [_fila_cierre(f) for f in filas]})


@bp.route("/api/recaudo/cierres/<int:cierre_id>", methods=["GET"])
@rol(*ROLES_RECAUDO)
def ver_cierre(cierre_id):
    """Un cierre con sus liquidaciones (para el PDF/Excel), aunque después lo hayan reabierto."""
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
    ids = cierre["liquidacion_ids"]
    cierre["liquidaciones_detalle"] = (
        _cargar(conn, f"r.id IN ({','.join('?' * len(ids))})", ids) if ids else [])
    conn.close()
    return jsonify(cierre)


@bp.route("/api/recaudo/cierres/<int:cierre_id>/reabrir", methods=["POST"])
@rol(*ADMIN)
def reabrir_cierre(cierre_id):
    """Solo Administrador, con motivo. El cierre queda como historial y sus
    liquidaciones vuelven a la caja abierta del recaudador (se pueden anular)."""
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
    auditoria.registrar(
        conn, "recaudo", "cierre", cierre_id, "reabrir",
        (f"Reabrió la caja N° {cierre_id} de {c['usuario_nombre'] or 'usuario #' + str(c['usuario_id'])} "
         f"({_n_liq(c['liquidaciones'])}, recaudado {auditoria.pesos(c['recaudado'])}, "
         f"efectivo {auditoria.pesos(c['efectivo'])}). Motivo: {motivo}"),
        {"liquidaciones": c["liquidaciones"], "recaudado": c["recaudado"], "efectivo": c["efectivo"],
         "motivo": motivo},
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
