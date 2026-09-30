"""Regenerate the AMM fixtures consumed by the web client's Vitest mirror
(apps/web/src/lib/__tests__/amm.fixtures.json). Run from the repo root:

    uv run --project services/api python scripts/gen-amm-fixtures.py

Every case is produced by the Python engine (app.amm) — the TS mirror in
apps/web/src/lib/amm.ts must reproduce these values within tight
tolerances, proving the client's live fill estimates can't drift from the
server's authority.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "services" / "api"))

from app.amm import price_yes, proceeds_for_shares, shares_for_dollars  # noqa: E402

PRICE_Q_GRID = [-100.0, -10.0, 0.0, 1.5, 10.0, 42.7, 100.0, 250.0, 600.0, 1200.0]
TRADE_Q_GRID = [0.0, 50.0, 250.0, 800.0]
DOLLARS = [1.0, 5.0, 10.0, 50.0, 123.45, 500.0, 1000.0]
SHARES = [0.1, 1.0, 2.5, 10.0, 25.1234567891, 100.0]


def main() -> None:
    price_cases = [
        {"qYes": qy, "qNo": qn, "price": price_yes(qy, qn)}
        for qy in PRICE_Q_GRID
        for qn in PRICE_Q_GRID
    ]
    share_cases = [
        {
            "qYes": qy, "qNo": qn, "side": side, "dollars": d,
            "shares": float(shares_for_dollars(qy, qn, side, d)),
        }
        for qy in TRADE_Q_GRID
        for qn in TRADE_Q_GRID
        for side in ("yes", "no")
        for d in DOLLARS
    ]
    proceed_cases = [
        {
            "qYes": qy, "qNo": qn, "side": side, "shares": s,
            "proceeds": float(proceeds_for_shares(qy, qn, side, s)),
        }
        for qy in TRADE_Q_GRID
        for qn in TRADE_Q_GRID
        for side in ("yes", "no")
        for s in SHARES
    ]

    out = REPO / "apps" / "web" / "src" / "lib" / "__tests__" / "amm.fixtures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "generator": "scripts/gen-amm-fixtures.py (Python LMSR engine)",
                "priceYes": price_cases,
                "sharesForDollars": share_cases,
                "proceedsForShares": proceed_cases,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"wrote {out}: {len(price_cases)} price, "
        f"{len(share_cases)} shares, {len(proceed_cases)} proceeds cases"
    )


if __name__ == "__main__":
    main()
