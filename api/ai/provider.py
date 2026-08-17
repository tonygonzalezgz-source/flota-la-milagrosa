"""Selección del proveedor de LLM según la variable de entorno AI_PROVIDER.

    AI_PROVIDER=anthropic  → Claude (SDK anthropic)
    AI_PROVIDER=google     → Gemini (SDK google-genai)  [default]

Ambos adapters exponen la misma interfaz `stream(system, messages, tools, ctx)`,
así se puede intercambiar el proveedor sin tocar el endpoint.
"""
import os


def get_provider():
    name = (os.environ.get("AI_PROVIDER") or "google").strip().lower()
    if name == "anthropic":
        from ai.adapters.anthropic_adapter import AnthropicProvider
        return AnthropicProvider()
    if name == "google":
        from ai.adapters.google_adapter import GoogleProvider
        return GoogleProvider()
    raise ValueError(
        f"AI_PROVIDER no reconocido: {name!r} (usa 'anthropic' o 'google')."
    )


# System prompt del asistente (español, breve, rol de operación de flota).
SYSTEM_PROMPT = (
    "Eres el asistente de BusControl, la plataforma de operación de la flota de "
    "transporte La Milagrosa. Ayudas a operadores y propietarios a consultar el "
    "estado de sus buses de forma clara y concisa.\n"
    "Usa la herramienta `estado_actual_bus` cuando pregunten por el estado, la "
    "ruta, el conductor o el despacho de un bus identificándolo por su número "
    "interno.\n"
    "Responde siempre en español, breve y directo. Si la herramienta indica que "
    "no hay acceso al bus o que no hay datos para hoy, explícalo con naturalidad "
    "y no inventes información."
)
