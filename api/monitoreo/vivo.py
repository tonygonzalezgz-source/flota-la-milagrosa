"""Mapa en vivo: última posición de cada bus con equipo GPS activo.

Lee solo `gps_ultima_posicion` (una fila por bus), nunca el histórico. La ruta
del bus es la que le asignó el despacho de HOY (fecha Bogotá).
"""
from datetime import timedelta

from flask import jsonify, request

from . import bp, geo
from .comun import ahora_utc, db, desde_bd, iso, rol
from .rutas import CONFIG_POR_DEFECTO, configs_rutas, zonas_encierro

VER = ("Administrador", "Jefe de Ruta", "Despachador", "Propietario")

MOVIMIENTO_KMH = 3      # por debajo = detenido (ruido del GPS parado)


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
    filas = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    configs = configs_rutas(conn)
    zonas = zonas_encierro(conn)
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
        # Se calculan con el motor de eventos (fase 4).
        f["sentido"] = None
        f["ultimo_punto"] = None
        buses.append(f)
    return jsonify({"servidor_utc": iso(ahora), "buses": buses,
                    "desconexion_por_defecto_s": CONFIG_POR_DEFECTO["desconexion_min"] * 60})
