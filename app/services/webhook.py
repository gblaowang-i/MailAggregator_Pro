import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.email import EmailRecord
from app.schemas.accounts import encode_utc_datetime


def _build_payload(record: EmailRecord, account_email: str) -> dict[str, Any]:
    labels: list[str] = []
    if record.labels:
        try:
            labels = json.loads(record.labels) if record.labels.strip() else []
        except Exception:
            pass
    return {
        "id": record.id,
        "message_id": record.message_id,
        "account_id": record.account_id,
        "account_email": account_email,
        "subject": record.subject or "",
        "sender": record.sender or "",
        "content_summary": (record.content_summary or "")[:500],
        "received_at": encode_utc_datetime(record.received_at) if record.received_at else None,
        "is_read": bool(record.is_read),
        "labels": labels,
    }


async def send_webhook_for_email(
    record: EmailRecord,
    account_email: str,
) -> None:
    """POST JSON payload to configured webhook URL. No-op if webhook_url not set."""
    settings = get_settings()
    url = (settings.webhook_url or "").strip()
    if not url:
        return

    payload = _build_payload(record, account_email)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                print(f"[webhook] non-2xx status={resp.status_code} url={url}")
    except Exception as exc:
        print(f"[webhook] send failed url={url}: {exc}")

