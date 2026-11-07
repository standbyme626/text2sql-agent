#!/usr/bin/env bash
# 隧道 / 服务健康看门狗：由 deploy/text2sql-watchdog.timer 每 2 分钟调用
#   本机 health 挂了        → 重启 text2sql.service
#   边缘侧隧道端口不通      → 重启 text2sql-tunnel.service
#
# 通过 SSH 别名判断对端连通性，别名可用 EDGE_SSH 覆盖（默认 edge-tunnel）
set -u
LOG_TAG="text2sql-watchdog"
PORT="${PORT:-3388}"
EDGE_SSH="${EDGE_SSH:-edge-tunnel}"

if ! curl -sf --max-time 8 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  logger -t "$LOG_TAG" "本机服务无响应，重启 text2sql.service"
  systemctl restart text2sql.service
  sleep 5
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$EDGE_SSH" \
     "curl -sf --max-time 8 http://127.0.0.1:${PORT}/api/health >/dev/null" >/dev/null 2>&1; then
  logger -t "$LOG_TAG" "边缘侧隧道端口不通，重启 text2sql-tunnel.service"
  systemctl restart text2sql-tunnel.service
fi
