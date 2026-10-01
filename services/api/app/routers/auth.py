import asyncio
import re
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import ledger
from app.amm import price_yes, proceeds_for_shares
from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.events import record_event
from app.ratelimit import auth_limit, reset_limit
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api")

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
COOKIE = settings.session_cookie

# Verified against when the email doesn't exist, so login timing doesn't
# enumerate registered addresses
_DUMMY_HASH = hash_password("meridian-timing-equalizer")


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
        text("INSERT INTO sessions (token, user_id, expires_at) "
             "VALUES (:t, :u, now() + CAST(:age AS interval))"),
        {"t": token, "u": user_id, "age": timedelta(seconds=settings.session_max_age)},
    )
    # opportunistic GC: this user's expired tokens leave with each login
    await session.execute(
        text("DELETE FROM sessions WHERE user_id = :u AND expires_at < now()"), {"u": user_id}
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
    _rl: None = Depends(auth_limit),
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
    password_hash = await asyncio.to_thread(hash_password, body.password)
    async with session.begin():
        exists = await session.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email})
        if exists.first():
            raise HTTPException(409, "That email is already registered.")
        try:
            row = (
                await session.execute(
                    text(
                        "INSERT INTO users (email, password_hash, display_name) "
                        "VALUES (:e, :p, :n) RETURNING id, email, display_name, balance_cents"
                    ),
                    {"e": email, "p": password_hash, "n": name},
                )
            ).first()
        except IntegrityError as err:
            # concurrent signup with the same email won the unique race
            raise HTTPException(409, "That email is already registered.") from err
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
    _rl: None = Depends(auth_limit),
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
        # scrypt runs in a worker thread (30-100ms of CPU) and against the
        # dummy hash when the user doesn't exist, so the response neither
        # stalls the event loop nor reveals account existence by timing
        stored = user["password_hash"] if user is not None else _DUMMY_HASH
        ok = await asyncio.to_thread(verify_password, body.password or "", stored)
        if user is None or user["is_house"] or not ok:
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
    user: dict = Depends(reset_limit), session: AsyncSession = Depends(get_session)
) -> dict:
    """Back to the starting balance with no open positions. Holdings are
    sold-back first — escrow returns and the market's q/price
    rebases exactly as a normal sell would — then the balance tops up.
    The market is left consistent instead of holding inventory nobody owns."""
    async with session.begin():
        # lock order matches place_order: markets → user → positions
        await session.execute(
            text("SELECT m.id FROM markets m JOIN positions p ON p.market_id = m.id "
                 "WHERE p.user_id = :u AND p.shares > 0 ORDER BY m.id FOR UPDATE OF m"),
            {"u": user["id"]},
        )
        current = (await session.execute(
            text("SELECT balance_cents FROM users WHERE id = :id FOR UPDATE"),
            {"id": user["id"]},
        )).scalar_one()
        positions = (await session.execute(
            text("SELECT p.market_id, p.side, p.shares, m.slug, m.q_yes, m.q_no "
                 "FROM positions p JOIN markets m ON m.id = p.market_id "
                 "WHERE p.user_id = :u AND p.shares > 0 ORDER BY p.market_id FOR UPDATE"),
            {"u": user["id"]},
        )).mappings().all()

        proceeds_total = 0
        for p in positions:
            proceeds = proceeds_for_shares(p["q_yes"], p["q_no"], p["side"], p["shares"])
            amount_cents = round(float(proceeds) * 100)
            proceeds_total += amount_cents
            side_col = f"q_{p['side']}"
            await session.execute(
                text(f"UPDATE markets SET {side_col} = {side_col} - :sh WHERE id = :id"),
                {"sh": p["shares"], "id": p["market_id"]},
            )
            await session.execute(
                text("UPDATE positions SET shares = 0, cost_cents = 0 "
                     "WHERE user_id = :u AND market_id = :m AND side = :s"),
                {"u": user["id"], "m": p["market_id"], "s": p["side"]},
            )
            price_cents = round(Decimal(amount_cents) / p["shares"]) if amount_cents else 0
            trade_id = (await session.execute(
                text("INSERT INTO trades (market_id, user_id, side, action, shares, "
                     "price_cents, amount_cents) VALUES (:m,:u,:s,'sell',:sh,:p,:amt) "
                     "RETURNING id"),
                {"m": p["market_id"], "u": user["id"], "s": p["side"],
                 "sh": p["shares"], "p": price_cents, "amt": amount_cents},
            )).scalar_one()
            await ledger.post_trade(
                session, user_id=user["id"], market_id=p["market_id"],
                amount_cents=amount_cents, cash="in", trade_id=trade_id,
            )
            seq_row = (await session.execute(
                text("UPDATE markets SET event_seq = event_seq + 1 WHERE id = :id "
                     "RETURNING event_seq, q_yes, q_no"),
                {"id": p["market_id"]},
            )).first()
            price_after = round(price_yes(seq_row.q_yes, seq_row.q_no) * 100)
            await session.execute(
                text("INSERT INTO price_history (market_id, price_cents) VALUES (:m, :p)"),
                {"m": p["market_id"], "p": price_after},
            )
            await record_event(
                session, aggregate=f"market:{p['slug']}", event_type="TradeExecuted",
                payload={"slug": p["slug"], "seq": seq_row.event_seq, "side": p["side"],
                         "action": "sell", "shares": float(p["shares"]),
                         "priceCents": price_cents, "amountCents": amount_cents,
                         "trader": user["display_name"], "idempotencyKey": None},
                notify={"type": "tick", "slug": p["slug"], "seq": seq_row.event_seq,
                        "price": price_after, "status": "open", "outcome": None},
            )

        target = settings.start_balance_cents
        delta = target - (current + proceeds_total)
        await session.execute(
            text("UPDATE users SET balance_cents = :b WHERE id = :id"),
            {"b": target, "id": user["id"]}
        )
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
