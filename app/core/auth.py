from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from typing import Optional

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import get_settings

JWT_ALG = "HS256"
JWT_EXP_HOURS = 24 * 7  # 7 days
_EPHEMERAL_FALLBACK_SECRET = secrets.token_hex(32)


def _jwt_secret() -> str:
    s = get_settings()
    if s.jwt_secret and s.jwt_secret.strip():
        return s.jwt_secret.strip()
    if s.api_token and s.api_token.strip():
        return s.api_token.strip()
    # Derive a stable per-instance secret from ENCRYPTION_KEY instead of a hardcoded public string.
    enc_key = (os.environ.get("ENCRYPTION_KEY") or s.encryption_key or "").strip()
    if enc_key:
        return hashlib.sha256(f"mail-tool-jwt:{enc_key}".encode("utf-8")).hexdigest()
    return _EPHEMERAL_FALLBACK_SECRET


def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)


def decode_jwt(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALG])
        return payload.get("sub")
    except Exception:
        return None


def login_required() -> bool:
    """True if admin username is set and password is configured (env or DB hash)."""
    from app.core.config import has_stored_admin_password
    s = get_settings()
    if not (s.admin_username and s.admin_username.strip()):
        return False
    if has_stored_admin_password():
        return True
    return s.admin_password is not None and bool(str(s.admin_password).strip())


def api_token_configured() -> bool:
    """True if a static API_TOKEN is configured."""
    s = get_settings()
    return bool((s.api_token or "").strip())


async def verify_api_token(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Require valid API token or JWT when API_TOKEN or admin login is configured."""
    settings = get_settings()
    static_token = (settings.api_token or "").strip()
    need_auth = bool(static_token) or login_required()

    if not need_auth:
        return

    provided: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        provided = authorization[7:].strip()
    if not provided and x_api_key:
        provided = (x_api_key or "").strip()

    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证信息，请先登录或提供 API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if static_token and hmac.compare_digest(provided, static_token):
        return

    username = decode_jwt(provided)
    expected_user = (settings.admin_username or "").strip()
    if username and expected_user and hmac.compare_digest(username, expected_user):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败或已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )

