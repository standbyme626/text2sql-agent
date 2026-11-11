# -*- coding: utf-8 -*-
"""提示词版本管理：system / insight / guard 三类提示词可版本化、可回滚。

文件放 knowledge/prompts/*.md（跟知识库一样可进 Git、可 review）：
    ---
    kind: system_append | insight | guard
    active: true
    name: 口径优先版
    created: '2026-11-12T10:00:00'
    ---
    正文内容
- system_append：追加到 system prompt 末尾
- insight：整体替换默认洞察提示词
- guard：追加到拒答/护栏规则末尾
"""
from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import settings

KINDS = ("system_append", "insight", "guard")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def prompts_dir() -> Path:
    return Path(settings.KNOWLEDGE_DIR) / "prompts"


def _ensure() -> None:
    p = prompts_dir()
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass


def _parse(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""
    text = raw.lstrip("\ufeff")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                import yaml  # type: ignore
                meta = yaml.safe_load(parts[1]) or {}
            except Exception:  # noqa: BLE001
                meta = {}
            body = parts[2].strip()
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def versions() -> list[dict]:
    d = prompts_dir()
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.md")):
        meta, body = _parse(f)
        out.append({
            "id": f.stem,
            "kind": str(meta.get("kind") or "system_append"),
            "name": str(meta.get("name") or f.stem),
            "active": bool(meta.get("active", False)),
            "created": str(meta.get("created") or ""),
            "size": len(body),
            "body": body,
        })
    return out


def active_of(kind: str) -> dict | None:
    for v in versions():
        if v["kind"] == kind and v["active"]:
            return v
    return None


def overlay(kind: str) -> str:
    """取当前生效版本的正文（无则空串）。"""
    v = active_of(kind)
    return v["body"] if v else ""


def _write(path: Path, content: str) -> None:
    _ensure()
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def add(kind: str, name: str, body: str, activate: bool = True,
        actor: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind 只能是 {', '.join(KINDS)}")
    body = (body or "").strip()
    if len(body) < 5:
        raise ValueError("提示词内容太短")
    import yaml  # type: ignore
    kid = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    meta = {"kind": kind, "name": name or kind, "active": bool(activate),
            "created": datetime.now().isoformat(timespec="seconds")}
    content = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip() \
        + "\n---\n\n" + body + "\n"
    _ensure()
    _write(prompts_dir() / f"{kid}.md", content)
    if activate:
        set_active(kind, kid, actor=actor)
    from . import audit
    audit.record(actor, "prompt.create", kid,
                 before={}, after={"kind": kind, "name": meta["name"], "active": activate},
                 effective=True)
    return {"id": kid, **meta}


def set_active(kind: str, kid: str, actor: str = "", _write_only: bool = False) -> dict:
    """把某个版本设为该类型的生效版本（同类互斥）。"""
    d = prompts_dir()
    target = d / f"{kid}.md"
    if not target.is_file():
        raise ValueError("提示词版本不存在")
    if not kind:
        meta, _ = _parse(target)
        kind = str(meta.get("kind") or "system_append")
        if kind not in KINDS:
            raise ValueError("提示词版本类型无效")
    for f in d.glob("*.md"):
        meta, body = _parse(f)
        if str(meta.get("kind")) != kind:
            continue
        want = (f.stem == kid)
        meta["active"] = want
        import yaml  # type: ignore
        content = "---\n" + yaml.safe_dump(
            meta, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n" + body + "\n"
        _write(f, content)
    from . import audit
    audit.record(actor, "prompt.activate", kid,
                 before={}, after={"kind": kind, "active": True}, effective=True)
    return {"id": kid, "kind": kind, "active": True}


def delete(kid: str, actor: str = "") -> bool:
    d = prompts_dir()
    if not _ID_RE.match(kid or ""):
        return False
    f = (d / f"{kid}.md").resolve()
    if not f.is_relative_to(d.resolve()) or not f.is_file():
        return False
    f.unlink()
    from . import audit
    audit.record(actor, "prompt.delete", kid, before={"id": kid}, after={}, effective=True)
    return True


def seed_defaults() -> None:
    """首次使用时放一份示例（可删）。"""
    d = prompts_dir()
    if d.exists() and any(d.glob("*.md")):
        return
    try:
        add("system_append", "示例：口径优先",
            "【团队口径提醒】涉及销售额与有效成交时，先用 list_metrics 拿口径，再写 SQL。",
            activate=False, actor="system")
    except Exception:  # noqa: BLE001
        pass
