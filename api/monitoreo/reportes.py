"""Reportes de recorrido: pasos por puntos de control (vueltas), excesos de
velocidad y abandonos de ruta.

Se calculan al consultar, sobre el histórico de posiciones, con el motor
(`motor.py`). Así aplican también a días ya recorridos y un cambio en la ruta
(puntos, corredor, velocidades) se refleja de inmediato sin reprocesar nada.
La ruta de cada bus es la del despacho de ese día, salvo que se elija una.
"""
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

from . import bp, motor
from .comun import a_bd, ahora_utc, db, desde_bd, iso, rol
from .rutas import CONFIG_POR_DEFECTO, _geometria, configs_rutas, zonas_encierro

VER = ("Administrador", "Jefe de Ruta", "Despachador")

MAX_DIAS = 7
MARGEN_RECEPCION = timedelta(hours=2)   # paquetes del día que el equipo reenvió tarde
MAX_RECORRIDO = timedelta(hours=24)
MAX_PUNTOS_RECORRIDO = 6000
BOGOTA = timedelta(hours=-5)


def _dia_utc(d):
    """[inicio, fin) del día d en hora Bogotá, expresado en UTC."""
    inicio = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - BOGOTA
    return inicio, inicio + timedelta(days=1)


def _fecha(v, por_defecto):
    if not v:
        return por_defecto
    return date.fromisoformat(v)


def _posiciones(conn, desde, hasta, bus_id=None):
    """{bus_id: [posición]} con fix, cuya hora (GPS, o de recepción si no trae) cae en [desde, hasta)."""
    sql = ("SELECT bus_id, lat, lon, velocidad_kmh, rumbo, precision_m, hora_gps, recibido_at "
           "FROM gps_posiciones WHERE recibido_at >= ? AND recibido_at < ? "
           "AND fix = 1 AND lat IS NOT NULL AND bus_id IS NOT NULL")
    params = [a_bd(desde), a_bd(hasta + MARGEN_RECEPCION)]
    if bus_id:
        sql += " AND bus_id = ?"
        params.append(bus_id)
    por_bus = {}
    for r in conn.execute(sql, tuple(params)).fetchall():
        r = dict(r)
        t = desde_bd(r["hora_gps"]) or desde_bd(r["recibido_at"])
        if t is None or not desde <= t < hasta:
            continue
        por_bus.setdefault(r["bus_id"], []).append({
            "t": t, "lat": r["lat"], "lon": r["lon"], "vel": r["velocidad_kmh"],
            "rumbo": r["rumbo"], "precision": r["precision_m"],
        })
    return por_bus


def _cargar_ruta(conn, ruta_id):
    fila = conn.execute("SELECT id, nombre FROM rutas WHERE id = ?", (ruta_id,)).fetchone()
    if not fila:
        return None
    g = _geometria(conn, ruta_id).get(ruta_id, {"trazados": {}, "puntos": []})
    tramos = [dict(t) for t in conn.execute(
        "SELECT sentido, desde_m, hasta_m, vel_aviso_kmh, vel_critica_kmh, nombre "
        "FROM ruta_tramos_velocidad WHERE ruta_id = ? AND activo = 1", (ruta_id,)).fetchall()]
    return motor.Ruta(ruta_id, dict(fila)["nombre"],
                      {s: t["puntos"] for s, t in g["trazados"].items()}, g["puntos"], tramos)


def _punto_pub(p):
    return {k: p.get(k) for k in ("id", "nombre", "alias", "tipo", "sentido", "orden",
                                  "minutos_objetivo", "radio_m")}


def _pub_paso(p):
    pt = p["punto"]
    return {"punto_id": pt["id"], "alias": pt.get("alias"), "nombre": pt["nombre"], "tipo": pt["tipo"],
            "sentido_punto": pt.get("sentido"), "sentido_bus": p["sentido_bus"],
            "entrada": iso(p["entrada"]), "salida": iso(p["salida"]), "paso": iso(p["paso"]),
            "distancia_m": p["distancia_m"], "vuelta": p["vuelta"],
            "vuelta_llegada": p["vuelta_llegada"], "vuelta_salida": p["vuelta_salida"],
            "transcurrido_min": p["transcurrido_min"], "minutos_objetivo": pt.get("minutos_objetivo"),
            "desvio_min": p["desvio_min"]}


def _pub_vuelta(v):
    def term(p):
        return {"id": p["id"], "alias": p.get("alias"), "nombre": p["nombre"]} if p else None
    return {"n": v["n"], "salida": iso(v["salida"]), "terminal_salida": term(v["terminal_salida"]),
            "llegada": iso(v["llegada"]), "terminal_llegada": term(v["terminal_llegada"]),
            "duracion_min": v["duracion_min"], "objetivo_llegada_min": v["objetivo_llegada_min"],
            "desvio_llegada_min": v["desvio_llegada_min"],
            "pasos": {str(p["punto"]["id"]): {"paso": iso(p["paso"]), "transcurrido_min": p["transcurrido_min"],
                                              "desvio_min": p["desvio_min"]}
                      for p in reversed(v["pasos"])}}   # reversed: si repite punto, queda el primero


def _pub(evento, *campos_hora):
    return {k: (iso(v) if k in campos_hora else v) for k, v in evento.items()}


def _avisos(ruta, origen, res):
    avisos = []
    if not ruta:
        avisos.append("Sin ruta asignada en el despacho: solo se evalúan los excesos de velocidad, "
                      f"con los límites por defecto ({CONFIG_POR_DEFECTO['vel_aviso_kmh']} / "
                      f"{CONFIG_POR_DEFECTO['vel_critica_kmh']} km/h).")
        return avisos
    if not ruta.trazados:
        avisos.append(f"La ruta {ruta.nombre} no tiene trazado: no se pueden calcular abandonos ni sentidos. "
                      "Impórtalo en Rutas Geográficas.")
    elif not res["resumen"]["inicio_ruta"]:
        avisos.append(f"El bus nunca entró al corredor de la ruta {ruta.nombre} (sin iniciar recorrido). "
                      + ("¿Es correcta la ruta del despacho?" if origen == "despacho" else ""))
    if not ruta.puntos:
        avisos.append(f"La ruta {ruta.nombre} no tiene puntos de control.")
    elif not ruta.tiene_terminal:
        avisos.append("La ruta no tiene ningún punto tipo Terminal: se muestran las horas de paso, "
                      "pero no las vueltas ni el atraso/adelanto.")
    return avisos


@bp.route("/api/monitoreo/reportes", methods=["GET"])
@rol(*VER)
def reporte_recorridos():
    hoy = (ahora_utc() + BOGOTA).date()
    try:
        desde = _fecha(request.args.get("fecha"), hoy)
        hasta = _fecha(request.args.get("fecha_fin"), desde)
    except ValueError:
        return jsonify({"error": "Fecha inválida (usa AAAA-MM-DD)"}), 400
    if hasta < desde:
        return jsonify({"error": "La fecha final no puede ser anterior a la inicial"}), 400
    if (hasta - desde).days >= MAX_DIAS:
        return jsonify({"error": f"El rango máximo es de {MAX_DIAS} días"}), 400
    bus_id = request.args.get("bus_id", type=int)
    ruta_elegida = request.args.get("ruta_id", type=int)

    conn = db()
    try:
        buses = {r["id"]: r for r in (dict(x) for x in conn.execute(
            "SELECT id, numero, placa FROM buses").fetchall())}
        configs = configs_rutas(conn)
        zonas = zonas_encierro(conn)
        rutas = {}

        def ruta(rid):
            if rid and rid not in rutas:
                rutas[rid] = _cargar_ruta(conn, rid)
            return rutas.get(rid)

        grupos = []
        d = desde
        while d <= hasta:
            inicio, fin = _dia_utc(d)
            por_bus = _posiciones(conn, inicio, fin, bus_id)
            despachos = {r["bus_id"]: r for r in (dict(x) for x in conn.execute(
                "SELECT d.bus_id, d.ruta_id, d.estado, c.nombre AS conductor FROM despacho_diario d "
                "LEFT JOIN conductores c ON c.id = d.conductor_id WHERE d.fecha = ?",
                (d.isoformat(),)).fetchall())}
            for bid in sorted(por_bus, key=lambda b: (buses.get(b, {}).get("numero") is None,
                                                       str(buses.get(b, {}).get("numero")).zfill(6))):
                desp = despachos.get(bid) or {}
                if ruta_elegida:
                    rid, origen = ruta_elegida, "elegida"
                elif desp.get("ruta_id"):
                    rid, origen = desp["ruta_id"], "despacho"
                else:
                    rid, origen = None, None
                r = ruta(rid)
                cfg = configs.get(rid, CONFIG_POR_DEFECTO)
                res = motor.analizar(por_bus[bid], r, cfg, zonas)
                bus = buses.get(bid, {})
                grupos.append({
                    "fecha": d.isoformat(), "bus_id": bid, "numero": bus.get("numero"), "placa": bus.get("placa"),
                    "ruta_id": r.id if r else None, "ruta_nombre": r.nombre if r else None,
                    "ruta_origen": origen, "estado_despacho": desp.get("estado"),
                    "conductor": desp.get("conductor"),
                    "limites": {"aviso": cfg["vel_aviso_kmh"], "critico": cfg["vel_critica_kmh"],
                                "corredor_m": cfg["corredor_m"]},
                    "resumen": _pub(res["resumen"], "primera", "ultima", "inicio_ruta"),
                    "avisos": _avisos(r, origen, res),
                    "vueltas": [_pub_vuelta(v) for v in res["vueltas"]],
                    "pasos": [_pub_paso(p) for p in res["pasos"]],
                    "excesos": [_pub(e, "inicio", "fin", "hora_max") for e in res["excesos"]],
                    "abandonos": [_pub(a, "inicio", "fin") for a in res["abandonos"]],
                })
            d += timedelta(days=1)
    finally:
        conn.close()

    return jsonify({
        "fecha": desde.isoformat(), "fecha_fin": hasta.isoformat(), "grupos": grupos,
        "puntos_ruta": {str(rid): [_punto_pub(p) for p in r.puntos] for rid, r in rutas.items() if r},
    })


@bp.route("/api/monitoreo/reportes/recorrido", methods=["GET"])
@rol(*VER)
def recorrido_bus():
    """Posiciones de un bus entre dos instantes (UTC ISO), para verlas en el mapa."""
    bus_id = request.args.get("bus_id", type=int)
    desde, hasta = desde_bd(request.args.get("desde")), desde_bd(request.args.get("hasta"))
    if not bus_id or not desde or not hasta or hasta <= desde:
        return jsonify({"error": "Indica bus_id, desde y hasta"}), 400
    if hasta - desde > MAX_RECORRIDO:
        return jsonify({"error": "El recorrido máximo es de 24 horas"}), 400
    conn = db()
    try:
        pos = _posiciones(conn, desde, hasta, bus_id).get(bus_id, [])
    finally:
        conn.close()
    pos.sort(key=lambda p: p["t"])
    if len(pos) > MAX_PUNTOS_RECORRIDO:
        paso = len(pos) / MAX_PUNTOS_RECORRIDO
        pos = [pos[int(i * paso)] for i in range(MAX_PUNTOS_RECORRIDO)]
    return jsonify([{"t": iso(p["t"]), "lat": p["lat"], "lon": p["lon"],
                     "vel": p["vel"]} for p in pos])
