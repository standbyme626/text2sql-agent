# -*- coding: utf-8 -*-
"""把 certbot 的 --nginx 续期方式改成 webroot + installer=None。

为什么：--nginx installer 每次 renew 都会往 server 块注入 SSL / 301 指令，
会改写我们手工维护的 nginx-site.conf（可能让 nginx -t 失败、SSE 的
proxy_buffering off 丢失）。改成 webroot 后续期完全不碰 nginx 配置。

用法： python3 fix-renewal.py <domain>
"""
from __future__ import annotations

import datetime
import os
import shutil
import sys
from pathlib import Path

if len(sys.argv) < 2 or not sys.argv[1].strip():
    print("用法：python3 fix-renewal.py <domain>")
    raise SystemExit(2)

domain = sys.argv[1].strip()
conf = Path(f"/etc/letsencrypt/renewal/{domain}.conf")
webroot = os.getenv("WEBROOT", "/var/www/html")
backup_dir = Path(os.getenv("BACKUP_DIR", "/root/text2sql-nginx-backup"))

if not conf.exists():
    print(f"SKIP: {conf} 不存在")
    raise SystemExit(0)

raw = conf.read_text(encoding="utf-8")
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
shutil.copy(conf, backup_dir / f"renewal.{stamp}.bak")

lines = raw.splitlines()
out = []
for line in lines:
    s = line.strip()
    if s.startswith("authenticator"):
        out.append("authenticator = webroot")
    elif s.startswith("installer"):
        out.append("installer = None")
    elif (s.startswith("webroot_path") or s.startswith("renew_hook")
          or s.startswith("[[webroot_map]]") or s.startswith(f"{domain} =")):
        continue
    else:
        out.append(line)

# 去掉尾部空行，把新键追加到 [renewalparams] 段末尾，再追加独立的 webroot_map 段
while out and not out[-1].strip():
    out.pop()
text = "\n".join(out) + "\n"
if "webroot_path" not in text:
    text += f"webroot_path = {webroot}\n"
if "renew_hook" not in text:
    text += "renew_hook = systemctl reload nginx\n"
text += f"\n[[webroot_map]]\n{domain} = {webroot}\n"

conf.write_text(text, encoding="utf-8")
Path(webroot, ".well-known", "acme-challenge").mkdir(parents=True, exist_ok=True)
print(f"OK: {conf} → authenticator=webroot, installer=None, webroot_map 已写入")
