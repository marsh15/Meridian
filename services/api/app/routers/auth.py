import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger
from app.config import settings
from app.db import get_session
from app.deps import current_user, require_user
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api")

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
COOKIE = settings.session_cookie


def user_payload(u: Any) -> dict:
    return {
        "id": u["id"],
        "email": u["email"],
        "displayName": u["display_name"],
        "balanceCents": int(u["balance_cents"]),
    }


async def _set_session_cookie(response: JSONResponse, user_id: int, session: AsyncSession) -> None:
    token = secrets.token_hex(32)
    await session.execute(
        text("INSERT INTO sessions (token, user_id) VALUES (:t, :u)"),
        {"t": token, "u": user_id},
    )
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", path="/",
        max_age=settings.session_max_age, secure=settings.cookie_secure,
    )


class SignupBody(BaseModel):
    email: str | None = None
    password: str | None = None
    displayName: str | None = None


@router.post("/auth/signup")
async def signup(
    body: SignupBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    body = body or SignupBody()
    email = body.email or ""
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "A valid email is required.")
    if not body.password or len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    name = (body.displayName or "").strip() or email.split("@")[0]
    if len(name) > 40:
        raise HTTPException(400, "Display name too long (max 40).")

    email = email.lower()
    async with session.begin():
        exists = await session.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email})
        if exists.first():
            raise HTTPException(409, "That email is already registered.")
        row = (
            await session.execute(
                text(
                    "INSERT INTO users (email, password_hash, display_name) "
                    "VALUES (:e, :p, :n) RETURNING id, email, display_name, balance_cents"
                ),
                {"e": email, "p": hash_password(body.password), "n": name},
            )
        ).first()
        await ledger.post_mint(
            session, row.id, int(row.balance_cents), "signup bonus"
        )
        resp = JSONResponse({"user": user_payload(row._mapping)})
        await _set_session_cookie(resp, row.id, session)
    return resp


class LoginBody(BaseModel):
    email: str | None = None
    password: str | None = None


@router.post("/auth/login")
async def login(
    body: LoginBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    body = body or LoginBody()
    async with session.begin():
        row = (
            await session.execute(
                text("SELECT * FROM users WHERE email = :e"), {"e": (body.email or "").lower()}
            )
        ).first()
        user = row._mapping if row else None
        if user is None or user["is_house"] or not verify_password(body.password or "", user["password_hash"]):
            raise HTTPException(401, "Wrong email or password.")
        resp = JSONResponse({"user": user_payload(user)})
        await _set_session_cookie(resp, user["id"], session)
    return resp


@router.post("/auth/logout")
async def logout(request: Request, session: AsyncSession = Depends(get_session)) -> JSONResponse:
    token = request.cookies.get(COOKIE)
    if token:
        async with session.begin():
            await session.execute(text("DELETE FROM sessions WHERE token = :t"), {"t": token})
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/auth/me")
async def me(user: dict | None = Depends(current_user)) -> dict:
    return {"user": user_payload(user) if user else None}


@router.post("/account/reset")
async def reset_account(
    user: dict = Depends(require_user), session: AsyncSession = Depends(get_session)
) -> dict:
    """Back to $1,000 and no open positions."""
    async with session.begin():
        current = (await session.execute(
            text("SELECT balance_cents FROM users WHERE id = :id FOR UPDATE"),
            {"id": user["id"]},
        )).scalar_one()
        await session.execute(
            text("UPDATE users SET balance_cents = :b WHERE id = :id"),
            {"b": settings.start_balance_cents, "id": user["id"]},
        )
        await session.execute(
            text("UPDATE positions SET shares = 0, cost_cents = 0 WHERE user_id = :id"),
            {"id": user["id"]},
        )
        delta = settings.start_balance_cents - int(current)
        if delta > 0:
            await ledger.post_mint(session, user["id"], delta, "account reset")
        elif delta < 0:
            await ledger.post_burn(session, user["id"], -delta, "account reset")
    row = (
        await session.execute(
            text("SELECT id, email, display_name, balance_cents FROM users WHERE id = :id"),
            {"id": user["id"]},
        )
    ).first()
    u = row._mapping
    return {"user": {"id": u["id"], "email": u["email"], "displayName": u["display_name"],
                     "balanceCents": int(u["balance_cents"])}}
