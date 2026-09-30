"""Administración de los equipos GPS: registro, tokens, asignación a buses
y dispositivos pendientes (IMEIs que reportan sin estar registrados)."""
from datetime import timedelta

from flask import jsonify, request

from . import bp
from .comun import (EMPRESA_POR_DEFECTO, a_bd, ahora_utc, db, desde_bd, hash_token, iso,
                    nuevo_token, rol)
from .esquema import asegurar_particiones
from .ingesta import _RE_IMEI, invalidar_cache_equipo

ADMIN = ("Administrador",)


def _bus_id(valor):
    """None, o id entero de un bus existente. Lanza ValueError con mensaje."""
    if valor in (None, "", 0, "0"):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError("bus_id inválido")


def _validar_bus(conn, bus_id, excluir_equipo=None):
    """El bus debe existir y no tener otro equipo activo."""
    if bus_id is None:
        return None
    bus = conn.execute("SELECT id, numero FROM buses WHERE id = ?", (bus_id,)).fetchone()
    if not bus:
        return "El bus no existe"
    otro = conn.execute(
        "SELECT imei FROM gps_equipos WHERE bus_id = ? AND activo = 1 AND id <> ?",
        (bus_id, excluir_equipo or 0),
    ).fetchone()
    if otro:
        return (f"El bus {dict(bus)['numero']} ya tiene el equipo {dict(otro)['imei']}. "
                "Desactívalo o quítale el bus primero.")
    return None


def _fila_equipo(r):
    r = dict(r)
    for k in ("ultimo_reporte_at", "ultima_hora_gps", "created_at", "updated_at", "pos_hora_gps"):
        if k in r:
            r[k] = iso(r[k])
    return r


@bp.route("/api/monitoreo/equipos", methods=["GET"])
@rol(*ADMIN)
def listar_equipos():
    conn = db()
    filas = conn.execute(
        """SELECT e.id, e.imei, e.bus_id, e.activo, e.notas,
                  e.ultimo_reporte_at, e.ultima_hora_gps, e.ultimo_desfase_s, e.ultimo_fix,
                  e.paquetes, e.created_at,
                  b.numero AS bus_numero, b.placa AS bus_placa,
                  u.lat AS pos_lat, u.lon AS pos_lon, u.hora_gps AS pos_hora_gps
             FROM gps_equipos e
        LEFT JOIN buses b ON b.id = e.bus_id
        LEFT JOIN gps_ultima_posicion u ON u.bus_id = e.bus_id AND u.equipo_id = e.id
            ORDER BY b.numero IS NULL, b.numero, e.imei"""
    ).fetchall()
    conn.close()
    return jsonify([_fila_equipo(r) for r in filas])


@bp.route("/api/monitoreo/equipos", methods=["POST"])
@rol(*ADMIN)
def crear_equipo():
    data = request.get_json(silent=True) or {}
    imei = (data.get("imei") or "").strip()
    if not _RE_IMEI.match(imei):
        return jsonify({"error": "IMEI inválido (solo números/letras, 4 a 32 caracteres)"}), 400
    try:
        bus_id = _bus_id(data.get("bus_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conn = db()
    if conn.execute("SELECT id FROM gps_equipos WHERE imei = ?", (imei,)).fetchone():
        conn.close()
        return jsonify({"error": "Ya hay un equipo registrado con ese IMEI"}), 409
    error = _validar_bus(conn, bus_id)
    if error:
        conn.close()
        return jsonify({"error": error}), 409

    token = nuevo_token()
    ahora = a_bd(ahora_utc())
    conn.execute(
        "INSERT INTO gps_equipos (empresa_id, imei, token_hash, bus_id, notas, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (EMPRESA_POR_DEFECTO, imei, hash_token(token), bus_id,
         (data.get("notas") or "").strip() or None, ahora, ahora),
    )
    # Si ese IMEI estaba esperando en pendientes, ya no hace falta.
    conn.execute("DELETE FROM gps_pendientes WHERE imei = ?", (imei,))
    conn.commit()
    conn.close()
    invalidar_cache_equipo(imei)
    return jsonify({"ok": True, "imei": imei, "token": token}), 201


@bp.route("/api/monitoreo/equipos/<int:equipo_id>", methods=["PUT"])
@rol(*ADMIN)
def editar_equipo(equipo_id):
    data = request.get_json(silent=True) or {}
    conn = db()
    actual = conn.execute("SELECT * FROM gps_equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not actual:
        conn.close()
        return jsonify({"error": "Equipo no encontrado"}), 404
    actual = dict(actual)

    try:
        bus_id = _bus_id(data["bus_id"]) if "bus_id" in data else actual["bus_id"]
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    activo = (1 if data["activo"] else 0) if "activo" in data else actual["activo"]
    notas = ((data.get("notas") or "").strip() or None) if "notas" in data else actual["notas"]

    if activo:
        error = _validar_bus(conn, bus_id, excluir_equipo=equipo_id)
        if error:
            conn.close()
            return jsonify({"error": error}), 409

    conn.execute(
        "UPDATE gps_equipos SET bus_id = ?, activo = ?, notas = ?, updated_at = ? WHERE id = ?",
        (bus_id, activo, notas, a_bd(ahora_utc()), equipo_id),
    )
    conn.commit()
    conn.close()
    invalidar_cache_equipo(actual["imei"])
    return jsonify({"ok": True})


@bp.route("/api/monitoreo/equipos/<int:equipo_id>/token", methods=["POST"])
@rol(*ADMIN)
def regenerar_token(equipo_id):
    """El token anterior deja de servir (en máx. 60 s por la caché de ingesta)."""
    conn = db()
    fila = conn.execute("SELECT imei FROM gps_equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not fila:
        conn.close()
        return jsonify({"error": "Equipo no encontrado"}), 404
    token = nuevo_token()
    conn.execute("UPDATE gps_equipos SET token_hash = ?, updated_at = ? WHERE id = ?",
                 (hash_token(token), a_bd(ahora_utc()), equipo_id))
    conn.commit()
    conn.close()
    invalidar_cache_equipo(dict(fila)["imei"])
    return jsonify({"ok": True, "imei": dict(fila)["imei"], "token": token})


@bp.route("/api/monitoreo/equipos/<int:equipo_id>/posiciones", methods=["GET"])
@rol(*ADMIN)
def posiciones_equipo(equipo_id):
    """Últimos paquetes recibidos de un equipo (para verificar la instalación)."""
    try:
        limite = max(1, min(int(request.args.get("limite", 30)), 200))
    except ValueError:
        limite = 30
    desde = a_bd(ahora_utc() - timedelta(days=7))   # acota las particiones a leer
    conn = db()
    filas = conn.execute(
        """SELECT lat, lon, velocidad_kmh, rumbo, precision_m, satelites, fix,
                  hora_gps, recibido_at
             FROM gps_posiciones
            WHERE equipo_id = ? AND recibido_at >= ?
         ORDER BY recibido_at DESC, id DESC
            LIMIT ?""",
        (equipo_id, desde, limite),
    ).fetchall()
    conn.close()
    out = []
    for r in filas:
        r = dict(r)
        hg, rc = r["hora_gps"], r["recibido_at"]
        r["hora_gps"], r["recibido_at"] = iso(hg), iso(rc)
        dg, dr = desde_bd(hg), desde_bd(rc)
        r["desfase_s"] = int((dr - dg).total_seconds()) if dg and dr else None
        out.append(r)
    return jsonify(out)


# ── Pendientes ──

@bp.route("/api/monitoreo/pendientes", methods=["GET"])
@rol(*ADMIN)
def listar_pendientes():
    conn = db()
    filas = conn.execute(
        "SELECT imei, token_hash IS NOT NULL AS trae_token, primer_visto_at, ultimo_visto_at, "
        "paquetes, ultimo_payload, ultima_ip FROM gps_pendientes ORDER BY ultimo_visto_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in filas:
        r = dict(r)
        r["trae_token"] = bool(r["trae_token"])
        r["primer_visto_at"] = iso(r["primer_visto_at"])
        r["ultimo_visto_at"] = iso(r["ultimo_visto_at"])
        out.append(r)
    return jsonify(out)


@bp.route("/api/monitoreo/pendientes/<imei>/asignar", methods=["POST"])
@rol(*ADMIN)
def asignar_pendiente(imei):
    """Registra el IMEI pendiente y lo asigna a un bus. Si el equipo ya viene
    mandando un token, se adopta ese mismo (no hay que reconfigurarlo);
    si no trae token, se genera uno y hay que ponerlo en la URL del equipo."""
    data = request.get_json(silent=True) or {}
    try:
        bus_id = _bus_id(data.get("bus_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conn = db()
    pend = conn.execute("SELECT * FROM gps_pendientes WHERE imei = ?", (imei,)).fetchone()
    if not pend:
        conn.close()
        return jsonify({"error": "Ese IMEI ya no está en pendientes"}), 404
    pend = dict(pend)
    if conn.execute("SELECT id FROM gps_equipos WHERE imei = ?", (imei,)).fetchone():
        conn.close()
        return jsonify({"error": "Ya hay un equipo registrado con ese IMEI"}), 409
    error = _validar_bus(conn, bus_id)
    if error:
        conn.close()
        return jsonify({"error": error}), 409

    token = None
    token_hash = pend["token_hash"]
    if not token_hash:
        token = nuevo_token()
        token_hash = hash_token(token)
    ahora = a_bd(ahora_utc())
    conn.execute(
        "INSERT INTO gps_equipos (empresa_id, imei, token_hash, bus_id, notas, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (EMPRESA_POR_DEFECTO, imei, token_hash, bus_id,
         (data.get("notas") or "").strip() or None, ahora, ahora),
    )
    conn.execute("DELETE FROM gps_pendientes WHERE imei = ?", (imei,))
    conn.commit()
    conn.close()
    invalidar_cache_equipo(imei)
    return jsonify({"ok": True, "imei": imei, "token": token, "token_adoptado": token is None}), 201


@bp.route("/api/monitoreo/pendientes/<imei>", methods=["DELETE"])
@rol(*ADMIN)
def descartar_pendiente(imei):
    conn = db()
    conn.execute("DELETE FROM gps_pendientes WHERE imei = ?", (imei,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ── Mantenimiento diario (cron de Vercel) ──

def cron_monitoreo():
    """Crea las particiones de posiciones del mes actual y los 2 siguientes."""
    conn = db()
    try:
        creadas = asegurar_particiones(conn)
    finally:
        conn.close()
    return {"ok": True, "particiones": creadas}
