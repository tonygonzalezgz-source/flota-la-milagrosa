"""Recaudo: liquidación del dinero que entrega cada conductor por el día del bus.

Los datos operativos (conductor, ruta, viajes, registradora) vienen del despacho
del mismo (bus, fecha); el recaudo agrega la tarifa, la liquidación y lo que el
conductor entregó. Cada recaudador cierra su caja (caja.py) con el efectivo que
entrega a la transportadora."""
from flask import Blueprint

bp = Blueprint("recaudo", __name__)

from .comun import configurar  # noqa: E402,F401
from .esquema import migrar  # noqa: E402,F401
from . import endpoints, caja, contable  # noqa: E402,F401  (registran sus rutas en bp)
