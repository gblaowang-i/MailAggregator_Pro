import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.email import EmailAccount
from app.models.poll_status import AccountPollStatus
from app.services.fetcher import fetch_recent_emails_for_account

last_poll_started_at: Optional[datetime] = None
last_poll_finished_at: Optional[datetime] = None
last_poll_error: Optional[str] = None

TICK_SECONDS = 5
MAX_CONCURRENT_ACCOUNTS = 4


def _resolve_global_interval() -> int:
    try:
        settings = get_settings()
        raw_interval = getattr(settings, "poll_interval_seconds", None)
        if raw_interval in (None, "", 0):
            return 300
        return max(int(raw_interval), 5)
    except Exception as exc:  # noqa: BLE001
        print(f"[poller] invalid poll_interval_seconds, fallback=300: {exc}")
        return 300


async def _poll_single_account(
    account_id: int,
    account_interval: Optional[int],
    global_interval: int,
    semaphore: asyncio.Semaphore,
) -> Optional[str]:
    interval = max(account_interval or global_interval, 5)
    async with semaphore:
        async with async_session_factory() as db:
            now = datetime.utcnow()
            status_row = await db.get(AccountPollStatus, account_id)
            if status_row and status_row.last_started_at:
                elapsed = (now - status_row.last_started_at).total_seconds()
                if elapsed < interval:
                    return None

            if not status_row:
                status_row = AccountPollStatus(account_id=account_id)
                db.add(status_row)
            status_row.last_started_at = now
            status_row.last_error = None
            await db.commit()

            err_msg: Optional[str] = None
            try:
                await fetch_recent_emails_for_account(db, account_id=account_id)
                finished = datetime.utcnow()
                status_row.last_success_at = finished
                status_row.last_finished_at = finished
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                err_msg = str(exc) or exc.__class__.__name__
                # Roll back any failed transaction before persisting status_row.last_error
                await db.rollback()
                status_row = await db.get(AccountPollStatus, account_id)
                if not status_row:
                    status_row = AccountPollStatus(account_id=account_id, last_started_at=now)
                    db.add(status_row)
                status_row.last_error = err_msg
                status_row.last_finished_at = datetime.utcnow()
                await db.commit()
            return err_msg


async def poller_loop() -> None:
    global last_poll_started_at, last_poll_finished_at, last_poll_error

    global_interval = _resolve_global_interval()
    print(f"[poller] loop started, global_interval={global_interval}s")
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ACCOUNTS)

    while True:
        last_poll_started_at = datetime.utcnow()
        last_poll_error = None

        try:
            # Dynamically reload global poll interval so Settings updates take effect immediately.
            global_interval = _resolve_global_interval()

            async with async_session_factory() as db_list:
                res = await db_list.execute(
                    select(EmailAccount.id, EmailAccount.poll_interval_seconds).where(
                        EmailAccount.is_active.is_(True)
                    )
                )
                active_accounts = list(res.all())

            if active_accounts:
                results = await asyncio.gather(
                    *(
                        _poll_single_account(acc_id, acc_interval, global_interval, semaphore)
                        for acc_id, acc_interval in active_accounts
                    ),
                    return_exceptions=True,
                )
                for item in results:
                    if isinstance(item, Exception):
                        last_poll_error = str(item)
                    elif isinstance(item, str) and item:
                        last_poll_error = item
        except asyncio.CancelledError:
            print("[poller] loop cancelled, shutting down")
            raise
        except Exception as exc:  # noqa: BLE001
            # 捕获所有意外错误，避免轮询任务直接退出
            last_poll_error = str(exc)
            print(f"[poller] unexpected error: {exc}")
        finally:
            last_poll_finished_at = datetime.utcnow()

        await asyncio.sleep(TICK_SECONDS)

