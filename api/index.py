"""
Entry point para Vercel Serverless (Python).
Vercel detecta el WSGI `app` y lo invoca por cada request.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, init_db  # noqa: E402,F401

# Ejecuta migraciones/seed una sola vez por cold-start del serverless.
# Todas las operaciones son idempotentes (IF NOT EXISTS / seed solo si vacío).
try:
    init_db()
except Exception as e:
    print(f"[init_db] warning: {e}")

