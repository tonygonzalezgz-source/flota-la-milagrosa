"""Adapters por proveedor de LLM. Cada uno expone una clase con:

    def stream(self, system, messages, tools, ctx) -> generator de eventos

donde cada evento es un dict:
    {"type": "text",  "text": "..."}   fragmento de texto (streaming)
    {"type": "tool",  "name": "..."}   aviso de que se ejecutó una tool
    {"type": "done"}                    fin de la respuesta
"""
