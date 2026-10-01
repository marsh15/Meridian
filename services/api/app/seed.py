"""Seeds the demo world: 12 sample markets authored by the house account,
12 named demo traders (login disabled via is_house), 2 trader-authored
markets, and a replay of small trades so feeds/holders show activity.
Ported from server/seed-data.js + server/db.js; idempotent via marker rows.

Run: uv run python -m app.seed
"""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.amm import opening_q, price_yes, proceeds_for_shares, shares_for_dollars
from app.db import SessionFactory

SEED_MARKETS = [
    {"id": "fed-cut-nov-2026", "ticker": "FED.CUT26",
         "question": "Will the Fed cut rates at the November 2026 meeting?",
         "category": "Economics", "yes": 68, "volume": 4_820_000, "traders": 11_400, "closes": "2026-11-05",
         "description": ("This market resolves YES if the Federal Open Market Committee lowers the "
                      "federal funds target rate at its November 2026 meeting. Futures pricing has "
                      "swung between 55¢ and 75¢ over the past month as CPI prints and labor data "
                      "alternately embolden and restrain the doves."),
         "resolution": ("Resolves YES if the FOMC statement released after the November 3–4, 2026 "
                     "meeting announces a lower target range for the federal funds rate.")},
    {"id": "democrat-wins-2028", "ticker": "POTUS.28D",
         "question": "Will a Democrat win the 2028 US presidential election?",
         "category": "Politics", "yes": 54, "volume": 12_750_000, "traders": 41_200, "closes": "2028-11-07",
         "description": ("Resolves YES if the Democratic nominee wins a majority of the electoral "
                      "college in the 2028 US presidential election, as certified by Congress. "
                      "Early trading typically tracks generic-ballot polling and incumbent-party "
                      "fatigue measures."),
         "resolution": "Resolves per the certification of the 2028 electoral college results by a joint session of Congress."},
    {"id": "btc-150k-2026", "ticker": "BTC.150K",
         "question": "Will Bitcoin close above $150,000 on Dec 31, 2026?",
         "category": "Crypto", "yes": 32, "volume": 8_930_000, "traders": 26_800, "closes": "2026-12-31",
         "description": ("Resolves YES if the BTC/USD price on Coinbase closes at or above $150,000 "
                      "at 23:59:59 UTC on December 31, 2026. The market peaked at 71¢ after the "
                      "spring halving rally before fading alongside risk-off macro sentiment."),
         "resolution": "Resolves using the 1-day candle close on Coinbase for December 31, 2026, in UTC."},
    {"id": "spx-7500-2026", "ticker": "SPX.7500",
         "question": "Will the S&P 500 finish 2026 above 7,500?",
         "category": "Economics", "yes": 46, "volume": 5_640_000, "traders": 18_700, "closes": "2026-12-31",
         "description": ("Resolves YES if the S&P 500 index closes above 7,500 on the final trading "
                      "day of 2026. Earnings breadth has been strong, but multiple expansion is "
                      "stretched by historical standards — traders are split almost down the middle."),
         "resolution": "Resolves to the official closing print of the S&P 500 on the last NYSE trading day of 2026."},
    {"id": "apple-ar-headset", "ticker": "AAPL.AR",
         "question": "Will Apple announce a new AR headset in 2026?",
         "category": "Tech", "yes": 41, "volume": 2_210_000, "traders": 9_400, "closes": "2026-12-31",
         "description": ("Resolves YES if Apple formally announces a new augmented-reality headset "
                      "(or major successor to Vision Pro) at any point during calendar year 2026. "
                      "Leaked CAD drawings and display orders have kept this market lively despite "
                      "no official word."),
         "resolution": "Resolves YES upon an Apple press release or keynote announcement of a new AR headset product."},
    {"id": "starship-mars-2026", "ticker": "STSHIP.MRS",
         "question": "Will SpaceX Starship depart for Mars in 2026?",
         "category": "Science", "yes": 12, "volume": 1_310_000, "traders": 7_100, "closes": "2026-12-31",
         "description": ("Resolves YES if a Starship vehicle departs Earth orbit on a Mars transfer "
                      "trajectory before the end of 2026. The Hohmann transfer window opens in "
                      "October, but unfueled-dep skepticism keeps this market cheap."),
         "resolution": "Resolves YES if SpaceX confirms a trans-Mars injection burn of a Starship vehicle in 2026."},
    {"id": "ai-film-oscar-2030", "ticker": "AI.OSCAR30",
         "question": "Will an AI-generated film win an Oscar by 2030?",
         "category": "Culture", "yes": 24, "volume": 980_000, "traders": 5_900, "closes": "2030-03-31",
         "description": ("Resolves YES if a film that uses AI-generated video for a majority of its "
                      "runtime wins any Academy Award in a competitive category before the March "
                      "2030 ceremony. Current Academy rules require disclosed human authorship for "
                      "eligibility in some categories."),
         "resolution": "Resolves YES per the Academy of Motion Picture Arts and Sciences official winners list."},
    {"id": "swift-tour-2027", "ticker": "TSWIFT.27",
         "question": "Will Taylor Swift announce a 2027 world tour?",
         "category": "Culture", "yes": 58, "volume": 1_740_000, "traders": 9_900, "closes": "2027-06-30",
         "description": ("Resolves YES if Taylor Swift or her label officially announces a concert "
                      "tour with dates in 2027. Historically, tour announcements follow roughly "
                      "4–8 months after a major album release cycle."),
         "resolution": "Resolves YES on an official artist or label announcement of a tour including 2027 dates."},
    {"id": "nyc-90-christmas", "ticker": "NYC.XMAS90",
         "question": "Will NYC hit 90°F on Christmas Day 2026?",
         "category": "Weather", "yes": 4, "volume": 340_000, "traders": 3_300, "closes": "2026-12-25",
         "description": ("Resolves YES if the National Weather Service records a temperature of 90°F "
                      "or higher in Central Park on December 25, 2026. The all-time record for "
                      "that date is 64°F, set in 1964 — hence the deep longshot pricing."),
         "resolution": "Resolves to the NWS Central Park daily high for December 25, 2026."},
    {"id": "eth-flips-btc", "ticker": "ETH.FLIP",
         "question": "Will Ethereum flip Bitcoin market cap by 2028?",
         "category": "Crypto", "yes": 8, "volume": 1_120_000, "traders": 6_100, "closes": "2028-12-31",
         "description": ("Resolves YES if Ethereum market capitalization exceeds Bitcoin market "
                      "capitalization on any day before January 1, 2029, per CoinGecko aggregated "
                      "data. ETH last closed the gap to under 40% of BTC cap in 2021."),
         "resolution": "Resolves YES if ETH market cap exceeds BTC market cap at any daily close before 2029."},
    {"id": "artemis-moon-2027", "ticker": "ARTEMIS.MN",
         "question": "Will astronauts land on the Moon before 2028?",
         "category": "Science", "yes": 61, "volume": 2_010_000, "traders": 8_800, "closes": "2027-12-31",
         "description": ("Resolves YES if a crewed spacecraft touches down on the lunar surface with "
                      "living astronauts aboard before January 1, 2028. No human has walked on "
                      "the Moon since Apollo 17 in December 1972."),
         "resolution": "Resolves YES upon confirmed crewed lunar surface landing per NASA or the operating agency."},
    {"id": "chiefs-sb-lxi", "ticker": "KC.SB61",
         "question": "Will the Chiefs reach Super Bowl LXI?",
         "category": "Sports", "yes": 37, "volume": 3_320_000, "traders": 22_400, "closes": "2027-02-14",
         "description": ("Resolves YES if the Kansas City Chiefs play in Super Bowl LXI in February "
                      "2027. Dynasty pricing is getting expensive against a deeper field of AFC "
                      "contenders than at any point in the Mahomes era."),
         "resolution": "Resolves YES if the Chiefs appear in Super Bowl LXI, per the NFL."},
]

DEMO_TRADERS = [
    ("Maya Chen", "maya.chen"), ("Dele Okafor", "dele.okafor"), ("Priya Nair", "priya.nair"),
    ("Tomás Rivera", "tomas.rivera"), ("June Park", "june.park"), ("Marcus Webb", "marcus.webb"),
    ("Aisha Diallo", "aisha.diallo"), ("Felix Grant", "felix.grant"), ("Nadia Kovač", "nadia.kovac"),
    ("Ellis Moore", "ellis.moore"), ("Ruth Abrams", "ruth.abrams"), ("Kenji Sato", "kenji.sato"),
]

EXTRA_MARKETS = [
    {"slug": "openai-gpt6-july-2027", "ticker": "OAI.GPT6",
         "question": "Will OpenAI ship a GPT-6 model before July 2027?",
         "category": "Tech", "yes": 44, "closes": "2027-06-30", "by": "Maya Chen",
         "description": ("Resolves YES if OpenAI publicly releases a model branded GPT-6 (or "
                      "equivalent flagship successor) before July 1, 2027. Release cadence "
                      "assumptions are the main swing factor — the crowd has bounced between "
                      "35¢ and 55¢ since opening."),
         "resolution": "Resolves YES upon public availability of a GPT-6-branded model per OpenAI announcements."},
    {"slug": "knicks-ecf-2027", "ticker": "NYK.ECF27",
         "question": "Will the Knicks reach the 2027 Eastern Conference Finals?",
         "category": "Sports", "yes": 29, "closes": "2027-06-15", "by": "Marcus Webb",
         "description": ("Resolves YES if the New York Knicks appear in the 2027 Eastern Conference "
                      "Finals. Health-adjusted depth models put them firmly in the contender mix, "
                      "but the East is brutal at the top."),
         "resolution": "Resolves YES if the Knicks play in the 2027 ECF, per the NBA."},
]


def gen_history(seed_id: str, current: float, n: int = 48) -> list[int]:
    """Deterministic walk ending exactly at the opening price."""
    rand = random.Random(seed_id)
    p = current + (rand.random() * 44 - 22)
    pts = []
    for _ in range(n):
        p += (rand.random() - 0.5) * 7 + (current - p) * 0.07
        p = min(97.0, max(3.0, p))
        pts.append(p)
    pts[-1] = float(current)
    return [round(v) for v in pts]


async def insert_history(session, market_id: int, history: list[int], days_span: float) -> None:
    now = datetime.now(UTC)
    rows = []
    for i, p in enumerate(history):
        days_ago = days_span - (days_span / (len(history) - 1)) * i
        rows.append({"m": market_id, "p": p, "at": now - timedelta(days=days_ago)})
    await session.execute(
        text("INSERT INTO price_history (market_id, price_cents, created_at) "
             "VALUES (:m, :p, :at)"),
        rows,
    )


async def seed_sample_markets(session) -> None:
    house = (
        await session.execute(
            text("INSERT INTO users (email, password_hash, display_name, is_house) "
                 "VALUES ('house@meridian.demo', 'x', 'Meridian', true) "
                 "ON CONFLICT (email) DO UPDATE SET display_name = 'Meridian' RETURNING id")
        )
    ).scalar_one()
    now = datetime.now(UTC)
    for m in SEED_MARKETS:
        q_yes, q_no = opening_q(m["yes"])
        mid = (
            await session.execute(
                text(
                    "INSERT INTO markets (slug, ticker, question, category, description, "
                    "resolution_rules, closes_at, creator_id, q_yes, q_no, seed_volume_cents, "
                    "seed_traders, created_at) VALUES (:slug,:ticker,:q,:cat,:descr,:res,:close,"
                    ":creator,:qy,:qn,:vol,:traders, :created) RETURNING id"
                ),
                {
                    "slug": m["id"], "ticker": m["ticker"], "q": m["question"],
                    "cat": m["category"], "descr": m["description"], "res": m["resolution"],
                    "close": datetime.fromisoformat(f"{m['closes']}T23:59:59+00:00"),
                    "creator": house, "qy": q_yes, "qn": q_no,
                    "vol": m["volume"] * 100, "traders": m["traders"],
                    "created": now - timedelta(days=30),
                },
            )
        ).scalar_one()
        await insert_history(session, mid, gen_history(m["id"], m["yes"]), 30)
    print(f"Seeded {len(SEED_MARKETS)} sample markets")


async def seed_demo_activity(session) -> None:
    marker = await session.execute(
        text("SELECT 1 FROM users WHERE email = 'maya.chen@demo.meridian'")
    )
    if marker.first():
        return

    rand = random.Random(0x5EEDFEED)

    # demo traders: named accounts, unusable credentials, login blocked via is_house
    user_ids: dict[str, int] = {}
    for name, slug in DEMO_TRADERS:
        uid = (
            await session.execute(
                text("INSERT INTO users (email, password_hash, display_name, is_house) "
                     "VALUES (:e, :h, :n, true) RETURNING id"),
                {"e": f"{slug}@demo.meridian", "h": f"{rand.getrandbits(128):032x}:{rand.getrandbits(256):064x}", "n": name},
            )
        ).scalar_one()
        user_ids[name] = uid
    balances = dict.fromkeys(user_ids.values(), 100000)
    ids = list(user_ids.values())

    # a couple of extra markets authored by named demo traders
    now = datetime.now(UTC)
    for x in EXTRA_MARKETS:
        q_yes, q_no = opening_q(x["yes"])
        await session.execute(
            text(
                "INSERT INTO markets (slug, ticker, question, category, description, "
                "resolution_rules, closes_at, creator_id, q_yes, q_no, created_at) VALUES "
                "(:slug,:ticker,:q,:cat,:descr,:res,:close,:creator,:qy,:qn, :created) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": x["slug"], "ticker": x["ticker"], "q": x["question"],
                "cat": x["category"], "descr": x["description"], "res": x["resolution"],
                "close": datetime.fromisoformat(f"{x['closes']}T23:59:59+00:00"),
                "creator": user_ids[x["by"]], "qy": q_yes, "qn": q_no,
                "created": now - timedelta(days=9),
            },
        )
        mid = (
            await session.execute(text("SELECT id FROM markets WHERE slug = :s"), {"s": x["slug"]})
        ).scalar()
        if mid:
            await insert_history(session, mid, gen_history(x["slug"], x["yes"]), 30)

    # replay trades on every open market so feeds and holders have named activity;
    # final AMM quantities are written back so prices stay consistent
    markets = (
        await session.execute(text("SELECT id, q_yes, q_no FROM markets WHERE status = 'open' ORDER BY id"))
    ).mappings().all()
    for m in markets:
        q_yes, q_no = m["q_yes"], m["q_no"]
        holdings: dict[tuple[int, str], float] = {}
        drift = 0.0
        n_trades = 2 + rand.randrange(4)

        for _ in range(n_trades):
            uid = ids[rand.randrange(len(ids))]
            side = "no" if drift > 30 else "yes" if drift < -30 else ("yes" if rand.random() < 0.55 else "no")
            held = holdings.get((uid, side), 0.0)
            hours_ago = 2 + rand.random() * 70
            at = now - timedelta(hours=hours_ago)

            if held > 5 and rand.random() < 0.35:
                shares = round(held * (0.3 + rand.random() * 0.5), 2)
                proceeds = float(proceeds_for_shares(q_yes, q_no, side, shares))
                amount_cents = max(1, round(proceeds * 100))
                q_yes -= shares if side == "yes" else 0
                q_no -= shares if side == "no" else 0
                drift -= shares if side == "yes" else -shares
                balances[uid] += amount_cents
                await session.execute(
                    text("INSERT INTO trades (market_id, user_id, side, action, shares, "
                         "price_cents, amount_cents, created_at) "
                         "VALUES (:m,:u,:s,'sell',:sh,:p,:amt,:at)"),
                    {"m": m["id"], "u": uid, "s": side, "sh": shares,
                     "p": round(amount_cents / shares), "amt": amount_cents, "at": at},
                )
                await session.execute(
                    text("UPDATE positions SET shares = GREATEST(positions.shares - :sh, 0) "
                         "WHERE user_id = :u AND market_id = :m AND side = :s"),
                    {"u": uid, "m": m["id"], "sh": shares, "s": side},
                )
                holdings[(uid, side)] = held - shares
            else:
                amount_cents = round(5 + rand.random() * 30) * 100
                if balances[uid] < amount_cents:
                    continue
                shares = float(shares_for_dollars(q_yes, q_no, side, amount_cents / 100))
                if shares < 1:
                    continue
                q_yes += shares if side == "yes" else 0
                q_no += shares if side == "no" else 0
                drift += shares if side == "yes" else -shares
                balances[uid] -= amount_cents
                await session.execute(
                    text("INSERT INTO trades (market_id, user_id, side, action, shares, "
                         "price_cents, amount_cents, created_at) "
                         "VALUES (:m,:u,:s,'buy',:sh,:p,:amt,:at)"),
                    {"m": m["id"], "u": uid, "s": side, "sh": shares,
                     "p": round(amount_cents / shares), "amt": amount_cents, "at": at},
                )
                await session.execute(
                    text("INSERT INTO positions (user_id, market_id, side, shares, cost_cents) "
                         "VALUES (:u,:m,:s,:sh,:c) ON CONFLICT (user_id, market_id, side) "
                         "DO UPDATE SET shares = positions.shares + :sh, "
                         "cost_cents = positions.cost_cents + :c"),
                    {"u": uid, "m": m["id"], "s": side, "sh": shares, "c": amount_cents},
                )
                holdings[(uid, side)] = held + shares

            await session.execute(
                text("INSERT INTO price_history (market_id, price_cents, created_at) "
                     "VALUES (:m, :p, :at)"),
                {"m": m["id"], "p": round(price_yes(q_yes, q_no) * 100), "at": at},
            )

        await session.execute(
            text("UPDATE markets SET q_yes = :qy, q_no = :qn WHERE id = :id"),
            {"qy": q_yes, "qn": q_no, "id": m["id"]},
        )

    for uid, cents in balances.items():
        await session.execute(
            text("UPDATE users SET balance_cents = :b WHERE id = :id"), {"b": cents, "id": uid}
        )
    print(f"Seeded {len(DEMO_TRADERS)} demo traders with market activity")


async def main() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            count = (await session.execute(text("SELECT COUNT(*) FROM markets"))).scalar_one()
            if count == 0:
                await seed_sample_markets(session)
            await seed_demo_activity(session)
        # import the freshly seeded world into the ledger so reconciliation
        # holds from the first trade (no-op when entries already exist)
        async with session.begin():
            from app.ledger import GENESIS_SQL

            await session.execute(text(GENESIS_SQL))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
