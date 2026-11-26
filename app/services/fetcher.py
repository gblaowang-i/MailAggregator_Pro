from datetime import datetime, timedelta, timezone

import asyncio
import json

from anyio import to_thread
from bs4 import BeautifulSoup
from imap_tools import AND, MailBox, MailBoxUnencrypted
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_secret
from app.models.email import EmailAccount, EmailRecord
from app.models.mail_rule import MailRule
from app.models.telegram_rule import TelegramFilterRule
from app.services.rules_engine import apply_mail_rules
from app.services.telegram import send_email_notification, should_push_telegram
from app.services.webhook import send_webhook_for_email

IMAP_SOCKET_TIMEOUT_SEC = 30
IMAP_FETCH_TIMEOUT_SEC = 120
DB_BATCH_QUERY_SIZE = 500

# Per-account lock to prevent concurrent poller + manual fetch_once races.
_account_locks: dict[int, asyncio.Lock] = {}


def _get_account_lock(account_id: int) -> asyncio.Lock:
    lock = _account_locks.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        _account_locks[account_id] = lock
    return lock


def _to_naive_utc(dt: datetime | None) -> datetime:
    """Normalize any datetime (aware or naive) to naive UTC for consistent storage & sorting."""
    if dt is None:
        return datetime.utcnow()
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _extract_rfc_message_id(msg: object) -> str:
    msg_id = getattr(msg, "message_id", None)
    if isinstance(msg_id, str) and msg_id.strip():
        return msg_id.strip()

    headers = getattr(msg, "headers", None)
    if isinstance(headers, dict):
        for k, val in headers.items():
            if str(k).lower() == "message-id":
                if isinstance(val, (tuple, list)):
                    for item in val:
                        if isinstance(item, str) and item.strip():
                            return item.strip()
                elif isinstance(val, str) and val.strip():
                    return val.strip()
    return ""


def _extract_message_id(msg: object, account_id: int) -> tuple[str, str]:
    """
    Return (primary_message_id, legacy_rfc_message_id).

    Using account-scoped UID (`{account_id}:{uid}`) preserves full backward compatibility
    with existing SQLite rows produced by imap_tools (where headers['message-id'] is a tuple)
    and guarantees two accounts receiving the same email never collide on the UNIQUE constraint.
    """
    rfc_id = _extract_rfc_message_id(msg)
    uid = getattr(msg, "uid", None)
    if uid:
        return f"{account_id}:{uid}", rfc_id
    if rfc_id:
        return f"{account_id}:{rfc_id}", rfc_id
    return "", ""


def _to_plain_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


async def fetch_recent_emails_for_account(
    db: AsyncSession,
    account_id: int,
    lookback_hours: int = 24,
    allow_inactive: bool = False,
) -> int:
    lock = _get_account_lock(account_id)
    async with lock:
        return await _fetch_recent_emails_locked(
            db,
            account_id=account_id,
            lookback_hours=lookback_hours,
            allow_inactive=allow_inactive,
        )


async def _fetch_recent_emails_locked(
    db: AsyncSession,
    account_id: int,
    lookback_hours: int = 24,
    allow_inactive: bool = False,
) -> int:
    result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalars().first()
    if not account or (not allow_inactive and not account.is_active):
        return 0

    print(f"[telegram] fetch_start account_id={account_id}")
    existing_count = await db.execute(
        select(func.count(EmailRecord.id)).where(EmailRecord.account_id == account_id)
    )
    existing_total = int(existing_count.scalar_one() or 0)

    # 初次同步：会拉取大量历史邮件用于填充列表，但不应触发“新邮件推送”，否则会疯狂推送历史邮件。
    # 判断条件改为“数据库里目前一封都没有”，只在第一次抓取时视为初次同步。
    is_initial_sync = existing_total == 0

    if is_initial_sync:
        # 初次或接近初次同步：拉取更长时间、更多数量的历史邮件。
        since_dt = datetime.utcnow() - timedelta(days=365)
        max_messages = 1000
    else:
        # 之后走增量：最近 lookback_hours 小时内的新邮件即可。
        since_dt = datetime.utcnow() - timedelta(hours=lookback_hours)
        max_messages = 200

    password = decrypt_secret(account.encrypted_pwd)
    port = int(account.port or 993)

    def _fetch_sync() -> list[tuple[str, str, str, str, datetime, str, str]]:
        items: list[tuple[str, str, str, str, datetime, str, str]] = []
        mailbox_cls = MailBoxUnencrypted if port == 143 else MailBox
        with mailbox_cls(
            account.host,
            port=port,
            timeout=IMAP_SOCKET_TIMEOUT_SEC,
        ).login(account.email, password, "INBOX") as mbox:
            for msg in mbox.fetch(
                AND(date_gte=since_dt.date()),
                reverse=True,
                limit=max_messages,
            ):
                message_id, legacy_rfc_id = _extract_message_id(msg, account.id)
                if not message_id:
                    continue
                subject = msg.subject or ""
                sender = msg.from_ or ""
                received_at = _to_naive_utc(getattr(msg, "date", None))
                html = getattr(msg, "html", None) or ""
                text = getattr(msg, "text", None) or ""
                if not text and html:
                    text = _to_plain_text(html)
                items.append((message_id, legacy_rfc_id, subject, sender, received_at, text, html))
        return items

    try:
        fetched = await asyncio.wait_for(
            to_thread.run_sync(_fetch_sync),
            timeout=IMAP_FETCH_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"IMAP 连接或拉取超时（>{IMAP_FETCH_TIMEOUT_SEC}s）") from exc

    # Batch-fetch existing EmailRecords by message_id to avoid N+1 SQL queries.
    candidate_ids: set[str] = set()
    for message_id, legacy_rfc_id, *_ in fetched:
        candidate_ids.add(message_id)
        if legacy_rfc_id:
            candidate_ids.add(legacy_rfc_id)

    existing_by_mid: dict[str, EmailRecord] = {}
    candidate_list = list(candidate_ids)
    for i in range(0, len(candidate_list), DB_BATCH_QUERY_SIZE):
        chunk = candidate_list[i : i + DB_BATCH_QUERY_SIZE]
        q = await db.execute(select(EmailRecord).where(EmailRecord.message_id.in_(chunk)))
        for rec in q.scalars().all():
            existing_by_mid[rec.message_id] = rec

    mail_rules_result = await db.execute(
        select(MailRule).order_by(MailRule.rule_order, MailRule.id)
    )
    mail_rules = list(mail_rules_result.scalars().all())

    inserted = 0
    updated = 0
    seen_in_batch: set[str] = set()
    new_entries: list[tuple[EmailRecord, bool]] = []

    for message_id, legacy_rfc_id, subject, sender, received_at, body_text, body_html in fetched:
        if message_id in seen_in_batch:
            continue
        seen_in_batch.add(message_id)

        existing = existing_by_mid.get(message_id)
        if existing is None and legacy_rfc_id:
            legacy_rec = existing_by_mid.get(legacy_rfc_id)
            if legacy_rec is not None and legacy_rec.account_id == account.id:
                existing = legacy_rec

        # If already exists, backfill body fields when missing.
        if existing:
            changed = False
            if (not existing.body_text) and body_text:
                existing.body_text = body_text
                changed = True
            if (not existing.body_html) and body_html:
                existing.body_html = body_html
                changed = True
            # Keep summary aligned with body when it was previously just a subject snippet.
            if changed and existing.content_summary == (existing.subject or "")[:200]:
                summary_src = body_text or existing.subject or ""
                existing.content_summary = summary_src.replace("\r", "").strip()[:200]
            if changed:
                updated += 1
            continue

        summary_src = body_text or subject
        summary = (summary_src or "").replace("\r", "").strip()[:200]
        record = EmailRecord(
            message_id=message_id,
            account_id=account.id,
            subject=subject[:255],
            sender=sender[:255],
            content_summary=summary,
            body_text=(body_text or None),
            body_html=(body_html or None),
            received_at=received_at,
            created_at=datetime.utcnow(),
        )
        labels_to_add, skip_telegram, mark_read = apply_mail_rules(
            record, body_text or "", mail_rules
        )
        if labels_to_add:
            record.labels = json.dumps(labels_to_add, ensure_ascii=False)
        if mark_read:
            record.is_read = True

        db.add(record)
        inserted += 1
        new_entries.append((record, skip_telegram))

    if inserted or updated:
        await db.commit()

    telegram_rules_result = await db.execute(
        select(TelegramFilterRule)
        .where(TelegramFilterRule.account_id == account.id)
        .order_by(TelegramFilterRule.rule_order, TelegramFilterRule.id)
    )
    telegram_rules = list(telegram_rules_result.scalars().all())

    # 初次同步仅入库不推送；非初次时 new_entries 仅含本轮新插入的邮件，再叠加“最近 N 小时内”才推送，避免轰炸。
    PUSH_RECENCY_HOURS = 12
    recency_threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=PUSH_RECENCY_HOURS)

    TELEGRAM_PUSH_DELAY_SEC = 1.5
    MAX_PUSH_PER_ACCOUNT_PER_RUN = 30

    # 每次拉取都打一行，便于确认是否走到推送逻辑（若无新邮件则 new_records=0，不会推送）
    print(f"[telegram] account_id={account.id} is_initial_sync={is_initial_sync} new_records={len(new_entries)}")

    if not is_initial_sync:
        pushed_count = 0
        recency_skipped = 0
        push_errors = 0
        for record, skip_from_mail in new_entries:
            r_at = _to_naive_utc(record.received_at) if record.received_at is not None else None
            if r_at is not None and r_at < recency_threshold:
                recency_skipped += 1
                await send_webhook_for_email(record, account.email)
                continue
            if pushed_count >= MAX_PUSH_PER_ACCOUNT_PER_RUN:
                await send_webhook_for_email(record, account.email)
                continue
            if should_push_telegram(
                record, account, telegram_rules, skip_from_mail
            ):
                try:
                    await send_email_notification(record, account)
                    pushed_count += 1
                    if pushed_count < MAX_PUSH_PER_ACCOUNT_PER_RUN:
                        await asyncio.sleep(TELEGRAM_PUSH_DELAY_SEC)
                except Exception as exc:  # noqa: BLE001
                    push_errors += 1
                    print(f"[telegram] account_id={account.id} push_error: {exc}")
            await send_webhook_for_email(record, account.email)
        if new_entries:
            hint = f" (超过{PUSH_RECENCY_HOURS}h未推送)" if recency_skipped else ""
            err_hint = f" errors={push_errors}" if push_errors else ""
            print(
                f"[telegram] account_id={account.id} new_emails={len(new_entries)} "
                f"recency_skipped={recency_skipped} pushed={pushed_count}{hint}{err_hint}"
            )
    elif new_entries:
        print(f"[telegram] account_id={account.id} initial_sync new_emails={len(new_entries)} (no push)")

    return inserted + updated


