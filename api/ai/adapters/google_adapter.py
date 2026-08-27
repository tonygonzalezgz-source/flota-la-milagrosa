"""Adapter para Gemini vía el SDK oficial `google-genai`.

Implementa el loop de streaming + function calling: transmite texto, y cuando
el modelo emite un function_call ejecuta la tool, devuelve el function_response
y continúa la conversación.

Ante un 503 UNAVAILABLE (el modelo saturado por picos de demanda) reintenta con
espera creciente y, si el modelo sigue caído, pasa al siguiente de la cadena de
respaldo. Ver `_model_chain()`.
"""
import os
import random
import time

from ai.tools._common import json_safe

# Cadena de modelos por defecto: un GA estable adelante y dos respaldos con
# mucha capacidad detrás. A propósito NO se usa el alias `gemini-flash-latest`:
# apunta siempre al modelo más nuevo, que es justo el más saturado (503).
# Ojo al mantener esta lista: los modelos 2.5 quedaron cerrados para proyectos
# nuevos (404 "no longer available to new users"), así que la cadena va sobre
# la familia 3.x, con un `lite` al final porque es el que más cupo tiene.
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_FALLBACKS = "gemini-3.7-flash,gemini-3.5-flash-lite"

# Códigos y estados que corresponden a saturación o fallo pasajero: vale la
# pena reintentar el mismo modelo. El resto (400, 401, 403…) es error de
# configuración y reintentarlo solo hace perder tiempo.
_TRANSIENT_CODES = {429, 500, 502, 503, 504}
_TRANSIENT_STATUS = (
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "INTERNAL",
    "DEADLINE_EXCEEDED",
    "ABORTED",
    "OVERLOADED",
)

MSG_SATURADO = (
    "El asistente está saturado en este momento. Espera unos segundos y "
    "vuelve a preguntar."
)


def _es_transitorio(exc):
    """True si el error viene de saturación del modelo y conviene reintentar."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code in _TRANSIENT_CODES
    status = str(getattr(exc, "status", "") or "").upper()
    if status in _TRANSIENT_STATUS:
        return True
    msg = str(exc).upper()
    return any(s in msg for s in _TRANSIENT_STATUS) or "503" in msg or "429" in msg


def _modelo_no_disponible(exc):
    """True si el modelo en sí no existe o el proyecto no lo tiene habilitado.

    Reintentarlo no sirve, pero el siguiente de la cadena sí puede responder:
    es un 404 de ese modelo, no un problema de credencial ni de la petición.
    """
    if getattr(exc, "code", None) == 404:
        return True
    if str(getattr(exc, "status", "") or "").upper() == "NOT_FOUND":
        return True
    msg = str(exc).upper()
    return "404" in msg and ("NOT_FOUND" in msg or "NOT FOUND" in msg)


def _espera(intento):
    """Backoff exponencial con jitter: ~1s, ~2s, ~4s (tope 8s)."""
    return min(8.0, 2.0 ** intento) * (0.75 + random.random() * 0.5)


def _model_chain():
    """Modelos a probar en orden: el principal y sus respaldos.

    GOOGLE_MODEL define el principal; GOOGLE_MODEL_FALLBACKS los respaldos
    separados por coma (déjalo vacío para desactivar el cambio de modelo).
    """
    principal = (os.environ.get("GOOGLE_MODEL") or DEFAULT_MODEL).strip()
    crudos = os.environ.get("GOOGLE_MODEL_FALLBACKS")
    if crudos is None:
        crudos = DEFAULT_FALLBACKS
    cadena = [principal]
    for m in crudos.split(","):
        m = m.strip()
        if m and m not in cadena:
            cadena.append(m)
    return cadena


def _to_gemini_schema(js):
    """Convierte un JSON Schema simple a google.genai.types.Schema."""
    from google.genai import types

    t = (js.get("type") or "object").upper()
    kwargs = {"type": t}
    if js.get("description"):
        kwargs["description"] = js["description"]
    if js.get("enum"):
        kwargs["enum"] = js["enum"]
    if t == "OBJECT":
        props = js.get("properties", {}) or {}
        kwargs["properties"] = {k: _to_gemini_schema(v) for k, v in props.items()}
        if js.get("required"):
            kwargs["required"] = js["required"]
    if t == "ARRAY" and js.get("items"):
        kwargs["items"] = _to_gemini_schema(js["items"])
    return types.Schema(**kwargs)


class GoogleProvider:
    def __init__(self):
        from google import genai  # import perezoso: solo si AI_PROVIDER=google

        api_key = (
            os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self._client = genai.Client(api_key=api_key)
        self._models = _model_chain()
        self._intentos = max(1, int(os.environ.get("GOOGLE_ATTEMPTS_PER_MODEL", "2")))
        # Índice del modelo vigente: una vez que uno responde, los demás turnos
        # de esta misma conversación siguen con él.
        self._idx = 0

    def _turno(self, contents, config, text_parts, fn_parts):
        """Un turno del modelo, con reintentos y cambio de modelo si hace falta.

        Emite los eventos de texto conforme llegan y acumula los Parts en
        `text_parts` / `fn_parts`. Nunca reintenta después de haber emitido
        texto: eso duplicaría la respuesta en pantalla.
        """
        ultimo = None
        for i in range(self._idx, len(self._models)):
            modelo = self._models[i]
            for intento in range(self._intentos):
                emitido = False
                try:
                    for chunk in self._client.models.generate_content_stream(
                        model=modelo, contents=contents, config=config
                    ):
                        cand = chunk.candidates[0] if chunk.candidates else None
                        if not cand or not cand.content or not cand.content.parts:
                            continue
                        for part in cand.content.parts:
                            if getattr(part, "text", None):
                                text_parts.append(part)
                                emitido = True
                                yield {"type": "text", "text": part.text}
                            if getattr(part, "function_call", None):
                                fn_parts.append(part)
                    self._idx = i
                    return
                except Exception as e:
                    ultimo = e
                    if emitido:
                        raise
                    # Turno descartado: se limpia lo acumulado antes de repetir
                    # o de pasar al siguiente modelo.
                    text_parts.clear()
                    fn_parts.clear()
                    if _modelo_no_disponible(e):
                        # El modelo no existe para este proyecto: no se reintenta,
                        # se pasa directo al siguiente de la cadena.
                        print(f"[chat] {modelo} no habilitado para este proyecto: {e}")
                        break
                    if not _es_transitorio(e):
                        raise
                    print(f"[chat] {modelo} no disponible (intento {intento + 1}): {e}")
                    if intento < self._intentos - 1:
                        time.sleep(_espera(intento))
            if i + 1 < len(self._models):
                print(f"[chat] cambiando a modelo de respaldo: {self._models[i + 1]}")
        # Agotada la cadena: si el último fallo no fue saturación (p. ej. ningún
        # modelo habilitado), se propaga tal cual para no mentir en el mensaje.
        if ultimo is not None and not _es_transitorio(ultimo):
            raise ultimo
        raise RuntimeError(MSG_SATURADO) from ultimo

    def stream(self, system, messages, tools, ctx):
        from google.genai import types

        by_name = {t["name"]: t for t in tools}
        decls = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=_to_gemini_schema(t["parameters"]),
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)],
        )

        # Historial en formato Gemini (user ↔ model).
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=m["content"])])
            )

        for _ in range(6):
            text_parts = []   # Parts con texto (preservan thought_signature si viene)
            fn_parts = []     # Parts con function_call (idem; requerido por Gemini 3.x)
            yield from self._turno(contents, config, text_parts, fn_parts)

            if not fn_parts:
                break

            # Turno del modelo: preservar los Parts originales para no perder
            # thought_signature (Gemini 3.x rechaza function calls sin firma).
            contents.append(types.Content(role="model", parts=text_parts + fn_parts))

            # Ejecutar tools y devolver los resultados.
            resp_parts = []
            for part in fn_parts:
                fc = part.function_call
                yield {"type": "tool", "name": fc.name}
                tool = by_name.get(fc.name)
                args = dict(fc.args) if fc.args else {}
                if tool is None:
                    result = {"error": f"Tool desconocida: {fc.name}"}
                else:
                    result = tool["run"](args, ctx)
                resp_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name, response=json_safe(result)
                        )
                    )
                )
            contents.append(types.Content(role="user", parts=resp_parts))

        yield {"type": "done"}
