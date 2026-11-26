from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_api_token
from app.core.config import (
    EDITABLE_KEYS,
    get_settings,
    set_db_overrides,
)
from app.core.database import get_db
from app.core.encryption import encrypt_secret
from app.models.email import EmailAccount
from app.models.telegram_rule import TelegramFilterRule

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(verify_api_token)],
)


async def load_settings_from_db(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(text("SELECT key, value FROM system_settings"))
    rows = result.fetchall()
    return {r[0]: r[1] for r in rows}


@router.get("")
async def get_settings_for_edit(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """返回当前配置：可编辑项为明文（供表单回填），敏感项可脱敏展示。"""
    s = get_settings()
    return {
        "telegram_bot_token": s.telegram_bot_token or "",
        "telegram_chat_id": s.telegram_chat_id or "",
        "poll_interval_seconds": s.poll_interval_seconds,
        "webhook_url": s.webhook_url or "",
        "api_token": s.api_token or "",
        "retention_keep_days": s.retention_keep_days,
        "retention_keep_per_account": s.retention_keep_per_account,
    }


@router.get("/export")
async def export_settings(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """导出当前配置（系统设置 + 邮箱账号及推送规则）为 JSON 文件（含敏感信息，请妥善保存）。"""
    s = get_settings()
    settings_data = {
        "telegram_bot_token": s.telegram_bot_token or "",
        "telegram_chat_id": s.telegram_chat_id or "",
        "poll_interval_seconds": s.poll_interval_seconds,
        "webhook_url": s.webhook_url or "",
        "api_token": s.api_token or "",
        "retention_keep_days": s.retention_keep_days,
        "retention_keep_per_account": s.retention_keep_per_account,
    }

    result = await db.execute(
        select(EmailAccount).order_by(EmailAccount.sort_order, EmailAccount.id)
    )
    accounts_rows = result.scalars().all()
    accounts_data: List[dict[str, Any]] = []
    for acc in accounts_rows:
        rules_result = await db.execute(
            select(TelegramFilterRule)
            .where(TelegramFilterRule.account_id == acc.id)
            .order_by(TelegramFilterRule.rule_order, TelegramFilterRule.id)
        )
        rules = rules_result.scalars().all()
        accounts_data.append({
            "email": acc.email,
            "provider": acc.provider or "custom",
            "host": acc.host or "imap.gmail.com",
            "port": int(acc.port or 993),
            "is_active": bool(acc.is_active),
            "sort_order": int(acc.sort_order or 0),
            "telegram_push_enabled": bool(acc.telegram_push_enabled),
            "push_template": acc.push_template or "short",
            "poll_interval_seconds": acc.poll_interval_seconds,
            "encrypted_pwd": acc.encrypted_pwd or "",
            "telegram_rules": [
                {"field": r.field, "mode": r.mode, "value": r.value, "rule_order": r.rule_order}
                for r in rules
            ],
        })

    data = {"settings": settings_data, "accounts": accounts_data}
    return JSONResponse(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=\"mail-tool-config.json\""},
    )


class SettingsUpdate(BaseModel):
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    poll_interval_seconds: Optional[int] = None
    webhook_url: Optional[str] = None
    api_token: Optional[str] = None
    retention_keep_days: Optional[int] = None
    retention_keep_per_account: Optional[int] = None


class TelegramRuleImport(BaseModel):
    field: str = "sender"
    mode: str = "allow"
    value: str = ""
    rule_order: int = 0


class AccountImport(BaseModel):
    email: str
    provider: Optional[str] = "custom"
    host: Optional[str] = "imap.gmail.com"
    port: Optional[int] = 993
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0
    telegram_push_enabled: Optional[bool] = True
    push_template: Optional[str] = "short"
    poll_interval_seconds: Optional[int] = None
    encrypted_pwd: Optional[str] = None
    telegram_rules: Optional[List[TelegramRuleImport]] = None


class ImportPayload(BaseModel):
    settings: Optional[SettingsUpdate] = None
    accounts: Optional[List[AccountImport]] = None


def _validate_settings_updates(updates: dict[str, Any]) -> None:
    if "poll_interval_seconds" in updates and updates["poll_interval_seconds"] is not None:
        if int(updates["poll_interval_seconds"]) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="全局轮询间隔不能小于 5 秒",
            )
    if "retention_keep_days" in updates and updates["retention_keep_days"] is not None:
        if int(updates["retention_keep_days"]) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="保留天数不能小于 1 天",
            )
    if "retention_keep_per_account" in updates and updates["retention_keep_per_account"] is not None:
        if int(updates["retention_keep_per_account"]) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="每账号保留封数不能小于 1",
            )


async def _persist_settings_updates(db: AsyncSession, updates: dict[str, Any]) -> None:
    for key in list(updates.keys()):
        if key not in EDITABLE_KEYS:
            del updates[key]
    _validate_settings_updates(updates)
    for key, value in updates.items():
        if key == "api_token" and isinstance(value, str) and value.strip() == "***":
            # Prevent accidentally overwriting the real api_token with masked placeholder
            continue
        if key in {"poll_interval_seconds", "retention_keep_days", "retention_keep_per_account"}:
            val = str(value) if value is not None else ""
        else:
            val = (value or "").strip()
        await db.execute(
            text(
                "INSERT OR REPLACE INTO system_settings (key, value) VALUES (:k, :v)"
            ),
            {"k": key, "v": val},
        )


@router.post("/import")
async def import_settings(
    body: ImportPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """导入配置（系统设置 + 邮箱账号及推送规则）。按邮箱匹配账号，存在则更新，不存在则创建。"""
    if body.settings:
        updates = body.settings.dict(exclude_unset=True)
        await _persist_settings_updates(db, updates)
        await db.commit()
        set_db_overrides(await load_settings_from_db(db))

    imported_count = 0
    if body.accounts:
        for idx, acc_in in enumerate(body.accounts):
            email = (acc_in.email or "").strip()
            if not email:
                continue
            port = int(acc_in.port or 993)
            if not (1 <= port <= 65535):
                port = 993
            poll_interval = acc_in.poll_interval_seconds
            if poll_interval is not None and poll_interval < 5:
                poll_interval = 5
            is_active = True if acc_in.is_active is None else bool(acc_in.is_active)
            tg_enabled = True if acc_in.telegram_push_enabled is None else bool(acc_in.telegram_push_enabled)
            sort_order = idx if acc_in.sort_order is None else int(acc_in.sort_order)

            existing = (
                await db.execute(select(EmailAccount).where(EmailAccount.email == email))
            ).scalars().first()
            if existing:
                existing.provider = acc_in.provider or "custom"
                existing.host = (acc_in.host or "imap.gmail.com").strip() or "imap.gmail.com"
                existing.port = port
                existing.is_active = is_active
                existing.sort_order = sort_order
                existing.telegram_push_enabled = tg_enabled
                existing.push_template = acc_in.push_template or "short"
                existing.poll_interval_seconds = poll_interval
                if acc_in.encrypted_pwd is not None and acc_in.encrypted_pwd.strip() != "":
                    existing.encrypted_pwd = acc_in.encrypted_pwd
                account_id = existing.id
            else:
                enc_pwd = acc_in.encrypted_pwd if (acc_in.encrypted_pwd and acc_in.encrypted_pwd.strip()) else ""
                if not enc_pwd:
                    enc_pwd = encrypt_secret("")
                new_acc = EmailAccount(
                    email=email,
                    provider=acc_in.provider or "custom",
                    host=(acc_in.host or "imap.gmail.com").strip() or "imap.gmail.com",
                    port=port,
                    is_active=is_active,
                    sort_order=sort_order,
                    telegram_push_enabled=tg_enabled,
                    push_template=acc_in.push_template or "short",
                    poll_interval_seconds=poll_interval,
                    encrypted_pwd=enc_pwd,
                )
                db.add(new_acc)
                await db.flush()
                account_id = new_acc.id

            await db.execute(delete(TelegramFilterRule).where(TelegramFilterRule.account_id == account_id))
            for r in acc_in.telegram_rules or []:
                val = (r.value or "").strip()
                if not val:
                    continue
                rule = TelegramFilterRule(
                    account_id=account_id,
                    field=r.field if r.field in ("sender", "domain", "subject", "body") else "sender",
                    mode=r.mode if r.mode in ("allow", "deny") else "allow",
                    value=val,
                    rule_order=int(r.rule_order or 0),
                )
                db.add(rule)
            imported_count += 1
        await db.commit()

    s = get_settings()
    return {
        "settings": {
            "telegram_bot_token": s.telegram_bot_token or "",
            "telegram_chat_id": s.telegram_chat_id or "",
            "poll_interval_seconds": s.poll_interval_seconds,
            "webhook_url": s.webhook_url or "",
            "api_token": "***" if s.api_token else "",
            "retention_keep_days": s.retention_keep_days,
            "retention_keep_per_account": s.retention_keep_per_account,
        },
        "imported_accounts": imported_count,
    }


@router.patch("")
async def update_settings(
    body: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新配置并写入 DB，立即生效（覆盖 .env）。"""
    updates = body.dict(exclude_unset=True)
    await _persist_settings_updates(db, updates)
    await db.commit()
    set_db_overrides(await load_settings_from_db(db))
    s = get_settings()
    return {
        "telegram_bot_token": s.telegram_bot_token or "",
        "telegram_chat_id": s.telegram_chat_id or "",
        "poll_interval_seconds": s.poll_interval_seconds,
        "webhook_url": s.webhook_url or "",
        "api_token": "***" if s.api_token else "",
        "retention_keep_days": s.retention_keep_days,
        "retention_keep_per_account": s.retention_keep_per_account,
    }

