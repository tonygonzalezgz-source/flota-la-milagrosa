"""Dependencias que app.py le inyecta al módulo de auditoría con `configurar()`
(mismo patrón que Monitoreo y Recaudo, para evitar la importación circular)."""
from functools import wraps

EMPRESA_POR_DEFECTO = 1

_deps = {}


def configurar(get_db, require_role, database_url):
    _deps.update(get_db=get_db, require_role=require_role, database_url=database_url or "")


def db():
    return _deps["get_db"]()


def es_pg():
    return bool(_deps.get("database_url"))


def rol(*roles):
    """Igual que require_role de app.py, resuelto en tiempo de request."""
    def wrapper(f):
        @wraps(f)
        def inner(*args, **kwargs):
            return _deps["require_role"](*roles)(f)(*args, **kwargs)
        return inner
    return wrapper
