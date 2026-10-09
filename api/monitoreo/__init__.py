"""Monitoreo de Bus: ingesta GPS de los equipos de los buses, rutas geográficas,
mapa en vivo, motor de eventos/alarmas y reportes."""
from flask import Blueprint

bp = Blueprint("monitoreo", __name__)

from .comun import configurar  # noqa: E402,F401
from .esquema import migrar  # noqa: E402,F401
from . import ingesta, equipos, rutas, vivo, reportes  # noqa: E402,F401  (registran sus rutas en bp)
from .equipos import cron_monitoreo  # noqa: E402,F401
