import json
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, EmailStr, validator

VALID_PUSH_TEMPLATES = frozenset({"full_email", "full", "short", "title_only"})


def encode_utc_datetime(v: datetime) -> str:
    if v.tzinfo is not None:
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return v.isoformat() + "Z"


class EmailAccountBase(BaseModel):
    email: EmailStr
    host: str = "imap.gmail.com"
    port: int = 993
    is_active: bool = True
    provider: str = "custom"
    sort_order: Optional[int] = None
    telegram_push_enabled: bool = True
    push_template: str = "short"  # full_email | full | short | title_only
    poll_interval_seconds: Optional[int] = None


class EmailAccountCreate(EmailAccountBase):
    app_password: str

    @validator("host")
    def validate_host(cls, v: str) -> str:  # noqa: N805
        v = (v or "").strip()
        if not v:
            raise ValueError("IMAP Host 不能为空")
        return v

    @validator("port")
    def validate_port(cls, v: int) -> int:  # noqa: N805
        if not (1 <= v <= 65535):
            raise ValueError("端口必须在 1 到 65535 之间")
        return v

    @validator("push_template")
    def validate_push_template(cls, v: str) -> str:  # noqa: N805
        v = (v or "short").strip()
        if v not in VALID_PUSH_TEMPLATES:
            raise ValueError("push_template 必须为 full_email、full、short 或 title_only")
        return v

    @validator("poll_interval_seconds")
    def validate_poll_interval(cls, v: Optional[int]) -> Optional[int]:  # noqa: N805
        if v is not None and v < 5:
            raise ValueError("轮询间隔不能小于 5 秒")
        return v


class EmailAccountUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    is_active: Optional[bool] = None
    app_password: Optional[str] = None
    provider: Optional[str] = None
    sort_order: Optional[int] = None
    telegram_push_enabled: Optional[bool] = None
    push_template: Optional[str] = None
    poll_interval_seconds: Optional[int] = None

    @validator("host")
    def validate_host(cls, v: Optional[str]) -> Optional[str]:  # noqa: N805
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("IMAP Host 不能为空")
        return v

    @validator("port")
    def validate_port(cls, v: Optional[int]) -> Optional[int]:  # noqa: N805
        if v is not None and not (1 <= v <= 65535):
            raise ValueError("端口必须在 1 到 65535 之间")
        return v

    @validator("push_template")
    def validate_push_template(cls, v: Optional[str]) -> Optional[str]:  # noqa: N805
        if v is None:
            return None
        v = v.strip()
        if v not in VALID_PUSH_TEMPLATES:
            raise ValueError("push_template 必须为 full_email、full、short 或 title_only")
        return v

    @validator("poll_interval_seconds")
    def validate_poll_interval(cls, v: Optional[int]) -> Optional[int]:  # noqa: N805
        if v is not None and v < 5:
            raise ValueError("轮询间隔不能小于 5 秒")
        return v


class EmailAccountOut(EmailAccountBase):
    id: int

    class Config:
        orm_mode = True


class EmailRecordOut(BaseModel):
    id: int
    message_id: str
    account_id: int
    account_email: str
    subject: str
    sender: str
    content_summary: str
    received_at: datetime
    is_read: bool = False
    labels: List[str] = []

    class Config:
        orm_mode = True
        json_encoders = {datetime: encode_utc_datetime}

    @validator("labels", pre=True)
    def parse_labels(cls, v):  # noqa: N805
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else []
            except Exception:
                return []
        return v if v is not None else []


class EmailRecordDetailOut(EmailRecordOut):
    body_text: Optional[str] = None
    body_html: Optional[str] = None

    class Config:
        orm_mode = True
        json_encoders = {datetime: encode_utc_datetime}


class EmailListOut(BaseModel):
    items: List[EmailRecordOut]
    total: int
    page: int
    page_size: int

    class Config:
        json_encoders = {datetime: encode_utc_datetime}


class AccountPollStatusOut(BaseModel):
    account_id: int
    last_started_at: Optional[datetime] = None
    last_finished_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None

    class Config:
        orm_mode = True
        json_encoders = {datetime: encode_utc_datetime}


class TelegramFilterRuleCreate(BaseModel):
    field: str  # sender | domain | subject | body
    mode: str  # allow | deny
    value: str
    rule_order: int = 0


class TelegramFilterRuleUpdate(BaseModel):
    field: Optional[str] = None
    mode: Optional[str] = None
    value: Optional[str] = None
    rule_order: Optional[int] = None


class TelegramFilterRuleOut(BaseModel):
    id: int
    account_id: int
    field: str
    mode: str
    value: str
    rule_order: int

    class Config:
        orm_mode = True


class MailRuleCreate(BaseModel):
    name: Optional[str] = ""
    rule_order: int = 0
    account_id: Optional[int] = None
    sender_pattern: Optional[str] = ""
    subject_pattern: Optional[str] = ""
    body_pattern: Optional[str] = ""
    add_labels: List[str] = []
    push_telegram: bool = True
    mark_read: bool = False


class MailRuleUpdate(BaseModel):
    name: Optional[str] = None
    rule_order: Optional[int] = None
    account_id: Optional[int] = None
    sender_pattern: Optional[str] = None
    subject_pattern: Optional[str] = None
    body_pattern: Optional[str] = None
    add_labels: Optional[List[str]] = None
    push_telegram: Optional[bool] = None
    mark_read: Optional[bool] = None


class MailRuleOut(BaseModel):
    id: int
    name: Optional[str] = ""
    rule_order: int
    account_id: Optional[int] = None
    sender_pattern: Optional[str] = ""
    subject_pattern: Optional[str] = ""
    body_pattern: Optional[str] = ""
    add_labels: List[str] = []
    push_telegram: bool
    mark_read: bool

    class Config:
        orm_mode = True

    @validator("add_labels", pre=True)
    def parse_add_labels(cls, v):  # noqa: N805
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else []
            except Exception:
                return []
        return v if v is not None else []

