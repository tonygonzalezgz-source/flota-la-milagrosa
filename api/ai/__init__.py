"""Paquete del chatbot con IA de BusControl (Fase 1).

Contiene:
  - provider.py            → selecciona el proveedor de LLM según AI_PROVIDER
  - adapters/              → un adapter por proveedor (Anthropic, Google)
  - tools/                 → herramientas (tool calling) que consultan la BD

El endpoint /api/chat (en api/app.py) importa este paquete de forma perezosa.
"""
