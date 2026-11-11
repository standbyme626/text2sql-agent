# -*- coding: utf-8 -*-
"""全局配置：全部来自项目根 .env，密钥不落代码、不进版本库。"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = APP_DIR.parent                       # backend
PROJECT_DIR = BACKEND_DIR.parent                   # text2sql-agent
DATA_DIR = Path(os.getenv("TEXT2SQL_DATA_DIR", str(BACKEND_DIR / "data")))
STATIC_DIR = Path(os.getenv("TEXT2SQL_STATIC_DIR", str(BACKEND_DIR / "static")))

# 自测/隔离实例用 TEXT2SQL_NO_DOTENV=1 切断线上 .env，避免密钥与账号串味
if os.getenv("TEXT2SQL_NO_DOTENV", "").strip().lower() in ("1", "true", "yes", "on"):
    pass
else:
    load_dotenv(PROJECT_DIR / ".env", override=False)


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _clamped(key: str, default: int, lo: int, hi: int) -> int:
    """所有次数/上限类配置都钳制，避免误配造成空循环或额度失控。"""
    return max(lo, min(hi, _int(key, default)))


def _secure_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass


def _secret_key() -> str:
    """优先用 .env 的 SECRET_KEY，否则原子创建一次并持久化（权限 600）。"""
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env
    _secure_dir()
    p = DATA_DIR / ".secret_key"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(48)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
    except FileExistsError:
        return p.read_text(encoding="utf-8").strip()
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return key


@dataclass(frozen=True)
class Settings:
    # --- 服务 ---
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = _int("PORT", 3388)
    PUBLIC_BASE_PATH: str = os.getenv("PUBLIC_BASE_PATH", "")
    # 生产显式配站点域名；留空 = 同源，不再默认允许任意来源
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")

    # --- 鉴权（公网暴露必填） ---
    # AUTH_USERS=user:pass:role,user2:pass2:role2（role=admin|user）
    # 未配置时回退旧的单账号 AUTH_USER/AUTH_PASSWORD（角色固定 admin）
    AUTH_USERS: str = os.getenv("AUTH_USERS", "")
    AUTH_USER: str = os.getenv("AUTH_USER", "admin")
    AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "")
    SECRET_KEY: str = _secret_key()
    TOKEN_TTL_HOURS: int = _clamped("TOKEN_TTL_HOURS", 24, 1, 168)

    # --- 文本大模型：主模型 + 兜底模型 ---
    # 主模型默认 opencode-go DeepSeek V4.1 Flash；兜底保留 OpenRouter 免费模型
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "opencode-go")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://opencode.ai/inference/go/openai/v1").rstrip("/")
    LLM_API_KEY: str = (os.getenv("LLM_API_KEY") or
                        os.getenv("MODELSCOPE_API_KEY", ""))
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-v4.1-flash")
    LLM_FALLBACK_PROVIDER: str = os.getenv("LLM_FALLBACK_PROVIDER", "openrouter")
    LLM_FALLBACK_BASE_URL: str = os.getenv(
        "LLM_FALLBACK_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    LLM_FALLBACK_API_KEY: str = os.getenv("LLM_FALLBACK_API_KEY", "")
    LLM_FALLBACK_MODEL: str = os.getenv(
        "LLM_FALLBACK_MODEL", "baidu/ernie-5.5-flash-preview:free")
    LLM_TIMEOUT: int = _clamped("LLM_TIMEOUT", 120, 10, 300)
    LLM_MAX_TOKENS: int = _clamped("LLM_MAX_TOKENS", 8192, 256, 16384)
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    # --- 向量模型：硅基流动 SiliconFlow ---
    EMB_BASE_URL: str = os.getenv("EMB_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")
    EMB_API_KEY: str = os.getenv("SILICONFLOW_API_KEY", "")
    EMB_MODEL: str = os.getenv("EMB_MODEL", "Qwen/Qwen3-Embedding-8B")
    EMB_DIM: int = _clamped("EMB_DIM", 1024, 8, 4096)
    EMB_TIMEOUT: int = _clamped("EMB_TIMEOUT", 60, 5, 180)

    # --- 数据源（默认 SQLite；DATABASE_URL 可切 Postgres）---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    SEMANTIC_FILE: str = (os.getenv("SEMANTIC_FILE") or
                          str(BACKEND_DIR / "semantic" / "metrics.yaml"))
    # 文件知识库（Wren AI 风格）：knowledge/sql/*.md + knowledge/rules/*.md
    # 可版本化、可审计；索引与 few-shot 只是派生层
    KNOWLEDGE_DIR: str = (os.getenv("KNOWLEDGE_DIR") or
                          str(PROJECT_DIR / "knowledge"))

    # --- Agent 参数 ---
    # toolloop = 2026 工具调用循环；workflow = 旧固定流水线（不支持的模型可回退）
    AGENT_MODE: str = os.getenv("AGENT_MODE", "toolloop").strip().lower()
    MAX_AGENT_STEPS: int = _clamped("MAX_AGENT_STEPS", 6, 1, 20)
    MAX_TOOL_SQL: int = _clamped("MAX_TOOL_SQL", 4, 1, 10)
    TOOL_ROW_PREVIEW: int = _clamped("TOOL_ROW_PREVIEW", 20, 5, 100)
    TOP_K_TABLES: int = _clamped("TOP_K_TABLES", 6, 1, 20)
    COLUMN_LINK_TOPK: int = _clamped("COLUMN_LINK_TOPK", 8, 2, 40)
    FEWSHOT_K: int = _clamped("FEWSHOT_K", 2, 0, 6)
    MAX_SQL_RETRY: int = _clamped("MAX_SQL_RETRY", 2, 0, 5)
    MAX_RESULT_ROWS: int = _clamped("MAX_RESULT_ROWS", 500, 10, 5000)
    SQL_TIMEOUT_MS: int = _clamped("SQL_TIMEOUT_MS", 5000, 200, 60000)
    HISTORY_TURNS: int = _clamped("HISTORY_TURNS", 6, 1, 20)
    MAX_LLM_CALLS: int = _clamped("MAX_LLM_CALLS", 6, 1, 20)  # 单轮 LLM 硬预算（含 1 次洞察）
    FK_EXPAND_MAX: int = _clamped("FK_EXPAND_MAX", 3, 0, 10)  # 外键闭包最多补几张表
    AUTO_INSIGHT: bool = _bool("AUTO_INSIGHT", True)
    FOLLOWUP_COUNT: int = _clamped("FOLLOWUP_COUNT", 3, 0, 6)
    INSIGHT_MAX_TOKENS: int = _clamped("INSIGHT_MAX_TOKENS", 1200, 100, 3000)
    INSIGHT_PREVIEW_ROWS: int = _clamped("INSIGHT_PREVIEW_ROWS", 50, 5, 100)
    EMPTY_RESULT_RETRY: bool = _bool("EMPTY_RESULT_RETRY", True)
    GUARD_ENABLED: bool = _bool("GUARD_ENABLED", True)
    GUARD_SUGGESTIONS: int = _clamped("GUARD_SUGGESTIONS", 3, 0, 6)

    # --- 限流 / 资源 ---
    RATE_LIMIT_ENABLED: bool = _bool("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_PER_MIN: int = _clamped("RATE_LIMIT_PER_MIN", 40, 1, 1000)
    REBUILD_COOLDOWN: int = _clamped("REBUILD_COOLDOWN", 300, 0, 86400)
    MAX_QA_HISTORY: int = _clamped("MAX_QA_HISTORY", 400, 50, 10000)
    MAX_BODY_BYTES: int = _clamped("MAX_BODY_BYTES", 1_000_000, 10000, 10_000_000)
    SSE_HEARTBEAT_SEC: int = _clamped("SSE_HEARTBEAT_SEC", 15, 3, 60)

    # --- 可观测性 / 记忆 ---
    TRACE_ENABLED: bool = _bool("TRACE_ENABLED", True)
    TRACE_RECENT: int = _clamped("TRACE_RECENT", 200, 20, 2000)
    MEMORY_ENABLED: bool = _bool("MEMORY_ENABLED", True)

    # --- 开关 ---
    MOCK_MODE: bool = _bool("MOCK_MODE", False)   # 不调用任何外部 API，用于本地自测
    # 无索引/索引损坏且允许自动构建时，在 lifespan 里后台重建（只发生在异常场景）
    AUTO_BUILD_INDEX: bool = _bool("AUTO_BUILD_INDEX", True)
    # 仅容器/内网调试时可置 1，跳过「必须鉴权」检查；生产环境不要开
    ALLOW_INSECURE: bool = _bool("ALLOW_INSECURE", False)

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "ecommerce.db"

    @property
    def meta_path(self) -> Path:
        return DATA_DIR / "schema_meta.json"

    @property
    def index_path(self) -> Path:
        return DATA_DIR / "schema_index.json"

    @property
    def app_db_path(self) -> Path:
        return DATA_DIR / "app.db"

    @property
    def db_dialect(self) -> str:
        return "postgres" if self.DATABASE_URL.startswith(
            ("postgres://", "postgresql://")) else "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.db_dialect == "postgres"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_users)

    @property
    def auth_users(self) -> dict[str, dict[str, str]]:
        """账号表：AUTH_USERS 优先，否则回退单账号 AUTH_USER/AUTH_PASSWORD。"""
        raw = (self.AUTH_USERS or "").strip()
        users: dict[str, dict[str, str]] = {}
        if raw:
            for item in raw.split(","):
                parts = item.strip().split(":", 2)
                if len(parts) < 2 or not parts[0] or not parts[1]:
                    continue
                role = (parts[2] if len(parts) > 2 else "user").strip().lower()
                users[parts[0].strip()] = {
                    "password": parts[1],
                    "role": "admin" if role == "admin" else "user",
                }
        if not users and self.AUTH_PASSWORD:
            users[self.AUTH_USER] = {"password": self.AUTH_PASSWORD, "role": "admin"}
        return users

    def role_of(self, username: str) -> str:
        return (self.auth_users.get(username) or {}).get("role", "")

    @property
    def password_version(self) -> str:
        """改密码 / 增删账号 / 轮换 SECRET_KEY 后，已签发的旧 token 立即失效。"""
        import hashlib
        creds = ";".join(f"{u}:{v['password']}:{v['role']}"
                         for u, v in sorted(self.auth_users.items()))
        return hashlib.sha256(
            (creds + "|" + self.SECRET_KEY).encode()
        ).hexdigest()[:8]

    @property
    def llm_chain(self) -> list[dict[str, str]]:
        """主模型在前、兜底模型在后；缺 key 的条目自动跳过。"""
        chain = [
            {"provider": self.LLM_PROVIDER, "base_url": self.LLM_BASE_URL,
             "api_key": self.LLM_API_KEY, "model": self.LLM_MODEL},
        ]
        if self.LLM_FALLBACK_API_KEY and self.LLM_FALLBACK_MODEL:
            chain.append({
                "provider": self.LLM_FALLBACK_PROVIDER,
                "base_url": self.LLM_FALLBACK_BASE_URL,
                "api_key": self.LLM_FALLBACK_API_KEY,
                "model": self.LLM_FALLBACK_MODEL,
            })
        return [c for c in chain if c["base_url"] and c["api_key"] and c["model"]]

    @property
    def llm_ready(self) -> bool:
        return self.MOCK_MODE or bool(self.llm_chain)

    @property
    def emb_ready(self) -> bool:
        return self.MOCK_MODE or bool(self.EMB_API_KEY)


settings = Settings()
