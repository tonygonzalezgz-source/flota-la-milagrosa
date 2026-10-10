"""Consulta del historial de modificaciones. Solo lectura: no hay endpoints para
editar ni borrar (y la base de datos lo impide igual)."""
import json
import re
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

from . import bp
from .comun import db, es_pg, rol

ADMIN = ("Administrador",)
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BOGOTA = timedelta(hours=5)   # Colombia es UTC-5 todo el año
_MAX_LIMITE = 200


def _limite_utc(fecha_iso, dias_extra=0):
    """Medianoche de Bogotá de esa fecha (+dias_extra) expresada en UTC."""
    d = date.fromisoformat(fecha_iso) + timedelta(days=dias_extra)
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + _BOGOTA
    return dt if es_pg() else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_utc(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fila(r):
    d = dict(r)
    d["creado_at"] = _iso_utc(d.get("creado_at"))
    try:
        d["cambios"] = json.loads(d["cambios"]) if d.get("cambios") else None
    except (TypeError, ValueError):
        pass
    return d


@bp.route("/api/auditoria", methods=["GET"])
@rol(*ADMIN)
def listar_auditoria():
    """Filtros: desde, hasta (AAAA-MM-DD, hora Bogotá), modulo, usuario_id, q (texto).
    Paginación: limite (máx. 200) y antes_de (id: trae las filas más viejas que esa)."""
    a = request.args
    where, params = [], []

    for clave, extra, op in (("desde", 0, ">="), ("hasta", 1, "<")):
        valor = a.get(clave)
        if valor:
            if not _RE_FECHA.match(valor):
                return jsonify({"error": f"Fecha '{clave}' inválida (use AAAA-MM-DD)"}), 400
            where.append(f"creado_at {op} ?")
            params.append(_limite_utc(valor, extra))
    if a.get("modulo"):
        where.append("modulo = ?")
        params.append(a["modulo"])
    if a.get("usuario_id"):
        try:
            params.append(int(a["usuario_id"]))
        except ValueError:
            return jsonify({"error": "usuario_id inválido"}), 400
        where.append("usuario_id = ?")
    if a.get("q"):
        where.append("LOWER(descripcion) LIKE ?")
        params.append("%" + a["q"].strip().lower() + "%")
    if a.get("antes_de"):
        try:
            params.append(int(a["antes_de"]))
        except ValueError:
            return jsonify({"error": "antes_de inválido"}), 400
        where.append("id < ?")
    try:
        limite = max(1, min(int(a.get("limite", 100)), _MAX_LIMITE))
    except ValueError:
        limite = 100

    sql = "SELECT * FROM auditoria"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY id DESC LIMIT {limite + 1}"

    conn = db()
    filas = conn.execute(sql, params).fetchall()
    conn.close()
    items = [_fila(f) for f in filas[:limite]]
    return jsonify({"items": items, "hay_mas": len(filas) > limite})


@bp.route("/api/auditoria/usuarios", methods=["GET"])
@rol(*ADMIN)
def usuarios_auditoria():
    """Usuarios que aparecen en el historial (para el filtro), con su último nombre."""
    conn = db()
    filas = conn.execute(
        """SELECT usuario_id, MAX(usuario_nombre) AS nombre, MAX(usuario_rol) AS rol, COUNT(*) AS cambios
             FROM auditoria
            WHERE usuario_id IS NOT NULL
         GROUP BY usuario_id
         ORDER BY MAX(usuario_nombre)"""
    ).fetchall()
    conn.close()
    return jsonify([dict(f) for f in filas])
