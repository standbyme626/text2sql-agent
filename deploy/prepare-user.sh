#!/usr/bin/env bash
# ============================================================================
# 应用服务器：把 Text2SQL 从 root 迁到专用低权限用户 text2sql
# 只做授权准备 + 验证，不切换 unit；执行完再由部署方启用新 unit。
#
#   sudo PROJ=/opt/text2sql-agent bash deploy/prepare-user.sh
# ============================================================================
set -euo pipefail

PROJ="${PROJ:-/opt/text2sql-agent}"
USER_NAME="${USER_NAME:-text2sql}"
EDGE_SSH="${EDGE_SSH:-edge-tunnel}"

echo "== 1. 创建账号 =="
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/$USER_NAME" \
          --shell /usr/sbin/nologin "$USER_NAME"
fi
echo "  $(id "$USER_NAME")"

echo "== 2. 项目目录授权 =="
chown -R "$USER_NAME:$USER_NAME" "$PROJ"
chmod 600 "$PROJ/.env"
chmod 700 "$PROJ/backend/data"
chmod 600 "$PROJ/backend/data/.secret_key" 2>/dev/null || true
echo "  .env 600 / data 700 / 目录属主已归一"

echo "== 3. SSH 配置（隧道需要读别名与密钥）=="
mkdir -p "/home/$USER_NAME/.ssh"
for f in config known_hosts id_rsa id_ed25519 id_ecdsa; do
  if [ -f "/root/.ssh/$f" ]; then
    cp "/root/.ssh/$f" "/home/$USER_NAME/.ssh/$f"
  fi
done
chown -R "$USER_NAME:$USER_NAME" "/home/$USER_NAME/.ssh"
chmod 700 "/home/$USER_NAME/.ssh"
chmod 600 "/home/$USER_NAME/.ssh"/* 2>/dev/null || true
echo "  ~/.ssh 700 / 文件 600"

echo "== 4. 以低权限用户验证 =="
as_user() {
  if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
    sudo -u "$USER_NAME" "$@"
  else
    runuser -u "$USER_NAME" -- "$@"
  fi
}
as_user "${PROJ}/.venv/bin/python" -c \
  "import fastapi, uvicorn, httpx; print('  venv 可读:', fastapi.__version__)" || {
    echo "  ✗ venv 不可读"; exit 1;
  }
as_user ssh -G "$EDGE_SSH" >/dev/null 2>&1 \
  && echo "  ssh 别名可解析 ✓" \
  || echo "  ⚠️ ssh -G $EDGE_SSH 不可用，隧道 unit 暂不要切 User"

echo "== 完成 =="
echo "  现在可 cp deploy/text2sql*.service /etc/systemd/system/ && daemon-reload && restart"
echo "  若服务起不来，把 unit 里 User/Group 两行注释掉即可回滚到 root"
