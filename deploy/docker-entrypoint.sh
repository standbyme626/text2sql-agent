#!/bin/sh
set -e
cd /app

if [ ! -f backend/data/ecommerce.db ]; then
  echo "[entrypoint] 首次启动，初始化 50 张电商表…"
  python backend/scripts/init_db.py
fi

echo "[entrypoint] 启动 ${HOST:-0.0.0.0}:${PORT:-3388}"
exec python -m uvicorn app.main:app \
  --app-dir backend \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-3388}"
