"""Adapter para Gemini vía el SDK oficial `google-genai`.

Implementa el loop de streaming + function calling: transmite texto, y cuando
el modelo emite un function_call ejecuta la tool, devuelve el function_response
y continúa la conversación.
"""
import os
import time

from ai.tools._common import json_safe, is_retryable_error, retry_delay_seconds


MAX_RETRIES = 3


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
        self._model = os.environ.get("GOOGLE_MODEL", "gemini-flash-latest")

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
            # Retry solo si el fallo ocurre ANTES de yield-ear texto al usuario.
            # Si el error es mid-stream reintentar duplicaría contenido.
            text_emitted_this_turn = False

            for attempt in range(MAX_RETRIES):
                # Reset por si un intento anterior alcanzó a poblar los arrays
                # antes de fallar sin haber emitido texto (raro pero posible).
                text_parts = []
                fn_parts = []
                try:
                    for chunk in self._client.models.generate_content_stream(
                        model=self._model, contents=contents, config=config
                    ):
                        cand = chunk.candidates[0] if chunk.candidates else None
                        if not cand or not cand.content or not cand.content.parts:
                            continue
                        for part in cand.content.parts:
                            if getattr(part, "text", None):
                                text_parts.append(part)
                                text_emitted_this_turn = True
                                yield {"type": "text", "text": part.text}
                            if getattr(part, "function_call", None):
                                fn_parts.append(part)
                    break  # éxito, salir del retry loop
                except Exception as e:
                    if (
                        text_emitted_this_turn
                        or not is_retryable_error(e)
                        or attempt == MAX_RETRIES - 1
                    ):
                        raise
                    time.sleep(retry_delay_seconds(attempt))

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
