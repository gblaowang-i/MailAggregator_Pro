import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_api_token
from app.core.database import get_db
from app.models.email import EmailAccount, EmailRecord
from app.models.mail_rule import MailRule
from app.models.poll_status import AccountPollStatus
from app.schemas.accounts import EmailListOut, EmailRecordDetailOut
from app.services.fetcher import fetch_recent_emails_for_account
from app.services.rules_engine import apply_mail_rules

router = APIRouter(
    prefix="/emails",
    tags=["emails"],
    dependencies=[Depends(verify_api_token)],
)


def _parse_datetime_param(s: Optional[str], *, is_end: bool = False) -> Optional[datetime]:
    """
    Parse either a YYYY-MM-DD date string or a full ISO8601 datetime string (e.g. with Z/offset)
    into a naive UTC datetime for querying EmailRecord.received_at.
    """
    if not s or not s.strip():
        return None
    raw = s.strip()
    if len(raw) == 10:
        try:
            d = datetime.strptime(raw, "%Y-%m-%d")
            return d + timedelta(days=1) if is_end else d
        except ValueError:
            return None
    try:
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        try:
            d = datetime.strptime(raw[:10], "%Y-%m-%d")
            return d + timedelta(days=1) if is_end else d
        except ValueError:
            return None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/", response_model=EmailListOut)
async def list_emails(
    account_id: Optional[int] = Query(default=None),
    provider: Optional[str] = Query(default=None, description="Filter by account provider (e.g. gmail, qq, 163, custom)"),
    keyword: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD or ISO8601 UTC datetime"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD or ISO8601 UTC datetime"),
    is_read: Optional[bool] = Query(default=None),
    label: Optional[str] = Query(default=None, description="Filter by exact label name in labels JSON"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    base_filter = []
    need_account_join_for_count = False

    if account_id is not None:
        base_filter.append(EmailRecord.account_id == account_id)
    if provider and provider.strip():
        prov = provider.strip()
        need_account_join_for_count = True
        if prov == "custom":
            base_filter.append(
                or_(
                    EmailAccount.provider == "custom",
                    EmailAccount.provider.is_(None),
                    EmailAccount.provider == "",
                )
            )
        else:
            base_filter.append(EmailAccount.provider == prov)
    if keyword and keyword.strip():
        kw = f"%{_escape_like(keyword.strip())}%"
        base_filter.append(
            or_(
                EmailRecord.subject.ilike(kw, escape="\\"),
                EmailRecord.sender.ilike(kw, escape="\\"),
                EmailRecord.content_summary.ilike(kw, escape="\\"),
            )
        )
    df = _parse_datetime_param(date_from, is_end=False)
    if df is not None:
        base_filter.append(EmailRecord.received_at >= df)
    dt = _parse_datetime_param(date_to, is_end=True)
    if dt is not None:
        if date_to and len(date_to.strip()) == 10:
            base_filter.append(EmailRecord.received_at < dt)
        else:
            base_filter.append(EmailRecord.received_at <= dt)
    if is_read is not None:
        base_filter.append(EmailRecord.is_read.is_(is_read))
    if label and label.strip():
        encoded_label = json.dumps(label.strip(), ensure_ascii=False)
        like_pat = f"%{_escape_like(encoded_label)}%"
        base_filter.append(EmailRecord.labels.like(like_pat, escape="\\"))

    count_stmt = select(func.count(EmailRecord.id))
    if need_account_join_for_count:
        count_stmt = count_stmt.join(EmailAccount, EmailAccount.id == EmailRecord.account_id)
    if base_filter:
        count_stmt = count_stmt.where(*base_filter)
    total = (await db.execute(count_stmt)).scalar_one()

    offset = (page - 1) * page_size
    stmt: Select = (
        select(
            EmailRecord.id,
            EmailRecord.message_id,
            EmailRecord.account_id,
            EmailAccount.email.label("account_email"),
            EmailRecord.subject,
            EmailRecord.sender,
            EmailRecord.content_summary,
            EmailRecord.received_at,
            EmailRecord.is_read,
            EmailRecord.labels,
        )
        .join(EmailAccount, EmailAccount.id == EmailRecord.account_id)
        .order_by(EmailRecord.received_at.desc(), EmailRecord.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    if base_filter:
        stmt = stmt.where(*base_filter)
    result = await db.execute(stmt)
    rows = result.mappings().all()
    items = [dict(r) for r in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post(
    "/apply-rules",
    status_code=status.HTTP_200_OK,
)
async def apply_rules_to_all_emails(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对数据库中已有邮件按当前规则重算标签（会清除旧标签），并按规则可选标已读。"""
    rules_result = await db.execute(
        select(MailRule).order_by(MailRule.rule_order, MailRule.id)
    )
    rules = list(rules_result.scalars().all())

    result = await db.execute(select(EmailRecord))
    records = list(result.scalars().all())
    updated = 0

    # 没有任何规则：视为“清空全部标签”，不改动已读状态。
    if not rules:
        for record in records:
            if (record.labels or "").strip() and (record.labels or "").strip() != "[]":
                record.labels = "[]"
                updated += 1
        await db.commit()
        return {"updated": updated, "total": len(records), "message": "已清空全部历史标签"}

    for record in records:
        body_text = (record.body_text or "") or (record.content_summary or "")
        labels_to_add, _skip_telegram, mark_read = apply_mail_rules(
            record, body_text, rules
        )
        # 重算：先清空旧标签，再按当前规则重新添加
        new_labels: list[str] = []
        seen: set[str] = set()
        for lb in labels_to_add:
            if lb not in seen:
                new_labels.append(lb)
                seen.add(lb)
        new_labels_json = json.dumps(new_labels, ensure_ascii=False)
        old_labels_json = (record.labels or "[]").strip() or "[]"
        record_changed = False
        if new_labels_json != old_labels_json:
            record.labels = new_labels_json
            record_changed = True
        if mark_read and not record.is_read:
            record.is_read = True
            record_changed = True
        if record_changed:
            updated += 1
    await db.commit()
    return {"updated": updated, "total": len(records), "message": "已按当前规则重算标签"}


@router.post(
    "/accounts/{account_id}/fetch_once",
    status_code=status.HTTP_200_OK,
)
async def fetch_once_for_account(
    account_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict:
    exists = await db.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = exists.scalars().first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # Update per-account poll status as a manual fetch.
    status_row = await db.get(AccountPollStatus, account_id)
    if not status_row:
        status_row = AccountPollStatus(account_id=account_id)
        db.add(status_row)

    started = datetime.utcnow()
    status_row.last_started_at = started
    status_row.last_error = None
    await db.commit()

    try:
        inserted = await fetch_recent_emails_for_account(
            db, account_id=account_id, allow_inactive=True
        )
        finished = datetime.utcnow()
        status_row.last_success_at = finished
        status_row.last_finished_at = finished
        await db.commit()
        return {"inserted": inserted}
    except Exception as exc:  # noqa: BLE001
        # Roll back any broken transaction before persisting error status.
        await db.rollback()
        msg = str(exc) or exc.__class__.__name__
        status_row = await db.get(AccountPollStatus, account_id)
        if not status_row:
            status_row = AccountPollStatus(account_id=account_id, last_started_at=started)
            db.add(status_row)
        status_row.last_finished_at = datetime.utcnow()
        status_row.last_error = msg
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"IMAP 拉取失败：{msg}",
        )


@router.get("/{email_id}", response_model=EmailRecordDetailOut)
async def get_email_detail(
    email_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rec = await db.get(EmailRecord, email_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not rec.is_read:
        rec.is_read = True
        await db.commit()
    stmt: Select = (
        select(
            EmailRecord.id,
            EmailRecord.message_id,
            EmailRecord.account_id,
            EmailAccount.email.label("account_email"),
            EmailRecord.subject,
            EmailRecord.sender,
            EmailRecord.content_summary,
            EmailRecord.received_at,
            EmailRecord.body_text,
            EmailRecord.body_html,
            EmailRecord.is_read,
            EmailRecord.labels,
        )
        .join(EmailAccount, EmailAccount.id == EmailRecord.account_id)
        .where(EmailRecord.id == email_id)
    )
    result = await db.execute(stmt)
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return dict(row)


