#!/usr/bin/env bash
# 在应用服务器上执行：从本机已有凭据文件生成项目 .env，密钥值全程不回显。
#
# 凭据文件格式（KEY=VALUE，允许 # 注释行）：
#   <CRED_DIR>/modelscope.env      MODELSCOPE_API_KEY=ms-xxx
#   <CRED_DIR>/siliconflow.env     SILICONFLOW_API_KEY=sk-xxx
# CRED_DIR 默认 $HOME/.config/text2sql/credentials
#
# 用法：
#   bash deploy/gen_env.sh
#   CRED_DIR=/secure/creds bash deploy/gen_env.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env

CRED_DIR="${CRED_DIR:-$HOME/.config/text2sql/credentials}"
export CRED_DIR

python3 - <<'PY'
import os
import re
from pathlib import Path

cred_dir = Path(os.environ["CRED_DIR"])


def val(path, names):
    p = Path(path)
    if not p.exists():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        if k.strip() in names:
            return v.strip().strip('"').strip("'")
    return ""


ms = val(cred_dir / "modelscope.env", {"MODELSCOPE_API_KEY"})
sf = val(cred_dir / "siliconflow.env", {"SILICONFLOW_API_KEY", "API_KEY"})

p = Path(".env")
text = p.read_text(encoding="utf-8")
for key, value in (("MODELSCOPE_API_KEY", ms), ("SILICONFLOW_API_KEY", sf)):
    if value:
        text = re.sub(rf"(?m)^{re.escape(key)}=.*$",
                      lambda m, k=key, v=value: f"{k}={v}", text)
        print(f"  已注入 {key}（长度 {len(value)}，值未回显）")
    else:
        print(f"  ⚠ 未找到 {key}（查找目录 {cred_dir}），请手动填入 .env")
p.write_text(text, encoding="utf-8")
os.chmod(p, 0o600)
PY

echo "完成：.env 权限已设为 600"
echo "提醒：API key 只用于本项目所需的文本生成与 embedding 调用。"
