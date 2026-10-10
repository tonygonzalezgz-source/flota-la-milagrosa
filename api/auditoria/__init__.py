"""Historial de modificaciones (auditoría): quién cambió qué y cuándo en
Catálogo y Recaudo. Las filas no se pueden editar ni borrar, ni siquiera por el
Administrador: la base de datos lo impide con triggers."""
from flask import Blueprint

bp = Blueprint("auditoria", __name__)

from .comun import configurar  # noqa: E402,F401
from .esquema import migrar  # noqa: E402,F401
from .registro import describir, diferencias, pesos, registrar  # noqa: E402,F401
from . import endpoints  # noqa: E402,F401  (registra sus rutas en bp)
