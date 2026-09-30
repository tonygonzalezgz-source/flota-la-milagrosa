"""Rutas geográficas: trazados de ida/regreso y puntos de control por ruta.

Se enlazan a la tabla `rutas` existente (la misma que usa el despacho), así el
bus toma la geometría de la ruta que el despacho le asignó ese día.
"""
import json
import math
import os

from flask import Response, jsonify, request

from . import bp, geo, kml
from .comun import EMPRESA_POR_DEFECTO, a_bd, ahora_utc, db, iso, rol

ADMIN = ("Administrador",)
VER = ("Administrador", "Jefe de Ruta", "Despachador", "Propietario")

UMBRAL_SENTIDO_M = 60      # punto a menos de esto de un trazado = pertenece a ese sentido
RADIO_POR_DEFECTO_M = 50
AVISO_EMPALME_M = 100      # fin de la ida lejos del inicio del regreso
MAX_VERTICES = 5000
MAX_PUNTOS = 200
SENTIDOS = ("ida", "regreso")
TIPOS_PUNTO = ("control", "terminal")
DISTANCIA_EXTREMO_M = 100  # punto cerca del inicio/fin de un trazado = probable terminal

# Parámetros del motor por ruta cuando no hay fila en ruta_config.
CONFIG_POR_DEFECTO = {"vel_aviso_kmh": 50, "vel_critica_kmh": 60, "corredor_m": 50,
                      "posiciones_fuera": 2, "precision_max_m": 30, "desconexion_min": 3}
LIMITES_CONFIG = {"vel_aviso_kmh": (10, 120), "vel_critica_kmh": (10, 150), "corredor_m": (10, 300),
                  "posiciones_fuera": (1, 10), "precision_max_m": (5, 200), "desconexion_min": (1, 60)}


# ══════════════════════════════════════════
#  Cálculo: sentido y orden de los puntos de control
# ══════════════════════════════════════════

def _r(v, n=1):
    return None if v is None else round(v, n)


def calcular(trazados, puntos):
    """Asigna a cada punto el sentido cuyo trazado queda a <= 60 m (o ambos) y
    los ordena por su posición a lo largo del recorrido (ida y luego regreso),
    no por el orden del archivo. Un sentido pedido explícitamente se respeta."""
    ida = trazados.get("ida") or []
    regreso = trazados.get("regreso") or []
    plano = geo.plano_para(ida, regreso, [[p["lat"], p["lon"]] for p in puntos] or [[0, 0]])

    salida = []
    for p in puntos:
        d_i, m_i, _ = geo.proyectar(p["lat"], p["lon"], ida, plano) if ida else (None, None, None)
        d_r, m_r, _ = geo.proyectar(p["lat"], p["lon"], regreso, plano) if regreso else (None, None, None)
        cerca = [s for s, d in (("ida", d_i), ("regreso", d_r)) if d is not None and d <= UMBRAL_SENTIDO_M]
        auto = "ambos" if len(cerca) == 2 else (cerca[0] if cerca else None)
        pedido = p.get("sentido")
        sentido = auto if pedido in (None, "", "auto") else pedido
        salida.append({
            **{k: p.get(k) for k in ("id", "nombre", "lat", "lon", "alias", "minutos_objetivo")},
            "tipo": p.get("tipo") or "control",
            "radio_m": int(p.get("radio_m") or RADIO_POR_DEFECTO_M),
            "sentido": sentido,
            "sentido_auto": auto,
            "manual": pedido not in (None, "", "auto"),
            "dist_ida_m": _r(d_i),
            "dist_regreso_m": _r(d_r),
            "medida_ida_m": _r(m_i) if sentido in ("ida", "ambos") else None,
            "medida_regreso_m": _r(m_r) if sentido in ("regreso", "ambos") else None,
        })

    def clave(q):
        if q["sentido"] in ("ida", "ambos"):
            return (0, q["medida_ida_m"] or 0)
        if q["sentido"] == "regreso":
            return (1, q["medida_regreso_m"] or 0)
        return (2, 0)

    salida.sort(key=clave)
    for i, q in enumerate(salida, 1):
        q["orden"] = i

    avisos = []
    sin_sentido = [q["nombre"] for q in salida if not q["sentido"]]
    if sin_sentido:
        avisos.append(f"{len(sin_sentido)} punto(s) quedan a más de {UMBRAL_SENTIDO_M} m de ambos "
                      f"trazados: {', '.join(sin_sentido)}. Revisa su ubicación o asígnales sentido a mano.")
    empalme = geo.distancia_extremos_m(ida, regreso)
    if empalme is not None and empalme > AVISO_EMPALME_M:
        avisos.append(f"El final de la ida queda a {round(empalme)} m del inicio del regreso. "
                      "Verifica que los sentidos no estén invertidos.")
    return {
        "puntos": salida,
        "longitudes": {"ida": _r(geo.longitud_m(ida), 0) if ida else None,
                       "regreso": _r(geo.longitud_m(regreso), 0) if regreso else None},
        "avisos": avisos,
    }


def sugerir_alias(nombre, usados):
    """Código corto: 1 palabra → 3 primeras letras (WATANA → WAT); 2 → inicial +
    2 letras de la segunda (LA PIEDRA → LPI); 3 o más → iniciales."""
    palabras = [w for w in "".join(c if c.isalnum() else " " for c in nombre.upper()).split() if w]
    if not palabras:
        base = "PC"
    elif len(palabras) == 1:
        base = palabras[0][:3]
    elif len(palabras) == 2:
        base = palabras[0][0] + palabras[1][:2]
    else:
        base = "".join(w[0] for w in palabras[:3])
    alias, n = base, 2
    while alias in usados:
        alias, n = f"{base[:2]}{n}", n + 1
    usados.add(alias)
    return alias


def sugerir_tipo(p, trazados):
    if "TERMINAL" in (p["nombre"] or "").upper():
        return "terminal"
    for linea in trazados.values():
        for extremo in (linea[0], linea[-1]):
            if geo.haversine_m(p["lat"], p["lon"], extremo[0], extremo[1]) <= DISTANCIA_EXTREMO_M:
                return "terminal"
    return "control"


# ══════════════════════════════════════════
#  Validación de entrada
# ══════════════════════════════════════════

def _coord(v, limite):
    f = float(v)
    if not math.isfinite(f) or abs(f) > limite:
        raise ValueError
    return f


def _validar_trazados(data):
    trazados = {}
    for s in SENTIDOS:
        linea = (data or {}).get(s)
        if not linea:
            continue
        if not isinstance(linea, list) or len(linea) < 2 or len(linea) > MAX_VERTICES:
            raise ValueError(f"El trazado de {s} debe tener entre 2 y {MAX_VERTICES} vértices.")
        try:
            trazados[s] = [[round(_coord(p[0], 90), 7), round(_coord(p[1], 180), 7)] for p in linea]
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"El trazado de {s} tiene coordenadas inválidas.")
    if not trazados:
        raise ValueError("La ruta necesita al menos un trazado (ida o regreso).")
    return trazados


def _validar_puntos(lista):
    if not isinstance(lista or [], list) or len(lista or []) > MAX_PUNTOS:
        raise ValueError(f"Máximo {MAX_PUNTOS} puntos de control.")
    puntos = []
    for p in lista or []:
        try:
            nombre = str(p.get("nombre") or "").strip()[:80]
            lat, lon = _coord(p.get("lat"), 90), _coord(p.get("lon"), 180)
            radio = int(p.get("radio_m") or RADIO_POR_DEFECTO_M)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Hay un punto de control con datos inválidos.")
        if not nombre:
            raise ValueError("Todos los puntos de control deben tener nombre.")
        if not 5 <= radio <= 500:
            raise ValueError(f"El radio de '{nombre}' debe estar entre 5 y 500 m.")
        sentido = p.get("sentido")
        if sentido not in (None, "", "auto", "ida", "regreso", "ambos"):
            raise ValueError(f"Sentido inválido en '{nombre}'.")
        tipo = p.get("tipo") or "control"
        if tipo not in TIPOS_PUNTO:
            raise ValueError(f"Tipo inválido en '{nombre}'.")
        alias = str(p.get("alias") or "").strip().upper()[:6] or None
        minutos = p.get("minutos_objetivo")
        if minutos in ("", None):
            minutos = None
        else:
            try:
                minutos = int(minutos)
            except (TypeError, ValueError):
                raise ValueError(f"Minutos objetivo inválidos en '{nombre}'.")
            if not 0 <= minutos <= 600:
                raise ValueError(f"Los minutos objetivo de '{nombre}' deben estar entre 0 y 600.")
        pid = p.get("id")
        puntos.append({"id": int(pid) if pid else None, "nombre": nombre, "lat": lat, "lon": lon,
                       "radio_m": radio, "sentido": sentido, "tipo": tipo, "alias": alias,
                       "minutos_objetivo": minutos})
    return puntos


# ══════════════════════════════════════════
#  Lectura
# ══════════════════════════════════════════

def _geometria(conn, ruta_id=None):
    """{ruta_id: {trazados, puntos}} de las rutas indicadas (o todas)."""
    filtro, params = ("WHERE ruta_id = ?", (ruta_id,)) if ruta_id else ("", ())
    out = {}
    for t in conn.execute(f"SELECT ruta_id, sentido, puntos, longitud_m, nombre_origen, updated_at "
                          f"FROM ruta_trazados {filtro}", params).fetchall():
        t = dict(t)
        g = out.setdefault(t["ruta_id"], {"trazados": {}, "puntos": []})
        g["trazados"][t["sentido"]] = {"puntos": json.loads(t["puntos"]), "longitud_m": t["longitud_m"],
                                       "nombre_origen": t["nombre_origen"], "updated_at": iso(t["updated_at"])}
    filtro_p = "AND ruta_id = ?" if ruta_id else ""
    for p in conn.execute(f"SELECT id, ruta_id, nombre, lat, lon, radio_m, sentido, medida_ida_m, "
                          f"medida_regreso_m, orden, tipo, alias, minutos_objetivo "
                          f"FROM ruta_puntos_control WHERE activo = 1 {filtro_p} "
                          f"ORDER BY ruta_id, orden", params).fetchall():
        p = dict(p)
        out.setdefault(p["ruta_id"], {"trazados": {}, "puntos": []})["puntos"].append(p)
    return out


@bp.route("/api/monitoreo/rutas", methods=["GET"])
@rol(*VER)
def listar_rutas():
    conn = db()
    rutas = [dict(r) for r in conn.execute(
        "SELECT id, nombre, grupo, color FROM rutas WHERE activa = 1 ORDER BY grupo, nombre").fetchall()]
    geos = _geometria(conn)
    conn.close()
    for r in rutas:
        g = geos.get(r["id"], {"trazados": {}, "puntos": []})
        r["tiene_ida"] = "ida" in g["trazados"]
        r["tiene_regreso"] = "regreso" in g["trazados"]
        r["longitud_ida_m"] = g["trazados"].get("ida", {}).get("longitud_m")
        r["longitud_regreso_m"] = g["trazados"].get("regreso", {}).get("longitud_m")
        r["puntos_control"] = len(g["puntos"])
    return jsonify(rutas)


@bp.route("/api/monitoreo/rutas/geometria", methods=["GET"])
@rol(*VER)
def geometria_rutas():
    """Trazados y puntos de control; ?ruta_id= para una sola ruta."""
    ruta_id = request.args.get("ruta_id", type=int)
    conn = db()
    rutas = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, nombre, color FROM rutas WHERE activa = 1").fetchall()}
    geos = _geometria(conn, ruta_id)
    conn.close()
    return jsonify([{"ruta_id": rid, "nombre": rutas[rid]["nombre"], "color": rutas[rid]["color"], **g}
                    for rid, g in geos.items() if rid in rutas])


# ══════════════════════════════════════════
#  Importación y guardado (solo Administrador)
# ══════════════════════════════════════════

@bp.route("/api/monitoreo/rutas/importar", methods=["POST"])
@rol(*ADMIN)
def importar_kml():
    """Lee un .kml/.kmz y devuelve una VISTA PREVIA (no guarda nada)."""
    archivo = request.files.get("archivo")
    if not archivo:
        return jsonify({"error": "Adjunta un archivo .kml o .kmz"}), 400
    try:
        leido = kml.leer(archivo.read(kml.MAX_BYTES + 1))
    except kml.KmlError as e:
        return jsonify({"error": str(e)}), 400

    lineas = []
    for i, l in enumerate(leido["lineas"]):
        lineas.append({"nombre": l["nombre"], "puntos": l["puntos"],
                       "longitud_m": round(geo.longitud_m(l["puntos"])),
                       "sentido": kml.sugerir_sentido(l["nombre"])})
    # Si los nombres no dicen nada: la primera línea es ida y la segunda regreso.
    if not any(l["sentido"] for l in lineas):
        for l, s in zip(lineas, SENTIDOS):
            l["sentido"] = s
    trazados = {}
    for l in lineas:
        if l["sentido"] and l["sentido"] not in trazados:
            trazados[l["sentido"]] = l["puntos"]
        elif l["sentido"]:
            l["sentido"] = None   # dos líneas con el mismo sentido: la segunda queda para decidir
    usados = set()
    puntos = [{**p, "radio_m": RADIO_POR_DEFECTO_M, "alias": sugerir_alias(p["nombre"], usados),
               "tipo": sugerir_tipo(p, trazados)} for p in leido["puntos"]]
    return jsonify({"nombre": leido["nombre"], "lineas": lineas, **calcular(trazados, puntos)})


@bp.route("/api/monitoreo/rutas/calcular", methods=["POST"])
@rol(*ADMIN)
def recalcular():
    """Recalcula sentido y orden de los puntos (p. ej. al corregir ida/regreso en la vista previa)."""
    data = request.get_json(silent=True) or {}
    try:
        trazados = _validar_trazados(data.get("trazados"))
        puntos = _validar_puntos(data.get("puntos"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(calcular(trazados, puntos))


@bp.route("/api/monitoreo/rutas/<int:ruta_id>/geometria", methods=["PUT"])
@rol(*ADMIN)
def guardar_geometria(ruta_id):
    """Reemplaza los trazados de la ruta y sincroniza sus puntos de control:
    con id → se actualiza; sin id → se crea; los que ya no vienen → activo = 0."""
    data = request.get_json(silent=True) or {}
    try:
        trazados = _validar_trazados(data.get("trazados"))
        puntos = _validar_puntos(data.get("puntos"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    usados = {p["alias"] for p in puntos if p["alias"]}
    for p in puntos:
        if not p["alias"]:
            p["alias"] = sugerir_alias(p["nombre"], usados)
    calculo = calcular(trazados, puntos)
    origen = str(data.get("nombre_origen") or "").strip()[:120] or None

    conn = db()
    if not conn.execute("SELECT id FROM rutas WHERE id = ?", (ruta_id,)).fetchone():
        conn.close()
        return jsonify({"error": "La ruta no existe"}), 404
    ahora = a_bd(ahora_utc())
    usuario = getattr(request, "jwt_user_id", None)
    try:
        for s in SENTIDOS:
            if s in trazados:
                conn.execute(
                    "INSERT INTO ruta_trazados (empresa_id, ruta_id, sentido, puntos, longitud_m, "
                    "nombre_origen, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (ruta_id, sentido) DO UPDATE SET puntos = excluded.puntos, "
                    "longitud_m = excluded.longitud_m, nombre_origen = excluded.nombre_origen, "
                    "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                    (EMPRESA_POR_DEFECTO, ruta_id, s, json.dumps(trazados[s], separators=(",", ":")),
                     geo.longitud_m(trazados[s]), origen, usuario, ahora),
                )
            else:
                conn.execute("DELETE FROM ruta_trazados WHERE ruta_id = ? AND sentido = ?", (ruta_id, s))

        existentes = {r["id"] for r in conn.execute(
            "SELECT id FROM ruta_puntos_control WHERE ruta_id = ? AND activo = 1", (ruta_id,)).fetchall()}
        conservados = set()
        for p in calculo["puntos"]:
            valores = (p["nombre"], p["lat"], p["lon"], p["radio_m"], p["sentido"],
                       p["medida_ida_m"], p["medida_regreso_m"], p["orden"], p["tipo"],
                       p["alias"], p["minutos_objetivo"], ahora)
            if p.get("id") in existentes:
                conn.execute(
                    "UPDATE ruta_puntos_control SET nombre = ?, lat = ?, lon = ?, radio_m = ?, sentido = ?, "
                    "medida_ida_m = ?, medida_regreso_m = ?, orden = ?, tipo = ?, alias = ?, "
                    "minutos_objetivo = ?, updated_at = ? WHERE id = ?",
                    valores + (p["id"],))
                conservados.add(p["id"])
            else:
                conn.execute(
                    "INSERT INTO ruta_puntos_control (nombre, lat, lon, radio_m, sentido, medida_ida_m, "
                    "medida_regreso_m, orden, tipo, alias, minutos_objetivo, updated_at, empresa_id, "
                    "ruta_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    valores + (EMPRESA_POR_DEFECTO, ruta_id, ahora))
        for pid in existentes - conservados:
            conn.execute("UPDATE ruta_puntos_control SET activo = 0, updated_at = ? WHERE id = ?", (ahora, pid))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return jsonify({"ok": True, "avisos": calculo["avisos"]})


@bp.route("/api/monitoreo/rutas/<int:ruta_id>/kml", methods=["GET"])
@rol(*ADMIN)
def exportar_kml(ruta_id):
    conn = db()
    ruta = conn.execute("SELECT nombre FROM rutas WHERE id = ?", (ruta_id,)).fetchone()
    g = _geometria(conn, ruta_id).get(ruta_id)
    conn.close()
    if not ruta or not g or not g["trazados"]:
        return jsonify({"error": "La ruta no tiene trazado guardado"}), 404
    nombre = dict(ruta)["nombre"]
    contenido = kml.escribir(nombre, {s: t["puntos"] for s, t in g["trazados"].items()}, g["puntos"])
    archivo = "".join(c if c.isalnum() or c in " -_" else "_" for c in nombre).strip() or "ruta"
    return Response(contenido, mimetype="application/vnd.google-earth.kml+xml",
                    headers={"Content-Disposition": f'attachment; filename="{archivo}.kml"'})


# ══════════════════════════════════════════
#  Configuración del motor por ruta
# ══════════════════════════════════════════

def config_ruta(conn, ruta_id):
    fila = conn.execute("SELECT * FROM ruta_config WHERE ruta_id = ?", (ruta_id,)).fetchone()
    cfg = dict(CONFIG_POR_DEFECTO)
    if fila:
        cfg.update({k: dict(fila)[k] for k in CONFIG_POR_DEFECTO})
    return cfg


def configs_rutas(conn):
    """{ruta_id: config} de todas las rutas que tienen fila; el resto usa los valores por defecto."""
    return {r["ruta_id"]: {k: r[k] for k in CONFIG_POR_DEFECTO}
            for r in (dict(x) for x in conn.execute("SELECT * FROM ruta_config").fetchall())}


@bp.route("/api/monitoreo/rutas/<int:ruta_id>/config", methods=["GET"])
@rol(*VER)
def ver_config(ruta_id):
    conn = db()
    cfg = config_ruta(conn, ruta_id)
    conn.close()
    return jsonify({**cfg, "por_defecto": CONFIG_POR_DEFECTO})


@bp.route("/api/monitoreo/rutas/<int:ruta_id>/config", methods=["PUT"])
@rol(*ADMIN)
def guardar_config(ruta_id):
    data = request.get_json(silent=True) or {}
    cfg = {}
    for k, (minimo, maximo) in LIMITES_CONFIG.items():
        try:
            v = int(data.get(k, CONFIG_POR_DEFECTO[k]))
        except (TypeError, ValueError):
            return jsonify({"error": f"Valor inválido en {k}"}), 400
        if not minimo <= v <= maximo:
            return jsonify({"error": f"{k} debe estar entre {minimo} y {maximo}"}), 400
        cfg[k] = v
    if cfg["vel_critica_kmh"] < cfg["vel_aviso_kmh"]:
        return jsonify({"error": "La velocidad crítica no puede ser menor que la de aviso"}), 400
    conn = db()
    if not conn.execute("SELECT id FROM rutas WHERE id = ?", (ruta_id,)).fetchone():
        conn.close()
        return jsonify({"error": "La ruta no existe"}), 404
    cols = list(cfg)
    conn.execute(
        f"INSERT INTO ruta_config (ruta_id, {', '.join(cols)}, updated_by, updated_at) "
        f"VALUES (?, {', '.join('?' * len(cols))}, ?, ?) ON CONFLICT (ruta_id) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in cols + ["updated_by", "updated_at"]),
        (ruta_id, *cfg.values(), getattr(request, "jwt_user_id", None), a_bd(ahora_utc())),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, **cfg})


# ══════════════════════════════════════════
#  Zonas de encierro (patios / parqueaderos)
# ══════════════════════════════════════════

def zonas_encierro(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, ruta_id, nombre, lat, lon, radio_m FROM zonas_encierro WHERE activo = 1 ORDER BY nombre"
    ).fetchall()]


@bp.route("/api/monitoreo/encierros", methods=["GET"])
@rol(*VER)
def listar_encierros():
    conn = db()
    zonas = zonas_encierro(conn)
    conn.close()
    return jsonify(zonas)


def _validar_zona(data):
    nombre = str(data.get("nombre") or "").strip()[:80]
    if not nombre:
        raise ValueError("La zona necesita un nombre.")
    try:
        lat, lon = _coord(data.get("lat"), 90), _coord(data.get("lon"), 180)
        radio = int(data.get("radio_m") or 100)
    except (TypeError, ValueError):
        raise ValueError("Coordenadas o radio inválidos.")
    if not 20 <= radio <= 1000:
        raise ValueError("El radio debe estar entre 20 y 1000 m.")
    ruta_id = data.get("ruta_id")
    return nombre, lat, lon, radio, (int(ruta_id) if ruta_id else None)


@bp.route("/api/monitoreo/encierros", methods=["POST"])
@rol(*ADMIN)
def crear_encierro():
    try:
        nombre, lat, lon, radio, ruta_id = _validar_zona(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = db()
    cur = conn.execute(
        "INSERT INTO zonas_encierro (empresa_id, ruta_id, nombre, lat, lon, radio_m, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (EMPRESA_POR_DEFECTO, ruta_id, nombre, lat, lon, radio, a_bd(ahora_utc())))
    conn.commit()
    nuevo = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "id": nuevo}), 201


@bp.route("/api/monitoreo/encierros/<int:zona_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_encierro(zona_id):
    try:
        nombre, lat, lon, radio, ruta_id = _validar_zona(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = db()
    conn.execute("UPDATE zonas_encierro SET nombre = ?, lat = ?, lon = ?, radio_m = ?, ruta_id = ? "
                 "WHERE id = ?", (nombre, lat, lon, radio, ruta_id, zona_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@bp.route("/api/monitoreo/encierros/<int:zona_id>", methods=["DELETE"])
@rol(*ADMIN)
def borrar_encierro(zona_id):
    conn = db()
    conn.execute("UPDATE zonas_encierro SET activo = 0 WHERE id = ?", (zona_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════
#  Configuración del mapa base
# ══════════════════════════════════════════

@bp.route("/api/monitoreo/mapa-config", methods=["GET"])
@rol(*VER)
def mapa_config():
    """Clave del mapa de Google para el navegador. No es secreta (Google Maps
    siempre la expone en el cliente): la protege la restricción por sitio web
    configurada en Google Cloud. Sin clave, el frontend usa las capas de Esri."""
    return jsonify({"google_maps_key": os.environ.get("GOOGLE_MAPS_KEY") or None})
