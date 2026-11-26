from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_api_token
from app.core.database import get_db
from app.core.encryption import encrypt_secret
from app.models.email import EmailAccount
from app.models.mail_rule import MailRule
from app.models.poll_status import AccountPollStatus
from app.models.telegram_rule import TelegramFilterRule
from app.schemas.accounts import (
    AccountPollStatusOut,
    EmailAccountCreate,
    EmailAccountOut,
    EmailAccountUpdate,
    TelegramFilterRuleCreate,
    TelegramFilterRuleOut,
    TelegramFilterRuleUpdate,
)

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(verify_api_token)],
)


@router.get("/", response_model=List[EmailAccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
) -> list[EmailAccount]:
    result = await db.execute(
        select(EmailAccount).order_by(EmailAccount.sort_order, EmailAccount.id)
    )
    return list(result.scalars().all())


@router.get("/status", response_model=List[AccountPollStatusOut])
async def list_account_status(
    db: AsyncSession = Depends(get_db),
) -> list[AccountPollStatus]:
    result = await db.execute(select(AccountPollStatus))
    return list(result.scalars().all())


@router.post(
    "/",
    response_model=EmailAccountOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: EmailAccountCreate,
    db: AsyncSession = Depends(get_db),
) -> EmailAccount:
    email_clean = str(payload.email).strip()
    exists = await db.execute(
        select(EmailAccount).where(func.lower(EmailAccount.email) == email_clean.lower())
    )
    if exists.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱账号已存在",
        )

    normalized_pwd = (payload.app_password or "").strip().replace(" ", "")
    if not normalized_pwd:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱授权码 / 应用密码不能为空",
        )
    encrypted_pwd = encrypt_secret(normalized_pwd)

    # 新账号默认排在最后：当前最大 sort_order + 1
    max_q = await db.execute(select(func.max(EmailAccount.sort_order)))
    max_sort = max_q.scalar_one()
    next_sort = 0 if max_sort is None else int(max_sort) + 1

    account = EmailAccount(
        email=email_clean,
        provider=getattr(payload, "provider", "custom") or "custom",
        encrypted_pwd=encrypted_pwd,
        host=payload.host.strip(),
        port=payload.port,
        is_active=payload.is_active,
        sort_order=next_sort,
        telegram_push_enabled=getattr(payload, "telegram_push_enabled", True),
        push_template=getattr(payload, "push_template", "short") or "short",
        poll_interval_seconds=getattr(payload, "poll_interval_seconds", None),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=EmailAccountOut)
async def update_account(
    account_id: int,
    payload: EmailAccountUpdate,
    db: AsyncSession = Depends(get_db),
) -> EmailAccount:
    result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalars().first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if payload.host is not None:
        account.host = payload.host.strip()
    if payload.port is not None:
        account.port = payload.port
    if payload.is_active is not None:
        account.is_active = payload.is_active
    if payload.provider is not None:
        account.provider = payload.provider
    if payload.sort_order is not None:
        account.sort_order = int(payload.sort_order)
    if payload.telegram_push_enabled is not None:
        account.telegram_push_enabled = payload.telegram_push_enabled
    if payload.push_template is not None:
        account.push_template = payload.push_template
    if "poll_interval_seconds" in payload.dict(exclude_unset=True):
        account.poll_interval_seconds = payload.poll_interval_seconds
    if payload.app_password is not None:
        normalized_pwd = (payload.app_password or "").strip().replace(" ", "")
        if not normalized_pwd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱授权码 / 应用密码不能为空",
            )
        account.encrypted_pwd = encrypt_secret(normalized_pwd)

    await db.commit()
    await db.refresh(account)
    return account


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalars().first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Explicitly remove dependent rows without ORM relationships (belt-and-suspenders with ON DELETE CASCADE)
    await db.execute(delete(AccountPollStatus).where(AccountPollStatus.account_id == account_id))
    await db.execute(delete(MailRule).where(MailRule.account_id == account_id))
    await db.delete(account)
    await db.commit()


# ----- Telegram push rules (per-account) -----


@router.get(
    "/{account_id}/telegram-rules",
    response_model=List[TelegramFilterRuleOut],
)
async def list_telegram_rules(
    account_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[TelegramFilterRule]:
    acc = (await db.execute(select(EmailAccount).where(EmailAccount.id == account_id))).scalars().first()
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    result = await db.execute(
        select(TelegramFilterRule)
        .where(TelegramFilterRule.account_id == account_id)
        .order_by(TelegramFilterRule.rule_order, TelegramFilterRule.id)
    )
    return list(result.scalars().all())


@router.post(
    "/{account_id}/telegram-rules",
    response_model=TelegramFilterRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_telegram_rule(
    account_id: int,
    payload: TelegramFilterRuleCreate,
    db: AsyncSession = Depends(get_db),
) -> TelegramFilterRule:
    acc = (await db.execute(select(EmailAccount).where(EmailAccount.id == account_id))).scalars().first()
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if payload.field not in ("sender", "domain", "subject", "body"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="field must be sender, domain, subject, or body")
    if payload.mode not in ("allow", "deny"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode must be allow or deny")
    val = (payload.value or "").strip()
    if not val:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="规则关键字不能为空")
    rule = TelegramFilterRule(
        account_id=account_id,
        field=payload.field,
        mode=payload.mode,
        value=val,
        rule_order=payload.rule_order,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch(
    "/telegram-rules/{rule_id}",
    response_model=TelegramFilterRuleOut,
)
async def update_telegram_rule(
    rule_id: int,
    payload: TelegramFilterRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> TelegramFilterRule:
    rule = await db.get(TelegramFilterRule, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    if payload.field is not None:
        if payload.field not in ("sender", "domain", "subject", "body"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="field must be sender, domain, subject, or body")
        rule.field = payload.field
    if payload.mode is not None:
        if payload.mode not in ("allow", "deny"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode must be allow or deny")
        rule.mode = payload.mode
    if payload.value is not None:
        val = payload.value.strip()
        if not val:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="规则关键字不能为空")
        rule.value = val
    if payload.rule_order is not None:
        rule.rule_order = payload.rule_order
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete(
    "/telegram-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_telegram_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await db.get(TelegramFilterRule, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await db.delete(rule)
    await db.commit()


