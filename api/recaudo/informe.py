"""Informe de recaudo por vehículo (el Excel lo arma recaudo-diario.html).

- Una fila por conductor de cada liquidación vigente: con relevo, el bus sale en
  varias filas (cada una con sus viajes, registradora, pasajeros y gastos).
- Dos fechas:
    fecha de la tarjeta = el día que trabajó el bus (`recaudos.fecha`, el que se
                          elige arriba en Recaudo diario);
    fecha de recaudo    = cuando se liquidó (`recaudos.created_at`, hora Bogotá),
                          es decir, cuando el conductor entregó la plata.
  El rango se busca por cualquiera de las dos (?por=tarjeta|recaudo).
- Los gastos se agrupan por tipo con su nombre actual (renombrar un tipo no parte
  la columna en dos); solo salen los tipos que tuvieron valor en el periodo.
"""
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

from . import bp
from .comun import EMPRESA_POR_DEFECTO, db, es_pg, rol
from .endpoints import _entero, _fecha_iso, _fecha_valida, _hora_utc, _Rechazo

ADMIN = ("Administrador",)
MAX_DIAS = 366
_BOGOTA = timedelta(hours=5)   # Colombia es UTC-5 todo el año


def _limite(fecha_iso, dias_extra=0):
    """Medianoche Bogotá del día → UTC, en el formato con el que se compara en cada motor
    (en SQLite created_at es texto 'AAAA-MM-DD HH:MM:SS' y se normaliza con datetime())."""
    d = date.fromisoformat(fecha_iso) + timedelta(days=dias_extra)
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + _BOGOTA
    return dt if es_pg() else dt.strftime("%Y-%m-%d %H:%M:%S")


def _orden_bus(numero):
    """Orden natural del número del bus: 2 antes que 10."""
    s = str(numero or "")
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


@bp.route("/api/recaudo/informe", methods=["GET"])
@rol(*ADMIN)
def informe():
    """?desde=&hasta= (AAAA-MM-DD) &por=tarjeta|recaudo [&bus_id=]."""
    a = request.args
    desde, hasta = _fecha_valida(a.get("desde")), _fecha_valida(a.get("hasta"))
    por = a.get("por") or "tarjeta"
    if not desde or not hasta or desde > hasta:
        return jsonify({"error": "Rango de fechas inválido (use AAAA-MM-DD)"}), 400
    if por not in ("tarjeta", "recaudo"):
        return jsonify({"error": "Elija si busca por fecha de la tarjeta o de recaudo"}), 400
    if (date.fromisoformat(hasta) - date.fromisoformat(desde)).days >= MAX_DIAS:
        return jsonify({"error": f"El informe abarca máximo {MAX_DIAS} días"}), 400
    bus_id = None
    if a.get("bus_id"):
        try:
            bus_id = _entero(a.get("bus_id"), "El vehículo")
        except _Rechazo as e:
            return jsonify({"error": str(e)}), e.status

    if por == "tarjeta":
        where, params = "r.fecha BETWEEN ? AND ?", [desde, hasta]
    else:
        creado = "r.created_at" if es_pg() else "datetime(r.created_at)"
        where, params = f"{creado} >= ? AND {creado} < ?", [_limite(desde), _limite(hasta, 1)]
    where += " AND r.anulado_at IS NULL"
    if bus_id:
        where += " AND r.bus_id = ?"
        params.append(bus_id)

    conn = db()
    filas = [dict(f) for f in conn.execute(
        f"""SELECT r.id AS recaudo_id, r.fecha, r.created_at, r.bus_id, r.tarifa,
                   b.numero AS bus_numero, b.placa AS bus_placa, b.grupo AS bus_grupo,
                   u.nombre AS usuario_nombre,
                   rc.orden, rc.viajes, rc.registradora_inicio, rc.registradora_fin, rc.pasajeros,
                   rc.producido, rc.total_gastos, rc.neto, rc.recaudado, rc.diferencia,
                   c.nombre AS conductor_nombre, c.cedula AS conductor_cedula,
                   ru.nombre AS ruta_nombre
              FROM recaudos r
              JOIN recaudo_conductores rc ON rc.recaudo_id = r.id
              JOIN buses b ON b.id = r.bus_id
         LEFT JOIN usuarios u ON u.id = r.usuario_id
         LEFT JOIN conductores c ON c.id = rc.conductor_id
         LEFT JOIN rutas ru ON ru.id = rc.ruta_id
             WHERE {where}""",
        params,
    ).fetchall()]
    gastos = [dict(g) for g in conn.execute(
        f"""SELECT g.recaudo_id, g.orden_conductor, g.tipo_gasto_id, g.tipo_nombre, g.valor, g.observacion
              FROM recaudo_gastos g
              JOIN recaudos r ON r.id = g.recaudo_id
             WHERE {where}
          ORDER BY g.recaudo_id, g.orden_conductor, g.id""",
        params,
    ).fetchall()]
    tipos = [dict(t) for t in conn.execute(
        "SELECT id, nombre FROM recaudo_tipos_gasto WHERE empresa_id = ? ORDER BY orden, nombre",
        (EMPRESA_POR_DEFECTO,),
    ).fetchall()]
    bus = None
    if bus_id:
        fila = conn.execute("SELECT numero FROM buses WHERE id = ?", (bus_id,)).fetchone()
        bus = str(dict(fila)["numero"]) if fila else None
    conn.close()

    nombre_tipo = {t["id"]: t["nombre"] for t in tipos}
    por_conductor, usados = {}, set()
    for g in gastos:
        tipo = nombre_tipo.get(g["tipo_gasto_id"], g["tipo_nombre"])
        usados.add(tipo)
        por_conductor.setdefault((g["recaudo_id"], g["orden_conductor"]), []).append(
            {"tipo": tipo, "valor": int(g["valor"]), "observacion": g["observacion"]})

    conductores = {}
    for f in filas:
        conductores[f["recaudo_id"]] = conductores.get(f["recaudo_id"], 0) + 1
    for f in filas:
        f["fecha"] = _fecha_iso(f["fecha"])
        f["created_at"] = _hora_utc(f["created_at"])
        f["bus_numero"] = str(f["bus_numero"])
        f["conductores"] = conductores[f["recaudo_id"]]
        f["gastos"] = por_conductor.get((f["recaudo_id"], f["orden"]), [])
    filas.sort(key=lambda f: (_orden_bus(f["bus_numero"]), f["fecha"], f["created_at"] or "",
                              f["recaudo_id"], f["orden"]))

    orden_tipos = [t["nombre"] for t in tipos if t["nombre"] in usados]
    orden_tipos += sorted(usados - set(orden_tipos))
    return jsonify({"desde": desde, "hasta": hasta, "por": por, "bus": bus,
                    "tipos_gasto": orden_tipos, "filas": filas})
