from __future__ import annotations

from datetime import timezone
from email.utils import parseaddr
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.models.email import EmailAccount, EmailRecord


def _get_record_field(record: EmailRecord, field: str) -> str:
    """Get the value for a rule field (sender, domain, subject, body). Case-insensitive match."""
    raw: str
    if field == "sender":
        raw = record.sender or ""
    elif field == "domain":
        s = record.sender or ""
        _, addr = parseaddr(s)
        target = addr or s
        if "@" in target:
            raw = target.split("@")[-1].strip().strip(">")
        else:
            raw = target.strip()
    elif field == "subject":
        raw = record.subject or ""
    elif field == "body":
        raw = (record.body_text or record.content_summary or "")[:2000]
    else:
        raw = ""
    return raw.lower()


def should_push_telegram(
    record: EmailRecord,
    account: EmailAccount,
    rules: list[Any],
    skip_from_mail_rules: bool = False,
) -> bool:
    """
    Decide whether to push this email to Telegram based on account settings and rules.
    - If account.telegram_push_enabled is False, never push.
    - If skip_from_mail_rules is True (matched a global mail rule that disables push), do not push.
    - Deny rules: if any rule (mode=deny) matches, do not push.
    - Allow rules: if there are allow rules, at least one must match; if no allow rules, push (unless deny matched).
    """
    if not getattr(account, "telegram_push_enabled", True):
        return False
    if skip_from_mail_rules:
        return False
    allow_rules = [r for r in rules if getattr(r, "mode", "") == "allow"]
    deny_rules = [r for r in rules if getattr(r, "mode", "") == "deny"]
    for r in deny_rules:
        val = (getattr(r, "value", None) or "").strip().lower()
        if not val:
            continue
        if val in _get_record_field(record, getattr(r, "field", "")):
            return False
    if allow_rules:
        for r in allow_rules:
            val = (getattr(r, "value", None) or "").strip().lower()
            if not val:
                continue
            if val in _get_record_field(record, getattr(r, "field", "")):
                return True
        return False
    return True


async def send_telegram_message(text: str) -> None:
    """
    Send a raw text message via Telegram Bot API.
    If Telegram is not configured, this is a no-op.
    """
    settings = get_settings()
    token: Optional[str] = settings.telegram_bot_token
    chat_id: Optional[str] = settings.telegram_chat_id

    if not token or not chat_id:
        # Telegram 未配置时直接跳过；打日志便于排查“收不到推送”问题。
        print("[telegram] skip: telegram_bot_token or telegram_chat_id not set (check Settings / system_settings)")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, json=payload)
            # 记录 Telegram API 返回是否成功，方便排查 chat_id / token 等配置问题。
            try:
                data = resp.json()
            except Exception:
                data = None
            ok_flag = bool(data and data.get("ok"))
            if not ok_flag:
                snippet = resp.text[:200].replace("\n", " ")
                print(f"[telegram] api error status={resp.status_code} body={snippet}")
        except Exception as exc:
            # 避免影响主流程，但将错误打印到日志，便于排查 Telegram 推送失败原因。
            print(f"[telegram] send failed: {exc}")
            return


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_html_truncated(raw: str, max_escaped_len: int) -> str:
    """
    HTML-escape `raw` while guaranteeing the escaped result does not exceed
    `max_escaped_len` characters and never splits an HTML entity like `&amp;`.
    """
    if max_escaped_len <= 0:
        return ""
    escaped_full = _escape_html(raw)
    if len(escaped_full) <= max_escaped_len:
        return escaped_full

    budget = max_escaped_len - 1  # reserve 1 char for ellipsis
    out: list[str] = []
    cur_len = 0
    for ch in raw:
        if ch == "&":
            part = "&amp;"
        elif ch == "<":
            part = "&lt;"
        elif ch == ">":
            part = "&gt;"
        else:
            part = ch
        if cur_len + len(part) > budget:
            break
        out.append(part)
        cur_len += len(part)
    return "".join(out) + "…"


def _build_preview(preview_source: str, max_lines: int = 8, max_len: int = 80, max_escaped_len: int = 3500) -> str:
    preview_lines: list[str] = []
    for ln in preview_source.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if len(ln) > max_len:
            ln = ln[: max_len - 1] + "…"
        preview_lines.append(ln)
        if len(preview_lines) >= max_lines:
            break
    if not preview_lines:
        return ""
    return _escape_html_truncated("\n".join(preview_lines), max_escaped_len)


async def send_email_notification(
    record: EmailRecord,
    account: EmailAccount,
    template: Optional[str] = None,
) -> None:
    """
    Push a formatted email notification to Telegram.
    template: "full_email" | "full" (long preview) | "short" (fewer lines) | "title_only" (no body).
    """
    template = template or getattr(account, "push_template", "short") or "short"
    subject_raw = record.subject or "(无主题)"
    sender_raw = record.sender or ""
    account_email_raw = account.email or ""

    subject = _escape_html_truncated(subject_raw, 300)
    sender = _escape_html_truncated(sender_raw, 200)
    account_email = _escape_html_truncated(account_email_raw, 200)

    lines: list[str] = [
        f"📬 <b>{subject}</b>",
        f"发件人: <code>{sender}</code>",
        f"账户: <code>{account_email}</code>",
    ]
    if record.received_at:
        dt = record.received_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc).astimezone()
        else:
            dt = dt.astimezone()
        lines.append(f"时间: {dt:%Y-%m-%d %H:%M}")

    header_text = "\n".join(lines)
    if template != "title_only":
        preview_source = (record.body_text or record.content_summary or "").strip()
        if preview_source:
            label = "正文：" if template == "full_email" else "内容预览："
            # Reserve exact budget so total message stays <= 4096 without cutting HTML tags/entities
            overhead = len(header_text) + 2 + len(label) + 1
            remaining_budget = max(0, 4096 - overhead)
            if template == "full_email":
                preview = _escape_html_truncated(preview_source, min(3800, remaining_budget))
            elif template == "full":
                preview = _build_preview(preview_source, max_lines=12, max_len=80, max_escaped_len=remaining_budget)
            else:
                preview = _build_preview(preview_source, max_lines=4, max_len=60, max_escaped_len=remaining_budget)
            if preview:
                lines.append("")
                lines.append(label)
                lines.append(preview)

    text = "\n".join(lines)
    await send_telegram_message(text)


