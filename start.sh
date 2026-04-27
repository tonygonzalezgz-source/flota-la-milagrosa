#!/bin/bash
# ══════════════════════════════════════════
#  La Milagrosa — Levantar servidores
# ══════════════════════════════════════════
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# ── 1. Instalar dependencias Python si faltan ──
if ! python3 -c "import flask" 2>/dev/null; then
  echo "[Setup] Instalando dependencias..."
  pip3 install -r requirements.txt
fi

# ── 2. Crear base de datos si no existe ──
if [ ! -f "api/flota.db" ]; then
  echo "[DB] Creando base de datos por primera vez..."
  python3 api/setup_db.py <<< "s"
fi

# ── 3. Levantar API Flask en background (puerto 5000) ──
echo "[API] Iniciando en http://localhost:8001 ..."
python3 api/app.py &
API_PID=$!

# ── 4. Levantar servidor estático (puerto 3030) ──
echo "[WEB] Iniciando en http://localhost:3030 ..."
echo ""
echo "  Abre: http://localhost:3030"
echo "  Ctrl+C para detener ambos servidores"
echo ""

trap "kill $API_PID 2>/dev/null; exit 0" INT TERM

python3 server.py
