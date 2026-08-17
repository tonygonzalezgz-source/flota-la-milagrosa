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
    "transporte La Milagrosa. Ayudas a administradores y propietarios a "
    "consultar información operativa de sus buses de forma clara y concisa.\n"
    "\n"
    "Tienes 6 herramientas para consultar la base de datos:\n"
    "- `estado_actual_bus(numero)`: estado del día (trabajando/taller/descanso), "
    "ruta y conductor asignados hoy para un bus.\n"
    "- `vencimientos_bus(numero)`: fechas de SOAT, tecnomecánica y tarjeta de "
    "operación de un bus, con días restantes y si están vigentes, por vencer "
    "o vencidas.\n"
    "- `movilidad_bus(numero, dias?)`: vueltas, pasajeros y kilómetros diarios "
    "de un bus en los últimos N días (default 7). Para 'esta semana' usa 7, "
    "'este mes' usa 30.\n"
    "- `vencimientos_flota_proximos(dias?)`: lista los buses con documentos "
    "por vencer o vencidos dentro de N días (default 30). Úsala para "
    "preguntas de panorama tipo '¿qué buses tienen SOAT venciendo esta "
    "semana?'.\n"
    "- `comparativa_movilidad_bus(numero, dias?)`: compara la movilidad de un "
    "bus en los últimos N días vs los N previos. Úsala para preguntas de "
    "comparativa, tendencia o 'por qué movilizó más/menos que antes'. "
    "Aprovecha las `observaciones` para explicar el porqué del cambio.\n"
    "- `comparativa_movilidad_flota(dias?)`: comparativa agregada de toda la "
    "flota visible (admin) o los buses del propietario. Devuelve totales, "
    "deltas y los top 3 que más subieron y bajaron. Úsala para resúmenes "
    "generales tipo 'cómo fue esta semana vs la pasada'.\n"
    "\n"
    "Reglas:\n"
    "- Responde siempre en español, breve y directo.\n"
    "- Si la herramienta indica que no hay acceso al bus (`acceso: false`), "
    "explícalo con naturalidad y no reveles datos de otros buses.\n"
    "- Si no hay datos para el período consultado, dilo tal cual — no inventes."
)
