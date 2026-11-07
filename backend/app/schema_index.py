# -*- coding: utf-8 -*-
"""50 张表的 schema linking：向量检索 + 中文关键词融合 + 外键补全 + 多轮表继承。

向量索引文件由 scripts/build_index.py 或 POST /api/index/rebuild 生成，
需要一次硅基流动 embedding 调用（50 条文本）。无索引/无 key 时自动降级为关键词检索。
"""
from __future__ import annotations

import asyncio
import json
import os

from .config import settings
from .embedding import cosine, embed, embed_one, last_error, set_error


def _grams(s: str) -> set[str]:
    s = (s or "").lower()
    return {s[i:i + 2] for i in range(len(s) - 1) if s[i:i + 2].strip()}


class SchemaIndex:
    def __init__(self):
        if not settings.meta_path.exists():
            raise RuntimeError("缺少 schema_meta.json，请先运行 python backend/scripts/init_db.py")
        self.meta = json.loads(settings.meta_path.read_text(encoding="utf-8"))
        self.tables = {t["name"]: t for t in self.meta["tables"]}
        self.order = [t["name"] for t in self.meta["tables"]]
        self.vectors: dict[str, list[float]] = {}
        self.mode = "keyword"
        self.load_error = ""
        self._build_lock = asyncio.Lock()
        self.load()

    # ---------- 索引持久化 ----------
    def load(self) -> None:
        p = settings.index_path
        if not p.exists():
            return
        expected_mode = "mock" if settings.MOCK_MODE else "remote"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("mode") != expected_mode:
                self.load_error = f"索引模式不匹配（{d.get('mode')} != {expected_mode}）"
                raise ValueError(self.load_error)
            if d.get("model") != settings.EMB_MODEL:
                self.load_error = "索引模型与 EMB_MODEL 不一致"
                raise ValueError(self.load_error)
            vecs = d.get("vectors", {})
            if not vecs or len(vecs) != len(self.order):
                self.load_error = "索引表数量不一致"
                raise ValueError(self.load_error)
            if int(d.get("dim") or 0) != settings.EMB_DIM:
                self.load_error = "索引维度与 EMB_DIM 不一致"
                raise ValueError(self.load_error)
            if any(len(v) != settings.EMB_DIM for v in vecs.values()):
                self.load_error = "索引向量维度异常"
                raise ValueError(self.load_error)
            self.vectors = vecs
            self.mode = "vector"
            self.load_error = ""
        except Exception as e:  # noqa: BLE001
            # 不再静默降级：记录原因，供 /api/status 与启动日志诊断
            self.load_error = self.load_error or f"索引加载失败：{type(e).__name__}"
            set_error(self.load_error)
            print(f"[text2sql] {self.load_error} → 已降级为关键词选表")

    async def build(self) -> dict:
        async with self._build_lock:
            texts = [self.tables[n]["text"] for n in self.order]
            vecs = await embed(texts)
            if vecs is None or len(vecs) != len(texts):
                raise RuntimeError(f"向量化失败：{last_error() or '返回条数不一致'}")
            if any(len(v) != settings.EMB_DIM for v in vecs):
                raise RuntimeError("向量维度与 EMB_DIM 不一致，已保留原索引")
            new_vectors = {
                n: [round(float(x), 6) for x in v] for n, v in zip(self.order, vecs)
            }
            payload = {
                "model": settings.EMB_MODEL,
                "dim": settings.EMB_DIM,
                "mode": "mock" if settings.MOCK_MODE else "remote",
                "table_count": len(self.order),
                "vectors": new_vectors,
            }
            # 原子替换：写临时文件后 os.replace，失败不破坏旧索引
            tmp = settings.index_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, settings.index_path)
            try:
                os.chmod(settings.index_path, 0o600)
            except OSError:
                pass
            self.vectors = new_vectors
            self.mode = "vector"
            self.load_error = ""
            return {"ok": True, "table_count": len(self.order), "mode": self.mode,
                    "mock": settings.MOCK_MODE}

    # ---------- 打分与检索 ----------
    def keyword_score(self, question: str, t: dict) -> float:
        qg = _grams(question)
        if not qg:
            return 0.0
        text = " ".join(
            [t["cn"], t["name"], t["domain"], t.get("keywords", "")]
            + [f'{c["cn"]} {c["name"]}' for c in t["columns"]]
        )
        hit = len(qg & _grams(text))
        score = min(1.0, hit / max(2.0, len(qg) * 0.6))
        for word in [t["cn"]] + (t.get("keywords") or "").split():
            if word and word in question:
                score += 0.22
        return min(1.0, score)

    def expand_with_fks(self, names: list[str], max_extra: int | None = None) -> list[str]:
        """按外键把 JOIN 必需的父表补进来，避免 Top6 硬截断后多表查询缺表。"""
        cap = settings.FK_EXPAND_MAX if max_extra is None else max_extra
        out = list(dict.fromkeys(names))
        for n in list(out):
            t = self.tables.get(n, {})
            for ref in (t.get("fks") or {}).values():
                parent = ref[0] if isinstance(ref, (list, tuple)) else str(ref).split(".")[0]
                if parent in self.tables and parent not in out and len(out) - len(names) < cap:
                    out.append(parent)
        return out

    async def search(
        self,
        question: str,
        top_k: int | None = None,
        boost: list[str] | None = None,
        qvec: list[float] | None = None,
        expand_fks: bool = True,
    ) -> list[dict]:
        k = top_k or settings.TOP_K_TABLES
        if qvec is None and self.mode == "vector":
            qvec = await embed_one(question)
        use_vector = bool(qvec) and self.mode == "vector" and bool(self.vectors)
        out = []
        for n in self.order:
            t = self.tables[n]
            try:
                vs = cosine(qvec, self.vectors[n]) if (use_vector and n in self.vectors) else 0.0
            except ValueError:
                vs = 0.0
            ks = self.keyword_score(question, t)
            score = (0.68 * vs + 0.32 * ks) if use_vector else ks
            if boost and n in boost:
                score += 0.12  # 多轮追问继承上一轮的表
            out.append({
                "name": n,
                "cn": t["cn"],
                "domain": t["domain"],
                "score": round(float(score), 4),
                "vector_score": round(float(vs), 4),
                "keyword_score": round(float(ks), 4),
            })
        out.sort(key=lambda x: -x["score"])
        picked = out[:k]
        if expand_fks:
            names = self.expand_with_fks([x["name"] for x in picked])
            by_name = {x["name"]: x for x in out}
            for n in names:
                if n not in [x["name"] for x in picked]:
                    extra = dict(by_name[n])
                    extra["score"] = round(extra["score"] - 0.001, 4)
                    extra["fk_added"] = True
                    picked.append(extra)
        return picked

    def answerable(self, question: str, threshold: float = 0.12) -> bool:
        """给 guard 的建议问法做一次可答性打分，避免推荐库里答不出的问题。"""
        return max((self.keyword_score(question, t) for t in self.tables.values()),
                   default=0.0) >= threshold

    # ---------- 给 LLM 的上下文 ----------
    def prompt_context(self, names: list[str]) -> str:
        parts = []
        for n in names:
            t = self.tables.get(n)
            if not t:
                continue
            enum_lines = [
                f'  {col} 可选值：{"、".join(str(v) for v in vals[:12])}'
                for col, vals in (t.get("enums") or {}).items()
            ]
            sample = json.dumps(t.get("samples", [])[:2], ensure_ascii=False)
            fks = "、".join(f'{c} → {ref[0]}.{ref[1]}' for c, ref in (t.get("fks") or {}).items())
            parts.append(
                f'### 表 `{n}` — {t["cn"]}（业务域：{t["domain"]}，约 {t["rows"]} 行）\n'
                f'{t["ddl"]}\n'
                + (f'  外键：{fks}\n' if fks else "")
                + ("\n".join(enum_lines) + "\n" if enum_lines else "")
                + f'  样例行：{sample}'
            )
        return "\n\n".join(parts)

    def brief(self) -> list[dict]:
        return [{
            "name": t["name"], "cn": t["cn"], "domain": t["domain"],
            "rows": t["rows"], "column_count": len(t["columns"]),
            "keywords": t.get("keywords", ""),
        } for t in self.meta["tables"]]
