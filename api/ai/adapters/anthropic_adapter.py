"""Adapter para Claude vía el SDK oficial `anthropic`.

Implementa a mano el loop de streaming + tool calling: transmite texto token a
token, y cuando el modelo pide una tool la ejecuta, agrega el resultado a la
conversación y vuelve a transmitir la siguiente respuesta.
"""
import os
import json
import time

from ai.tools._common import json_safe, is_retryable_error, retry_delay_seconds


MAX_RETRIES = 3


class AnthropicProvider:
    def __init__(self):
        import anthropic  # import perezoso: solo si AI_PROVIDER=anthropic
        # El cliente resuelve la credencial de ANTHROPIC_API_KEY.
        self._client = anthropic.Anthropic()
        self._model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        self._max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))

    def stream(self, system, messages, tools, ctx):
        anth_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]
        by_name = {t["name"]: t for t in tools}

        # Historial de la conversación en formato Anthropic.
        conv = [{"role": m["role"], "content": m["content"]} for m in messages]

        # Límite de vueltas para no ciclar indefinidamente sobre tools.
        for _ in range(6):
            # Retry solo si el fallo ocurre ANTES de yield-ear texto al usuario.
            # Si el error es mid-stream reintentar duplicaría contenido.
            text_emitted_this_turn = False
            final = None

            for attempt in range(MAX_RETRIES):
                try:
                    with self._client.messages.stream(
                        model=self._model,
                        max_tokens=self._max_tokens,
                        system=system,
                        messages=conv,
                        tools=anth_tools,
                    ) as stream:
                        for text in stream.text_stream:
                            text_emitted_this_turn = True
                            yield {"type": "text", "text": text}
                        final = stream.get_final_message()
                    break  # éxito, salir del retry loop
                except Exception as e:
                    if (
                        text_emitted_this_turn
                        or not is_retryable_error(e)
                        or attempt == MAX_RETRIES - 1
                    ):
                        raise
                    time.sleep(retry_delay_seconds(attempt))

            if final.stop_reason != "tool_use":
                break

            # Guardar el turno del asistente (incluye los bloques tool_use).
            conv.append({"role": "assistant", "content": final.content})

            tool_results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                yield {"type": "tool", "name": block.name}
                tool = by_name.get(block.name)
                if tool is None:
                    result = {"error": f"Tool desconocida: {block.name}"}
                else:
                    result = tool["run"](dict(block.input), ctx)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(json_safe(result), ensure_ascii=False),
                })

            conv.append({"role": "user", "content": tool_results})

        yield {"type": "done"}
