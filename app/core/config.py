from typing import Any, Dict, Optional

from pydantic import BaseSettings, Field

# 界面修改的配置存 DB，在此覆盖 .env；由 startup 与 PATCH /api/settings 刷新
_db_overrides: Dict[str, str] = {}
# 是否已在 DB 中存储管理员密码哈希（修改密码/重置密码后为 True）
_admin_has_stored_password: bool = False

EDITABLE_KEYS = frozenset(
    {
        "telegram_bot_token",
        "telegram_chat_id",
        "poll_interval_seconds",
        "webhook_url",
        "api_token",
        "retention_keep_days",
        "retention_keep_per_account",
    }
)


def set_db_overrides(overrides: Dict[str, str]) -> None:
    global _db_overrides, _admin_has_stored_password
    _db_overrides = {k: v for k, v in overrides.items() if k in EDITABLE_KEYS}
    _admin_has_stored_password = "admin_password_hash" in overrides


def get_db_overrides() -> Dict[str, str]:
    return _db_overrides.copy()


def has_stored_admin_password() -> bool:
    return _admin_has_stored_password


class Settings(BaseSettings):
    app_name: str = "MailAggregator Pro"
    database_url: str = Field(
        default="sqlite+aiosqlite:///./mail_agg.db",
        description="SQLAlchemy database URL",
    )

    encryption_key: Optional[str] = Field(
        default=None,
        description="Fernet encryption key for storing app passwords",
    )

    poll_interval_seconds: int = Field(
        default=300,
        description="Auto polling interval for fetching emails",
        ge=5,
    )

    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram Bot API token for notifications",
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram chat ID to receive notifications",
    )

    webhook_url: Optional[str] = Field(
        default=None,
        description="URL to POST new email payload (JSON) when a new email is fetched",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="Optional API token; when set, API requests must include Authorization: Bearer <token> or X-API-Key: <token>",
    )

    admin_username: Optional[str] = Field(
        default=None,
        description="Console login username; if set with admin_password, browser must login to access API",
    )
    admin_password: Optional[str] = Field(
        default=None,
        description="Console login password (plain); use with admin_username for login",
    )
    jwt_secret: Optional[str] = Field(
        default=None,
        description="Secret for signing JWT; default derived from api_token or random",
    )
    admin_reset_token: Optional[str] = Field(
        default=None,
        description="Token for resetting admin password when forgotten (e.g. ADMIN_RESET_TOKEN in .env)",
    )

    retention_keep_days: Optional[int] = Field(
        default=None,
        description="Optional retention policy: keep only latest N days of emails (manual cleanup uses this as default)",
        ge=1,
    )
    retention_keep_per_account: Optional[int] = Field(
        default=None,
        description="Optional retention policy: keep only latest N emails per account (manual cleanup uses this as default)",
        ge=1,
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    base = Settings()
    overrides = get_db_overrides()
    if not overrides:
        return base
    d: Dict[str, Any] = base.dict()
    for k, v in overrides.items():
        if k not in d:
            continue
        raw = v.strip() if isinstance(v, str) else v
        if k == "poll_interval_seconds":
            if raw in (None, ""):
                # 留空时回退到 .env / 默认值
                continue
            try:
                parsed = int(raw)
                if parsed >= 5:
                    d[k] = parsed
            except (TypeError, ValueError):
                continue
        elif k in {"retention_keep_days", "retention_keep_per_account"}:
            if raw in (None, ""):
                # 在界面清空保留策略时应置为 None，而不是回退到 .env 旧值
                d[k] = None
                continue
            try:
                parsed = int(raw)
                d[k] = parsed if parsed >= 1 else None
            except (TypeError, ValueError):
                d[k] = None
        else:
            d[k] = str(raw) if raw not in (None, "") else None
    return Settings(**d)


