"""Arranque de desarrollo local: fuerza SQLite aunque el entorno tenga DATABASE_URL.

Uso: python3 api/dev_server.py  (API en http://localhost:8001, BD api/flota.db)
"""
import os

# Antes de importar app: load_dotenv() no pisa variables ya definidas,
# así que fijarla vacía bloquea el DATABASE_URL de cualquier .env cercano.
os.environ["DATABASE_URL"] = ""

import app  # noqa: E402

app.init_db()
print("[API dev] SQLite local — http://localhost:8001")
app.app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="0.0.0.0", port=8001)
