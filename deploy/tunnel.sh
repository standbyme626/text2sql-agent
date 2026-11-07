#!/usr/bin/env bash
# 手动建立反向隧道（不想装 systemd 单元时用）
# 用法：bash deploy/tunnel.sh [端口，默认 3388]
#       EDGE_SSH=my-alias bash deploy/tunnel.sh 3388
set -euo pipefail
PORT="${1:-3388}"
EDGE_SSH="${EDGE_SSH:-edge-tunnel}"
echo "本机 127.0.0.1:${PORT} → ${EDGE_SSH} 127.0.0.1:${PORT}（Ctrl+C 断开）"
exec ssh -o BatchMode=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -N \
  -R "127.0.0.1:${PORT}:127.0.0.1:${PORT}" "$EDGE_SSH"
