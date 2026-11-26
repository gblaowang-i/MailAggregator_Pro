from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def ensure_sqlite_columns(engine: AsyncEngine) -> None:
    """
    Lightweight schema patching for SQLite in dev.

    create_all() won't add new columns to existing tables. This ensures the
    new email body columns exist without introducing Alembic migrations yet.
    """
    async with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect != "sqlite":
            return

        # emails table: body_text/body_html
        res = await conn.execute(text("PRAGMA table_info(emails)"))
        cols = {row[1] for row in res.fetchall()}

        if "body_text" not in cols:
            await conn.execute(text("ALTER TABLE emails ADD COLUMN body_text TEXT"))
        if "body_html" not in cols:
            await conn.execute(text("ALTER TABLE emails ADD COLUMN body_html TEXT"))
        if "is_read" not in cols:
            await conn.execute(text("ALTER TABLE emails ADD COLUMN is_read INTEGER DEFAULT 0"))
        if "labels" not in cols:
            await conn.execute(text("ALTER TABLE emails ADD COLUMN labels TEXT DEFAULT '[]'"))
        if "created_at" not in cols:
            await conn.execute(text("ALTER TABLE emails ADD COLUMN created_at DATETIME DEFAULT NULL"))

        # accounts table: provider / sort_order
        res_acc = await conn.execute(text("PRAGMA table_info(accounts)"))
        acc_cols = {row[1] for row in res_acc.fetchall()}
        if "provider" not in acc_cols:
            await conn.execute(
                text("ALTER TABLE accounts ADD COLUMN provider VARCHAR(50) DEFAULT 'custom'")
            )
        if "sort_order" not in acc_cols:
            await conn.execute(
                text("ALTER TABLE accounts ADD COLUMN sort_order INTEGER DEFAULT 0")
            )
        if "telegram_push_enabled" not in acc_cols:
            await conn.execute(
                text("ALTER TABLE accounts ADD COLUMN telegram_push_enabled INTEGER DEFAULT 1")
            )
        if "push_template" not in acc_cols:
            await conn.execute(
                text("ALTER TABLE accounts ADD COLUMN push_template VARCHAR(32) DEFAULT 'short'")
            )
        if "poll_interval_seconds" not in acc_cols:
            await conn.execute(
                text("ALTER TABLE accounts ADD COLUMN poll_interval_seconds INTEGER DEFAULT NULL")
            )

        # mail_rules table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS mail_rules (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(128) DEFAULT '',
                rule_order INTEGER DEFAULT 0,
                account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                sender_pattern VARCHAR(512),
                subject_pattern VARCHAR(512),
                body_pattern VARCHAR(512),
                add_labels TEXT DEFAULT '[]',
                push_telegram INTEGER DEFAULT 1,
                mark_read INTEGER DEFAULT 0,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            )
        """))

        # system_settings: 界面修改的配置覆盖 .env（key-value）
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT NOT NULL PRIMARY KEY,
                value TEXT NOT NULL
            )
        """))

        # telegram_filter_rules table (new table)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telegram_filter_rules (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                field VARCHAR(32) NOT NULL,
                mode VARCHAR(16) NOT NULL,
                value TEXT NOT NULL,
                rule_order INTEGER DEFAULT 0,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            )
        """))

        # Performance indexes for email listing, filtering, stats, and cleanup
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_emails_received_at ON emails (received_at)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_emails_account_received ON emails (account_id, received_at)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_emails_is_read ON emails (is_read)")
        )


