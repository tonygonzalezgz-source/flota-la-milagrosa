"""Mapa en vivo: última posición de cada bus con equipo GPS activo.

Lee `gps_ultima_posicion` (una fila por bus) para la ubicación. La ruta del bus
es la que le asignó el despacho de HOY (fecha Bogotá). Para el sentido, el
último punto de control y las alarmas (abandono, atajo, exceso) corre el mismo
motor de los reportes sobre las posiciones de la última hora y media del bus;
el resultado se guarda en memoria hasta que llegue una posición nueva.
"""
import time
from datetime import timedelta

from flask import jsonify, request

from . import bp, geo, motor
from .comun import ahora_utc, db, desde_bd, iso, rol
from .reportes import _cargar_ruta, _posiciones
from .rutas import CONFIG_POR_DEFECTO, configs_rutas, zonas_encierro

VER = ("Administrador", "Jefe de Ruta", "Despachador", "Propietario")

MOVIMIENTO_KMH = 3                    # por debajo = detenido (ruido del GPS parado)
VENTANA_VIVO = timedelta(minutes=90)  # historia que se analiza para el estado en vivo
ALARMA_ATAJO = timedelta(minutes=15)  # cuánto se muestra un atajo después de ocurrir
ALARMA_EXCESO = timedelta(minutes=2)
CACHE_RUTA_S = 300
CACHE_ANALISIS_S = 60

_rutas = {}      # ruta_id → (instante, motor.Ruta)
_analisis = {}   # bus_id → ((ruta_id, ultimo_reporte_at), resultado, instante)


def hoy_bogota(ahora):
    return (ahora - timedelta(hours=5)).date().isoformat()


def en_encierro(fila, zonas):
    """Zona de encierro que contiene al bus (las de su ruta o las de toda la empresa)."""
    if fila["lat"] is None:
        return None
    for z in zonas:
        if z["ruta_id"] not in (None, fila["ruta_id"]):
            continue
        if geo.haversine_m(fila["lat"], fila["lon"], z["lat"], z["lon"]) <= z["radio_m"]:
            return z
    return None


def estado_bus(fila, ahora, desconexion_s, zona):
    # En el patio el bus suele estar apagado: no es desconexión ni abandono.
    if zona:
        return "encierro"
    reporte = desde_bd(fila["ultimo_reporte_at"])
    if reporte is None or (ahora - reporte).total_seconds() > desconexion_s:
        return "sin_senal"
    if fila["lat"] is None:
        return "sin_fix"
    if not fila["fix_actual"]:
        return "sin_fix"
    if (fila["velocidad_kmh"] or 0) >= MOVIMIENTO_KMH:
        return "movimiento"
    return "detenido"


def _ruta(conn, ruta_id):
    hit = _rutas.get(ruta_id)
    if hit and time.monotonic() - hit[0] < CACHE_RUTA_S:
        return hit[1]
    r = _cargar_ruta(conn, ruta_id)
    _rutas[ruta_id] = (time.monotonic(), r)
    return r


def _alarma(res, ahora):
    """La alarma más grave vigente: fuera de ruta ahora > atajo reciente > exceso crítico reciente."""
    abierto = next((a for a in res["abandonos"] if a["tipo"] == "abandono" and not a["regreso"]), None)
    if abierto:
        return {"tipo": "abandono", "desde": iso(abierto["inicio"]), "distancia_m": abierto["distancia_max_m"]}
    atajo = next((a for a in reversed(res["abandonos"])
                  if (a["tipo"] == "atajo" or a["saltado_m"]) and a["fin"] and ahora - a["fin"] <= ALARMA_ATAJO), None)
    if atajo:
        return {"tipo": "atajo", "hora": iso(atajo["inicio"]), "saltado_m": atajo["saltado_m"]}
    exceso = next((e for e in reversed(res["excesos"])
                   if e["nivel"] == "critico" and ahora - e["fin"] <= ALARMA_EXCESO), None)
    if exceso:
        return {"tipo": "exceso", "hora": iso(exceso["hora_max"]), "vel_max": exceso["vel_max"],
                "limite": exceso["limite_critico"]}
    return None


def _estado_ruta(res):
    pasos = sorted(res["pasos"], key=lambda p: p["paso"])
    ultimo = None
    if pasos:
        p = pasos[-1]
        ultimo = {"alias": p["punto"].get("alias"), "nombre": p["punto"]["nombre"], "tipo": p["punto"]["tipo"],
                  "hora": iso(p["salida"] if p["punto"]["tipo"] == "terminal" else p["paso"]),
                  "desvio_min": p["desvio_min"]}
    return {"sentido": res["resumen"]["sentido_actual"], "en_ruta": res["resumen"]["en_ruta_actual"],
            "ultimo_punto": ultimo}


def _analizar_buses(conn, filas, configs, zonas, ahora):
    """Sentido, último punto y alarma de los buses con ruta. Solo se recalcula
    el bus que tiene un reporte nuevo, cambió de ruta o lleva un minuto sin
    recalcularse (las alarmas recientes vencen con el tiempo)."""
    def vigente(f):
        hit = _analisis.get(f["bus_id"])
        return hit and hit[0] == (f["ruta_id"], f["ultimo_reporte_at"]) and time.monotonic() - hit[2] < CACHE_ANALISIS_S

    pendientes = [f for f in filas if f["ruta_id"] and not vigente(f)]
    if pendientes:
        ids = {f["bus_id"] for f in pendientes}
        por_bus = (_posiciones(conn, ahora - VENTANA_VIVO, ahora + timedelta(minutes=5),
                               next(iter(ids)) if len(ids) == 1 else None))
        for f in pendientes:
            r = _ruta(conn, f["ruta_id"])
            res = motor.analizar(por_bus.get(f["bus_id"], []), r, configs.get(f["ruta_id"], CONFIG_POR_DEFECTO), zonas)
            _analisis[f["bus_id"]] = ((f["ruta_id"], f["ultimo_reporte_at"]),
                                      {**_estado_ruta(res), "alarma": _alarma(res, ahora)}, time.monotonic())
    return {f["bus_id"]: _analisis[f["bus_id"]][1] for f in filas if f["ruta_id"]}


@bp.route("/api/monitoreo/vivo", methods=["GET"])
@rol(*VER)
def vivo():
    ahora = ahora_utc()
    sql = """SELECT u.bus_id, b.numero, b.placa,
                    u.lat, u.lon, u.velocidad_kmh, u.rumbo, u.precision_m, u.satelites,
                    u.hora_gps, u.ultimo_reporte_at, u.fix_actual,
                    d.ruta_id, r.nombre AS ruta_nombre, r.color AS ruta_color,
                    d.estado AS estado_despacho
               FROM gps_ultima_posicion u
               JOIN buses b ON b.id = u.bus_id
               JOIN gps_equipos e ON e.bus_id = u.bus_id AND e.activo = 1
          LEFT JOIN despacho_diario d ON d.bus_id = u.bus_id AND d.fecha = ?
          LEFT JOIN rutas r ON r.id = d.ruta_id"""
    params = [hoy_bogota(ahora)]
    if getattr(request, "jwt_user_rol", None) == "Propietario":
        sql += " WHERE u.bus_id IN (SELECT bus_id FROM usuario_buses WHERE usuario_id = ?)"
        params.append(request.jwt_user_id)
    sql += " ORDER BY b.numero"

    conn = db()
    try:
        filas = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
        configs = configs_rutas(conn)
        zonas = zonas_encierro(conn)
        try:
            analisis = _analizar_buses(conn, filas, configs, zonas, ahora)
        except Exception as e:   # el mapa nunca debe caerse por el análisis
            print(f"[monitoreo.vivo] análisis: {e}")
            analisis = {}
    finally:
        conn.close()
    buses = []
    for f in filas:
        cfg = configs.get(f["ruta_id"], CONFIG_POR_DEFECTO)
        desconexion_s = cfg["desconexion_min"] * 60
        zona = en_encierro(f, zonas)
        f["estado"] = estado_bus(f, ahora, desconexion_s, zona)
        f["encierro"] = zona["nombre"] if zona else None
        f["desconexion_s"] = desconexion_s
        f["hora_gps"] = iso(f["hora_gps"])
        f["ultimo_reporte_at"] = iso(f["ultimo_reporte_at"])
        a = analisis.get(f["bus_id"]) or {}
        f["sentido"] = a.get("sentido")
        f["en_ruta"] = a.get("en_ruta")
        f["ultimo_punto"] = a.get("ultimo_punto")
        f["alarma"] = a.get("alarma") if not zona else None
        if f["alarma"] and f["estado"] in ("movimiento", "detenido", "sin_fix"):
            f["estado"] = "alarma"
        buses.append(f)
    return jsonify({"servidor_utc": iso(ahora), "buses": buses,
                    "desconexion_por_defecto_s": CONFIG_POR_DEFECTO["desconexion_min"] * 60})
