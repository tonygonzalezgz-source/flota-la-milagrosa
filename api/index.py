"""
Entry point para Vercel Serverless (Python).
Vercel detecta el WSGI `app` y lo invoca por cada request.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app  # noqa: E402,F401
