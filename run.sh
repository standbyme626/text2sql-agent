#!/usr/bin/env bash
# 一键启动：建 venv → 装依赖 → 建库 → 建向量索引 → 构建前端（如缺失）→ 起服务
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  echo "[1/5] 创建虚拟环境并安装依赖…"
  python3 -m venv .venv
  "$PY" -m pip install -q -r backend/requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "  ⚠ 已生成 .env，请填入 MODELSCOPE_API_KEY / SILICONFLOW_API_KEY；"
  echo "    只想先看界面可在 .env 设 MOCK_MODE=true"
fi

if [ ! -f backend/data/ecommerce.db ]; then
  echo "[2/5] 初始化 50 张电商表与模拟数据…"
  "$PY" backend/scripts/init_db.py
fi

if [ ! -f backend/data/schema_index.json ]; then
  echo "[3/5] 构建向量索引…"
  "$PY" backend/scripts/build_index.py || \
    echo "  ⚠ 索引未生成（多半是没配 embedding key），将自动降级为关键词选表"
fi

if [ ! -f backend/static/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "[4/5] 构建前端…"
    ( cd frontend && npm install --no-fund --no-audit && npm run build )
    rm -rf backend/static/* && cp -r frontend/dist/. backend/static/
  else
    echo "[4/5] ⚠ 未安装 npm，跳过前端构建；页面会提示「前端尚未构建」"
  fi
fi

# 非回环地址必须鉴权，否则服务会拒绝启动（见 README 安全设计）
if [ "${HOST:-127.0.0.1}" != "127.0.0.1" ] && ! grep -q '^AUTH_PASSWORD=.\+' .env 2>/dev/null; then
  echo "  ⚠ HOST=${HOST} 但 .env 未设 AUTH_PASSWORD，服务将拒绝启动"
fi

echo "[5/5] 启动服务: http://${HOST:-127.0.0.1}:${PORT:-3388}"
exec "$PY" -m uvicorn app.main:app --app-dir backend \
  --host "${HOST:-127.0.0.1}" --port "${PORT:-3388}"
