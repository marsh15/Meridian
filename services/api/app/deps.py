from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from app.config import settings
from app.db import SessionFactory


async def current_user(request: Request) -> dict[str, Any] | None:
    """Resolves the session cookie against users. Uses its own short-lived
    session so it never leaves a transaction open on the request's session —
    write endpoints depend on starting one cleanly. Tokens past expires_at
    are treated as absent (logins sweep the dead rows away)."""
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    async with SessionFactory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT u.id, u.email, u.display_name, u.balance_cents "
                    "FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token = :token AND s.expires_at > now()"
                ),
                {"token": token},
            )
        ).first()
    return row._mapping if row else None


async def require_user(user: dict | None = Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to do that.")
    return user
