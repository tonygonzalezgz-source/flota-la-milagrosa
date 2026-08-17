"""Registro de tools disponibles para el chatbot.

Cada tool es un dict con: name, description, parameters (JSON Schema) y run
(callable(args: dict, ctx: dict) -> dict). Los adapters de cada proveedor
convierten esta definición neutral a su propio formato.
"""
from ai.tools import estado_actual_bus

# Lista de tools expuestas al LLM (Fase 1: una sola).
REGISTRY = [
    estado_actual_bus.TOOL,
]

# Mapa nombre → tool, para ejecutar por nombre desde los adapters.
BY_NAME = {t["name"]: t for t in REGISTRY}
