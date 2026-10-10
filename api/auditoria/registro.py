"""Anotar cambios en el historial.

`registrar()` se llama dentro de la misma transacción del cambio y ANTES del
commit: si la anotación falla, el cambio tampoco se guarda (un cambio sin rastro
no debe quedar en la base). Nunca se anotan contraseñas.
"""
import json
from datetime import datetime, timezone

from flask import request

from .comun import EMPRESA_POR_DEFECTO, es_pg

_SENSIBLES = {"password", "contrasena", "token", "token_hash"}


def _ahora():
    dt = datetime.now(timezone.utc)
    return dt if es_pg() else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    ip = fwd.split(",")[0].strip() or request.remote_addr or ""
    return ip[:64] or None


def registrar(conn, modulo, entidad, entidad_id, accion, descripcion, cambios=None):
    """Agrega una fila al historial con el usuario del token (copia de su nombre y rol)."""
    uid = getattr(request, "jwt_user_id", None)
    usuario = {}
    if uid:
        fila = conn.execute(
            "SELECT nombre, username, rol FROM usuarios WHERE id = ?", (uid,)
        ).fetchone()
        usuario = dict(fila) if fila else {}
    if isinstance(cambios, dict):
        cambios = {k: v for k, v in cambios.items() if k not in _SENSIBLES}
    conn.execute(
        """INSERT INTO auditoria
               (empresa_id, creado_at, usuario_id, usuario_nombre, usuario_login, usuario_rol,
                modulo, entidad, entidad_id, accion, descripcion, cambios, ip)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (EMPRESA_POR_DEFECTO, _ahora(), uid, usuario.get("nombre"), usuario.get("username"),
         usuario.get("rol") or getattr(request, "jwt_user_rol", None),
         modulo, entidad, None if entidad_id is None else str(entidad_id), accion,
         (descripcion or "")[:2000],
         json.dumps(cambios, ensure_ascii=False, default=str) if cambios else None,
         _ip()),
    )


def _norm(v):
    """Normaliza para comparar: '' = None, 1.0 = 1, fechas a ISO."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def diferencias(antes, despues, campos):
    """{campo: [antes, después]} solo con los campos de `campos` que vienen en
    `despues` y cambiaron. Compara como texto para no confundir 1 con '1'."""
    out = {}
    for c in campos:
        if c not in despues or c in _SENSIBLES:
            continue
        a, d = _norm(antes.get(c)), _norm(despues.get(c))
        if (a is None) != (d is None) or (a is not None and str(a) != str(d)):
            out[c] = [a, d]
    return out


def _valor(v):
    if v is None:
        return "—"
    return str(v)


def describir(cambios, etiquetas=None):
    """'Placa: ABC123 → ABC124; Estado: activo → inactivo'."""
    etiquetas = etiquetas or {}
    return "; ".join(
        f"{etiquetas.get(c, c)}: {_valor(a)} → {_valor(d)}" for c, (a, d) in cambios.items()
    )


def pesos(n):
    """12345 → '$12.345' (formato colombiano)."""
    n = int(round(n or 0))
    signo = "-" if n < 0 else ""
    return f"{signo}${abs(n):,}".replace(",", ".")
