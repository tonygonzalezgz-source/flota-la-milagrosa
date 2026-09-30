"""Utilidades compartidas del módulo Monitoreo de Bus.

El módulo vive fuera de app.py para no seguir engordándolo; app.py le inyecta
sus dependencias (get_db, require_role, motor de BD) con `configurar()` al
arrancar, lo que evita la importación circular.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from functools import wraps

# Mientras exista una sola empresa, todo lo nuevo queda en la #1 (La Milagrosa).
EMPRESA_POR_DEFECTO = 1

_deps = {}


def configurar(get_db, require_role, database_url):
    _deps.update(get_db=get_db, require_role=require_role, database_url=database_url or "")


def db():
    return _deps["get_db"]()


def es_pg():
    return bool(_deps.get("database_url"))


def database_url():
    return _deps.get("database_url") or ""


def rol(*roles):
    """Igual que require_role de app.py, resuelto en tiempo de request."""
    def wrapper(f):
        @wraps(f)
        def inner(*args, **kwargs):
            return _deps["require_role"](*roles)(f)(*args, **kwargs)
        return inner
    return wrapper


# ── Tiempo: todo se guarda en UTC ──

def ahora_utc():
    return datetime.now(timezone.utc)


def a_bd(dt):
    """datetime aware → valor para la BD (Postgres: datetime; SQLite: ISO 'Z')."""
    if dt is None:
        return None
    if es_pg():
        return dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def desde_bd(v):
    """Valor de BD (datetime o texto ISO) → datetime aware en UTC."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def iso(v):
    """Valor de BD → 'YYYY-MM-DDTHH:MM:SSZ' (UTC). El frontend lo muestra en hora Bogotá."""
    dt = desde_bd(v)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


# ── Tokens de dispositivo: en BD solo se guarda el hash ──

def nuevo_token():
    return secrets.token_hex(16)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_valido(token, token_hash):
    if not token or not token_hash:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)
