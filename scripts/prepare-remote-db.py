"""Prepare a remote Postgres (Aiven, or any TCP Postgres) for first deploy:
apply migrations, seed the demo world, and prove LISTEN/NOTIFY works —
that round-trip is the backbone of the SSE live prices, so it's verified
BEFORE the app is ever pointed at the database.

Run from the repo root:

    uv run --project services/api python scripts/prepare-remote-db.py "<URI>"

Accepts the URI in whatever shape the provider hands it (postgres:// or
postgresql://, `ssl-mode=` or `sslmode=`) and prints the exact normalized
value to paste into the Render dashboard as DATABASE_URL.
"""

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def normalize(dsn: str) -> str:
    """Provider URI → SQLAlchemy asyncpg DSN asyncpg can actually open."""
    if dsn.startswith("postgres://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgres://"):]
    elif dsn.startswith("postgresql://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    dsn = dsn.replace("ssl-mode=", "ssl=")  # Aiven's hyphenated form
    # asyncpg takes `ssl=`, not libpq's `sslmode=` (which it rejects as a
    # connect kwarg); same requirement, driver-native spelling.
    dsn = dsn.replace("sslmode=", "ssl=")
    if "ssl=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "ssl=require"
    return dsn


async def verify_listen_notify(raw_dsn: str) -> None:
    import asyncpg

    listener = await asyncpg.connect(raw_dsn)
    notifier = await asyncpg.connect(raw_dsn)
    received: asyncio.Queue[str] = asyncio.Queue()
    await listener.add_listener("market_ticks", lambda *_a, payload="": received.put_nowait(payload))
    await asyncio.sleep(0.3)  # let the LISTEN register
    await notifier.execute("SELECT pg_notify('market_ticks', $1)", '{"probe": true}')
    try:
        payload = await asyncio.wait_for(received.get(), timeout=5.0)
        print(f"LISTEN/NOTIFY round-trip ok ({payload}) — SSE live prices will work")
    except TimeoutError:
        print(
            "FAIL: NOTIFY was not delivered on a direct persistent connection.\n"
            "This provider cannot back the SSE stream; use a plain TCP Postgres\n"
            "(Aiven) or a direct (non-pooled) endpoint."
        )
        sys.exit(2)
    finally:
        await listener.close()
        await notifier.close()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dsn = normalize(sys.argv[1].strip())
    # app modules bind settings (and the engine) at import time
    os.environ["DATABASE_URL"] = dsn
    os.chdir(REPO / "services" / "api")

    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    print("migrations applied")

    from app.seed import main as seed_main

    asyncio.run(seed_main())
    print("demo world seeded (idempotent)")

    # raw asyncpg parses `sslmode=` in the DSN query (the SQLAlchemy dialect
    # wants the `ssl=` kwarg form instead — hence normalize()'s output)
    asyncio.run(verify_listen_notify(dsn.replace("+asyncpg", "").replace("ssl=", "sslmode=")))

    print("\nDATABASE_URL for the Render dashboard:")
    print(dsn)


if __name__ == "__main__":
    main()
