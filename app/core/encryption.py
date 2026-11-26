from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy.engine.url import make_url

from app.core.config import get_settings


def _is_valid_fernet_key(key: str) -> bool:
    try:
        Fernet(key.encode("utf-8"))
        return True
    except Exception:
        return False


def _get_persistent_key_path() -> Path | None:
    """
    When using a file-backed SQLite database (e.g. ./data/mail_agg.db in Docker),
    store the auto-generated key in the same persistent directory so container
    rebuilds do not lose the key and break decryption of saved passwords.
    """
    try:
        settings = get_settings()
        url = make_url(str(settings.database_url))
        if url.drivername.split("+", 1)[0] != "sqlite":
            return None
        db_path = url.database
        if not db_path or db_path == ":memory:":
            return None
        p = Path(db_path)
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        return p.parent / ".encryption_key"
    except Exception:
        return None


def ensure_encryption_key() -> str:
    """
    Ensure ENCRYPTION_KEY exists and is valid.

    Resolution order:
    1. Process env ENCRYPTION_KEY
    2. .env ENCRYPTION_KEY (via Settings)
    3. Persistent key file alongside SQLite DB (<db_dir>/.encryption_key)
    4. Generate new key and persist to <db_dir>/.encryption_key and .env
    """
    existing = (os.environ.get("ENCRYPTION_KEY") or "").strip()
    if existing and _is_valid_fernet_key(existing):
        return existing

    settings = get_settings()
    if settings.encryption_key and _is_valid_fernet_key(settings.encryption_key.strip()):
        key = settings.encryption_key.strip()
        os.environ["ENCRYPTION_KEY"] = key
        return key

    key_file = _get_persistent_key_path()
    if key_file and key_file.is_file():
        try:
            stored = key_file.read_text(encoding="utf-8").strip()
            if stored and _is_valid_fernet_key(stored):
                os.environ["ENCRYPTION_KEY"] = stored
                return stored
        except OSError:
            pass

    new_key = Fernet.generate_key().decode("utf-8")
    os.environ["ENCRYPTION_KEY"] = new_key

    if key_file:
        try:
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(new_key + "\n", encoding="utf-8")
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    env_path = Path(".env")
    try:
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        written = False
        out_lines: list[str] = []
        for line in lines:
            if line.strip().startswith("ENCRYPTION_KEY="):
                out_lines.append(f"ENCRYPTION_KEY={new_key}")
                written = True
            else:
                out_lines.append(line)
        if not written:
            if out_lines and out_lines[-1].strip() != "":
                out_lines.append("")
            out_lines.append(f"ENCRYPTION_KEY={new_key}")

        env_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return new_key


def get_fernet() -> Fernet:
    raw_key = (os.environ.get("ENCRYPTION_KEY") or "").strip()
    if not raw_key:
        settings = get_settings()
        raw_key = (settings.encryption_key or "").strip()
    if not raw_key or not _is_valid_fernet_key(raw_key):
        raise ValueError(
            "Invalid ENCRYPTION_KEY. Run once to generate a key or set ENCRYPTION_KEY in .env"
        )
    return Fernet(raw_key.encode("utf-8"))


def encrypt_secret(plain: str) -> str:
    f = get_fernet()
    return f.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    f = get_fernet()
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Invalid encryption token")


