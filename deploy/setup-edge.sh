#!/usr/bin/env bash
# ============================================================================
# 边缘服务器（公网入口）上线脚本 —— 在装有 nginx + certbot 的那台机器上执行
#
# 前置：
#   1) 应用服务器已跑 text2sql.service + text2sql-tunnel.service（127.0.0.1:3388 隧道已通）
#   2) 三个文件已上传到本机 /tmp/text2sql-deploy/
#      nginx-bootstrap.conf · nginx-site.conf · fix-renewal.py
#   3) 域名 A 记录已指向本机公网 IP
#
# 环境变量：
#   DOMAIN      必填，站点域名（如 sql.example.com）
#   LE_EMAIL    Let's Encrypt 通知邮箱，默认 admin@example.com
#   EDGE_IP     可选，填了会校验域名是否解析到该 IP
#   APP_TOKEN   可选，提供时额外验证「带 token 200」
#   WANT_BASIC  置 1 时启用 nginx 第二层 Basic（默认关闭；凭据须手工交互创建）
#   SKIP_CERT   置 1 时跳过签发/续期改造，只更新反代配置（证书已存在时用）
#
# 执行：
#   DOMAIN=sql.example.com sudo -E bash /tmp/text2sql-deploy/setup-edge.sh
# ============================================================================
set -euo pipefail

DOMAIN="${DOMAIN:?必须设置 DOMAIN，例如 DOMAIN=sql.example.com}"
PORT="${PORT:-3388}"
SRC="${SRC:-/tmp/text2sql-deploy}"
CONF="/etc/nginx/sites-enabled/${DOMAIN}"
AVAIL="/etc/nginx/sites-available/${DOMAIN}"
HTPASSWD="/etc/nginx/.htpasswd-text2sql"
RENEW="/etc/letsencrypt/renewal/${DOMAIN}.conf"
LE_EMAIL="${LE_EMAIL:-admin@example.com}"
BACKUP_DIR="${BACKUP_DIR:-/root/text2sql-nginx-backup}"

echo "== 0. 前置检查 =="
for cmd in nginx certbot curl; do
  command -v "$cmd" >/dev/null || { echo "缺少命令：$cmd"; exit 1; }
done
if [ -n "${EDGE_IP:-}" ]; then
  getent hosts "$DOMAIN" | grep -q "$EDGE_IP" || {
    echo "域名 $DOMAIN 未解析到 $EDGE_IP，请先检查 DNS 记录"; exit 1;
  }
else
  getent hosts "$DOMAIN" >/dev/null || { echo "域名 $DOMAIN 未解析，请先配置 DNS"; exit 1; }
fi
for f in nginx-bootstrap.conf nginx-site.conf fix-renewal.py; do
  [ -f "$SRC/$f" ] || { echo "缺少配置文件：$SRC/$f"; exit 1; }
done
echo "  DNS ✓  certbot ✓  nginx ✓  domain=$DOMAIN"

echo "== 1. 可选第二层 Basic（默认关闭，不再用 htpasswd -b 把密码写进 argv）=="
if [ "${WANT_BASIC:-0}" = "1" ]; then
  if [ ! -f "$HTPASSWD" ]; then
    echo "  请先在本机交互执行（密码不经过命令行）："
    echo "    htpasswd -c $HTPASSWD <用户名>"
    echo "    chown root:www-data $HTPASSWD && chmod 640 $HTPASSWD"
    echo "  然后重跑本脚本；并取消 nginx-site.conf 里两行 auth_basic 注释。"
    exit 1
  fi
  chown root:www-data "$HTPASSWD" 2>/dev/null || true
  chmod 640 "$HTPASSWD"   # nginx worker 是 www-data，600 会让带凭据请求 500
  echo "  凭据文件权限已归一：root:www-data 640"
else
  echo "  应用层登录已足够，跳过 Basic 凭据创建"
fi

echo "== 2. 备份现有配置（绝不能留在 sites-enabled/ 内）=="
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d%H%M%S)"
for f in "$CONF" "$AVAIL"; do
  [ -f "$f" ] && cp "$f" "${BACKUP_DIR}/$(basename "$f").${STAMP}.bak" || true
done
echo "  备份目录：$BACKUP_DIR"

if [ "${SKIP_CERT:-0}" != "1" ] && [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  echo "== 3. 临时 80 配置，供 http-01 验证 =="
  sed "s/sql\.example\.com/${DOMAIN}/g" "$SRC/nginx-bootstrap.conf" > "$AVAIL"
  ln -sf "$AVAIL" "$CONF"
  nginx -t
  systemctl reload nginx
  echo "== 4. 签发证书（首次偶发 secondary validation timeout，最多 3 次）=="
  ok=0
  for i in 1 2 3; do
    if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        -m "$LE_EMAIL" --no-redirect; then
      ok=1; break
    fi
    echo "  第 $i 次签发失败，10 秒后重试…"
    sleep 10
  done
  [ "$ok" -eq 1 ] || { echo "证书签发失败，停止（保留 bootstrap 配置）"; exit 1; }
else
  echo "== 3-4. 证书已存在或指定 SKIP_CERT，跳过签发 =="
fi
[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ] || { echo "证书路径异常，停止"; exit 1; }

echo "== 5. 覆盖为最终反代配置 =="
sed "s/sql\.example\.com/${DOMAIN}/g" "$SRC/nginx-site.conf" > "$AVAIL"
ln -sf "$AVAIL" "$CONF"
nginx -t
systemctl reload nginx
echo "  最终配置已生效（proxy_buffering off 保留，SSE 可用）"

echo "== 6. 保护 certbot 续期，避免改写手工配置 =="
# --nginx installer 会在每次 renew 时往 server 块注入 SSL/301 指令，
# 与手工配置冲突甚至让 nginx -t 失败。改为 webroot + installer=None。
if [ -f "$RENEW" ]; then
  # 用 Python 重写 INI，sed 直接插入会把 [[webroot_map]] 放错段、破坏后续键
  python3 "$SRC/fix-renewal.py" "$DOMAIN"
  echo "  续期方式：webroot + installer=None + reload hook"
  if certbot renew --dry-run --cert-name "$DOMAIN" >/dev/null 2>&1; then
    echo "  renew --dry-run ✓"
  else
    echo "  ⚠️ renew --dry-run 未通过（不影响当前服务），请手工检查："
    echo "     certbot renew --dry-run --cert-name $DOMAIN"
  fi
else
  echo "  未找到 $RENEW，跳过（首次签发后应存在）"
fi

echo "== 7. 验证（失败即退出，不再只打警告）=="
code_home=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN/" || true)
echo "  首页 $DOMAIN/ → HTTP $code_home（应为 200，登录页可见）"
[ "$code_home" = "200" ] || { echo "  ✗ 首页不可达"; exit 1; }

code_api=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN/api/meta" || true)
echo "  未登录 /api/meta → HTTP $code_api（应为 401，鉴权生效）"
[ "$code_api" = "401" ] || { echo "  ✗ 鉴权未生效，请检查应用层 AUTH_PASSWORD"; exit 1; }

if [ -n "${APP_TOKEN:-}" ]; then
  code_tok=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-App-Token: $APP_TOKEN" "https://$DOMAIN/api/meta" || true)
  echo "  带 token /api/meta → HTTP $code_tok（应为 200）"
  [ "$code_tok" = "200" ] || { echo "  ✗ 带 token 仍不可访问"; exit 1; }
else
  echo "  未提供 APP_TOKEN，跳过带 token 验证（可用登录接口取 token 后手工测）"
fi

echo
echo "== 完成 =="
echo "  · 应用侧：systemctl is-active text2sql.service text2sql-tunnel.service"
echo "  · 应用侧 .env 必须设 AUTH_PASSWORD，否则服务会拒绝启动"
echo "  · 备份在 ${BACKUP_DIR}/"
echo "  · 若本机还承载其他站点，改配置前请先取得机器主人授权"
