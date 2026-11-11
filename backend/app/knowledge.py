# -*- coding: utf-8 -*-
"""文件知识库：知识写在 markdown 里，检索索引只是派生层。

设计参考 Wren AI 的 context/memory 分层：
- knowledge/sql/*.md   = 已被确认的自然语言 → SQL 样例（可提交、可审计）
- knowledge/rules/*.md = 业务规则（口径、过滤、命名约定）
- 运行时召回 = 关键词重合 + 可用表校验；向量库/qa_history 仍作为隐式记忆
管理员在后台确认一条回答后，才会落成正式样例，避免把错误答案喂回模型。
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from .config import settings

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_cache: dict | None = None
_cache_key: tuple = ()


def _root() -> Path:
    return Path(settings.KNOWLEDGE_DIR)


def _sql_dir() -> Path:
    return _root() / "sql"


def _rules_dir() -> Path:
    return _root() / "rules"


def _ensure() -> None:
    for p in (_root(), _sql_dir(), _rules_dir()):
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass


def _mtime_key() -> tuple:
    out = []
    for p in (_sql_dir(), _rules_dir()):
        try:
            for f in sorted(p.glob("*.md")):
                out.append((str(f), f.stat().st_mtime))
        except OSError:
            pass
    return tuple(out)


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


def _load() -> dict:
    global _cache, _cache_key
    key = _mtime_key()
    if _cache is not None and key == _cache_key:
        return _cache
    examples: list[dict] = []
    rules: list[dict] = []
    for f in sorted(_sql_dir().glob("*.md")):
        meta, body = _parse(f)
        q = str(meta.get("question") or "").strip()
        sql = str(meta.get("sql") or "").strip()
        if not q or not sql:
            continue
        tables = meta.get("tables") or []
        if isinstance(tables, str):
            tables = [t.strip() for t in tables.split(",") if t.strip()]
        examples.append({
            "id": f.stem,
            "question": q,
            "sql": sql,
            "tables": [str(t) for t in tables if str(t).strip()],
            "notes": body[:2000],
            "source": str(meta.get("source") or ""),
            "created": str(meta.get("created") or ""),
            "verified": bool(meta.get("verified", True)),
        })
    for f in sorted(_rules_dir().glob("*.md")):
        meta, body = _parse(f)
        text = body.strip()
        if not text:
            continue
        rules.append({
            "id": f.stem,
            "title": str(meta.get("title") or text.splitlines()[0][:40]),
            "text": text,
            "source": str(meta.get("source") or ""),
            "created": str(meta.get("created") or ""),
        })
    _cache = {"sql": examples, "rules": rules}
    _cache_key = key
    return _cache


def examples() -> list[dict]:
    return _load()["sql"]


def rules() -> list[dict]:
    return _load()["rules"]


def stats() -> dict:
    d = _load()
    return {"sql": len(d["sql"]), "rules": len(d["rules"]),
            "path": str(_root())}


def rules_block(limit: int = 20) -> str:
    items = rules()[:limit]
    if not items:
        return ""
    lines = ["【团队业务规则（knowledge/rules，优先级高于默认口径）】"]
    for r in items:
        text = re.sub(r"\s+", " ", r["text"]).strip()[:240]
        lines.append(f"- {text}")
    return "\n".join(lines) + "\n"


def _grams(s: str) -> set[str]:
    s = (s or "").lower()
    return {s[i:i + 2] for i in range(len(s) - 1) if s[i:i + 2].strip()}


def recall(question: str, k: int = 2,
           allowed_tables: set[str] | None = None) -> list[dict]:
    """关键词召回正式样例；与 qa_history 的向量 few-shot 合并使用。"""
    q = (question or "").strip()
    if not q or k <= 0:
        return []
    qg = _grams(q)
    out = []
    for ex in examples():
        if not ex.get("verified", True):
            continue
        if allowed_tables:
            used = set(str(t).lower() for t in ex.get("tables") or [])
            if used and not used.issubset(allowed_tables):
                continue
        hit = len(qg & _grams(ex["question"]))
        score = min(1.0, hit / max(2.0, len(qg) * 0.7))
        if ex["question"] in q or q in ex["question"]:
            score = max(score, 0.9)
        if score > 0.30:
            out.append({"question": ex["question"], "sql": ex["sql"],
                        "score": round(float(score), 4),
                        "source": "knowledge", "id": ex["id"]})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


def _slug(text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + h


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


def add_example(question: str, sql: str, tables: list[str] | None = None,
                notes: str = "", source: str = "admin",
                verified: bool = True) -> dict:
    q = (question or "").strip()
    s = (sql or "").strip()
    if not q or not s:
        raise ValueError("问题和 SQL 不能为空")
    kid = _slug(q + s)
    meta = {
        "question": q,
        "sql": s,
        "tables": [str(t).strip() for t in (tables or []) if str(t).strip()],
        "source": source,
        "created": datetime.now().isoformat(timespec="seconds"),
        "verified": bool(verified),
    }
    import yaml  # type: ignore
    content = "---\n" + yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).strip() + "\n---\n\n" + (notes or "").strip() + "\n"
    _write(_sql_dir() / f"{kid}.md", content)
    reset_cache()
    return {"id": kid, **meta}


def add_rule(text: str, title: str = "", source: str = "admin") -> dict:
    body = (text or "").strip()
    if len(body) < 2:
        raise ValueError("规则内容过短")
    kid = _slug(body)
    meta = {"title": (title or body.splitlines()[0][:40]).strip(),
            "source": source,
            "created": datetime.now().isoformat(timespec="seconds")}
    import yaml  # type: ignore
    content = "---\n" + yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).strip() + "\n---\n\n" + body + "\n"
    _write(_rules_dir() / f"{kid}.md", content)
    reset_cache()
    return {"id": kid, **meta}


def _delete(path: Path, kid: str) -> bool:
    if not _ID_RE.match(kid or ""):
        return False
    f = (path / f"{kid}.md").resolve()
    if not f.is_relative_to(path.resolve()) or not f.is_file():
        return False
    f.unlink()
    reset_cache()
    return True


def delete_example(kid: str) -> bool:
    return _delete(_sql_dir(), kid)


def delete_rule(kid: str) -> bool:
    return _delete(_rules_dir(), kid)


def reset_cache() -> None:
    global _cache, _cache_key
    _cache = None
    _cache_key = ()
