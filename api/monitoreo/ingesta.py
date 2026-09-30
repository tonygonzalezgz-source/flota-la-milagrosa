"""Ingesta de posiciones de los equipos GPS instalados en los buses.

POST /api/gps/posicion?imei=XXXXXXXXXXXXXXX&token=YYYY

El equipo manda `Content-Type: application/x-www-form-urlencoded` aunque el
cuerpo es JSON, así que se lee el cuerpo crudo sin mirar el header. La llave de
primer nivel es configurable en el equipo (hoy "gps"): no se amarra a un nombre,
se toman los objetos que traigan latitude + longitude.

Rendimiento: el equipo espera la respuesta. En Postgres se reutiliza una
conexión por instancia serverless y todo el paquete se escribe en UNA ida y
vuelta (varias sentencias en un solo envío); el equipo se cachea 60 s para no
consultarlo en cada paquete.
"""
import json
import math
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from . import bp
from .comun import (EMPRESA_POR_DEFECTO, a_bd, ahora_utc, database_url, db, es_pg,
                    hash_token, token_valido)

MAX_REGISTROS_POR_PAQUETE = 100
MAX_PENDIENTES = 500           # tope de IMEIs desconocidos guardados
MAX_PAYLOAD_GUARDADO = 4000    # caracteres del último payload de un pendiente
CACHE_EQUIPO_S = 60

_RE_IMEI = re.compile(r"^[0-9A-Za-z_-]{4,32}$")


# ══════════════════════════════════════════
#  Parseo del paquete
# ══════════════════════════════════════════

def parsear_cuerpo(raw):
    """Cuerpo crudo → objeto JSON. Tolera JSON url-encoded o 'clave=<json>'."""
    txt = raw.decode("utf-8", "replace").strip()
    if not txt:
        raise ValueError("cuerpo vacío")
    try:
        return json.loads(txt)
    except ValueError:
        pass
    dec = urllib.parse.unquote_plus(txt).strip()
    if not dec.startswith(("{", "[")) and "=" in dec:
        dec = dec.split("=", 1)[1].strip()
    return json.loads(dec)


def extraer_registros(obj):
    """Objetos con latitude + longitude, en el orden en que vienen."""
    encontrados = []

    def visitar(o, prof):
        if prof > 4 or len(encontrados) >= MAX_REGISTROS_POR_PAQUETE:
            return
        if isinstance(o, dict):
            if "latitude" in o and "longitude" in o:
                encontrados.append(o)
                return
            for v in o.values():
                visitar(v, prof + 1)
        elif isinstance(o, list):
            for v in o:
                visitar(v, prof + 1)

    visitar(obj, 0)
    return encontrados


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _primero(reg, *claves):
    for k in claves:
        if k in reg:
            v = _num(reg.get(k))
            if v is not None:
                return v
    return None


def _hora_gps(reg, ahora):
    """UTC. Prefiere date_iso_8601; si no, 'date' (dd/mm/aaaa hh:mm:ss, también UTC)."""
    dt = None
    iso = reg.get("date_iso_8601")
    if isinstance(iso, str) and iso.strip():
        s = iso.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None and isinstance(reg.get("date"), str):
        try:
            dt = datetime.strptime(reg["date"].strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            dt = None
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # Relojes absurdos (GPS sin sincronizar) no sirven para ordenar ni evaluar.
    if dt.year < 2020 or dt > ahora + timedelta(hours=1):
        return None
    return dt


def normalizar(reg, ahora):
    lat = _num(reg.get("latitude"))
    lon = _num(reg.get("longitude"))
    fix_status = _num(reg.get("fix_status"))
    coords_ok = (lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180
                 and not (abs(lat) < 1e-6 and abs(lon) < 1e-6))
    # fix_status 0 o coordenadas en 0 = sin señal GPS. Si el equipo no manda
    # fix_status, se decide solo por las coordenadas.
    fix = coords_ok and (fix_status is None or fix_status > 0)
    sats = _primero(reg, "satellites", "sats", "satellite_count")
    return {
        "lat": lat if coords_ok else None,
        "lon": lon if coords_ok else None,
        "velocidad_kmh": _num(reg.get("speed")),
        "rumbo": _primero(reg, "course", "angle", "heading", "bearing"),
        "precision_m": _num(reg.get("accuracy")),
        "satelites": int(sats) if sats is not None else None,
        "fix": 1 if fix else 0,
        "hora_gps": _hora_gps(reg, ahora),
    }


# ══════════════════════════════════════════
#  Acceso a BD
# ══════════════════════════════════════════

_conn_lock = threading.Lock()
_conn = {"raw": None}
_cache_equipos = {}   # imei → (instante, fila)


def invalidar_cache_equipo(imei=None):
    if imei is None:
        _cache_equipos.clear()
    else:
        _cache_equipos.pop(imei, None)


def _conexion_pg():
    import psycopg2
    c = _conn["raw"]
    if c is None or c.closed:
        c = psycopg2.connect(database_url(), sslmode="require", connect_timeout=8)
        c.autocommit = True
        _conn["raw"] = c
    return c


def _ejecutar(sql, params=(), traer=False):
    """Una ida y vuelta. Postgres: conexión reutilizada (reintenta 1 vez si se
    cayó). SQLite: conexión de app.py, varias sentencias en orden."""
    if es_pg():
        import psycopg2
        import psycopg2.extras
        for intento in (1, 2):
            try:
                with _conn_lock:
                    cur = _conexion_pg().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute(sql, params)
                    return [dict(r) for r in cur.fetchall()] if traer else None
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                try:
                    if _conn["raw"] is not None:
                        _conn["raw"].close()
                except Exception:
                    pass
                _conn["raw"] = None
                if intento == 2:
                    raise
    conn = db()
    try:
        filas = None
        sentencias = [s for s in sql.split(";") if s.strip()]
        pos = 0
        for s in sentencias:
            n = s.count("%s")
            cur = conn.execute(s.replace("%s", "?"), tuple(params[pos:pos + n]))
            pos += n
            if traer:
                filas = [dict(r) for r in cur.fetchall()]
        conn.commit()
        return filas
    finally:
        conn.close()


def _equipo(imei):
    ahora = time.monotonic()
    hit = _cache_equipos.get(imei)
    if hit and ahora - hit[0] < CACHE_EQUIPO_S:
        return hit[1]
    filas = _ejecutar(
        "SELECT id, empresa_id, token_hash, bus_id, activo FROM gps_equipos WHERE imei = %s",
        (imei,), traer=True,
    )
    fila = filas[0] if filas else None
    _cache_equipos[imei] = (ahora, fila)
    return fila


_COLS_POS = ("empresa_id", "equipo_id", "bus_id", "lat", "lon", "velocidad_kmh", "rumbo",
             "precision_m", "satelites", "fix", "hora_gps", "recibido_at")
_COLS_ULT_FIX = ("lat", "lon", "velocidad_kmh", "rumbo", "precision_m", "satelites", "hora_gps")


def _sql_ultima():
    # Las columnas del fix solo avanzan con un fix válido y más reciente (los
    # paquetes pueden llegar desordenados si el equipo reenvía su cola).
    t = "gps_ultima_posicion"
    cond = f"excluded.lat IS NOT NULL AND ({t}.hora_gps IS NULL OR excluded.hora_gps >= {t}.hora_gps)"
    sets = [f"{c} = CASE WHEN {cond} THEN excluded.{c} ELSE {t}.{c} END" for c in _COLS_ULT_FIX]
    sets += ["equipo_id = excluded.equipo_id", "empresa_id = excluded.empresa_id",
             "ultimo_reporte_at = excluded.ultimo_reporte_at",
             "fix_actual = excluded.fix_actual", "updated_at = excluded.updated_at"]
    cols = ("bus_id", "empresa_id", "equipo_id") + _COLS_ULT_FIX + ("ultimo_reporte_at", "fix_actual", "updated_at")
    return (f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            f"ON CONFLICT (bus_id) DO UPDATE SET {', '.join(sets)}")


def guardar_paquete(equipo, registros, ahora):
    """Inserta las posiciones, actualiza la última posición del bus y el
    estado del equipo, todo en una transacción y una sola ida y vuelta."""
    bus_id = equipo["bus_id"]
    empresa_id = equipo["empresa_id"] or EMPRESA_POR_DEFECTO
    # Postgres ejecuta varias sentencias enviadas juntas como UNA transacción
    # implícita (todo o nada), sin BEGIN/COMMIT que puedan dejar la conexión
    # reutilizada en estado abortado.
    sql, params = [], []

    filas = []
    for r in registros:
        filas.append("(" + ", ".join(["%s"] * len(_COLS_POS)) + ")")
        params += [empresa_id, equipo["id"], bus_id, r["lat"], r["lon"], r["velocidad_kmh"],
                   r["rumbo"], r["precision_m"], r["satelites"], r["fix"],
                   a_bd(r["hora_gps"]), a_bd(ahora)]
    if es_pg():
        sql.append(f"INSERT INTO gps_posiciones ({', '.join(_COLS_POS)}) VALUES {', '.join(filas)}")
    else:   # SQLite antiguo no siempre acepta VALUES múltiples con placeholders repartidos
        una = "(" + ", ".join(["%s"] * len(_COLS_POS)) + ")"
        sql += [f"INSERT INTO gps_posiciones ({', '.join(_COLS_POS)}) VALUES {una}"] * len(filas)

    ultimo = registros[-1]
    con_fix = [r for r in registros if r["fix"]]
    mejor = max(con_fix, key=lambda r: r["hora_gps"] or ahora) if con_fix else None

    if bus_id:
        sql.append(_sql_ultima())
        params += [bus_id, empresa_id, equipo["id"]]
        if mejor:
            params += [mejor["lat"], mejor["lon"], mejor["velocidad_kmh"], mejor["rumbo"],
                       mejor["precision_m"], mejor["satelites"], a_bd(mejor["hora_gps"] or ahora)]
        else:
            params += [None] * len(_COLS_ULT_FIX)
        params += [a_bd(ahora), ultimo["fix"], a_bd(ahora)]

    hora_ref = ultimo["hora_gps"]
    desfase = int((ahora - hora_ref).total_seconds()) if hora_ref else None
    sql.append(
        "UPDATE gps_equipos SET ultimo_reporte_at = %s, "
        "ultima_hora_gps = COALESCE(%s, ultima_hora_gps), ultimo_desfase_s = %s, "
        "ultimo_fix = %s, paquetes = paquetes + %s WHERE id = %s"
    )
    params += [a_bd(ahora), a_bd(hora_ref), desfase, ultimo["fix"], len(registros), equipo["id"]]
    _ejecutar(";\n".join(sql), tuple(params))


def guardar_pendiente(imei, token, cuerpo_txt, ip, ahora):
    existe = _ejecutar("SELECT 1 AS x FROM gps_pendientes WHERE imei = %s", (imei,), traer=True)
    if not existe:
        total = _ejecutar("SELECT COUNT(*) AS n FROM gps_pendientes", (), traer=True)
        if total and total[0]["n"] >= MAX_PENDIENTES:
            return False
    _ejecutar(
        "INSERT INTO gps_pendientes (imei, token_hash, primer_visto_at, ultimo_visto_at, "
        "paquetes, ultimo_payload, ultima_ip) VALUES (%s, %s, %s, %s, 1, %s, %s) "
        "ON CONFLICT (imei) DO UPDATE SET token_hash = excluded.token_hash, "
        "ultimo_visto_at = excluded.ultimo_visto_at, paquetes = gps_pendientes.paquetes + 1, "
        "ultimo_payload = excluded.ultimo_payload, ultima_ip = excluded.ultima_ip",
        (imei, hash_token(token) if token else None, a_bd(ahora), a_bd(ahora),
         cuerpo_txt[:MAX_PAYLOAD_GUARDADO], ip),
    )
    return True


# ══════════════════════════════════════════
#  Endpoint
# ══════════════════════════════════════════

@bp.route("/api/gps/posicion", methods=["POST"])
def gps_posicion():
    ahora = ahora_utc()
    imei = (request.args.get("imei") or "").strip()
    token = (request.args.get("token") or "").strip()
    if not _RE_IMEI.match(imei):
        return jsonify({"error": "imei inválido o ausente"}), 400

    raw = request.get_data(cache=False)   # antes de tocar request.form
    try:
        cuerpo = parsear_cuerpo(raw)
    except ValueError:
        return jsonify({"error": "el cuerpo no es JSON válido"}), 400
    crudos = extraer_registros(cuerpo)
    if not crudos:
        return jsonify({"error": "el paquete no trae latitude/longitude"}), 400

    equipo = _equipo(imei)
    if equipo is None:
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        guardar_pendiente(imei, token, raw.decode("utf-8", "replace"), ip, ahora)
        return jsonify({"ok": True, "estado": "pendiente"}), 200

    if not token_valido(token, equipo["token_hash"]):
        return jsonify({"error": "token inválido"}), 401
    if not equipo["activo"]:
        return jsonify({"error": "equipo desactivado"}), 403

    registros = [normalizar(r, ahora) for r in crudos]
    guardar_paquete(equipo, registros, ahora)
    # Fase 4: aquí se evaluarán los eventos (sentido, puntos de control,
    # velocidad, abandono) sin afectar lo ya guardado.
    return jsonify({"ok": True, "recibidos": len(registros)}), 200
