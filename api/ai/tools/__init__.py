"""Registro de tools disponibles para el chatbot.

Cada tool es un dict con: name, description, parameters (JSON Schema) y run
(callable(args: dict, ctx: dict) -> dict). Los adapters de cada proveedor
convierten esta definición neutral a su propio formato.
"""
from ai.tools import (
    estado_actual_bus,
    vencimientos_bus,
    movilidad_bus,
    vencimientos_flota_proximos,
    comparativa_movilidad_bus,
    comparativa_movilidad_flota,
)

REGISTRY = [
    estado_actual_bus.TOOL,
    vencimientos_bus.TOOL,
    movilidad_bus.TOOL,
    vencimientos_flota_proximos.TOOL,
    comparativa_movilidad_bus.TOOL,
    comparativa_movilidad_flota.TOOL,
]

BY_NAME = {t["name"]: t for t in REGISTRY}
