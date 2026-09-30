import pg from 'pg'
import crypto from 'node:crypto'
import { openingQ, sharesForDollars, proceedsForShares, priceYes } from './amm.js'
import { genHistory, seedMarkets } from './seed-data.js'

const DATABASE_URL =
  process.env.DATABASE_URL ??
  'postgres://meridian:meridian@localhost:5434/meridian'

export const pool = new pg.Pool({ connectionString: DATABASE_URL })

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id            SERIAL PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL,
  balance_cents BIGINT NOT NULL DEFAULT 100000,
  is_house      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS markets (
  id                 SERIAL PRIMARY KEY,
  slug               TEXT NOT NULL UNIQUE,
  ticker             TEXT NOT NULL,
  question           TEXT NOT NULL,
  category           TEXT NOT NULL,
  description        TEXT NOT NULL DEFAULT '',
  resolution_rules   TEXT NOT NULL DEFAULT '',
  closes_at          TIMESTAMPTZ NOT NULL,
  creator_id         INT REFERENCES users(id),
  q_yes              DOUBLE PRECISION NOT NULL,
  q_no               DOUBLE PRECISION NOT NULL,
  status             TEXT NOT NULL DEFAULT 'open',
  outcome            TEXT,
  seed_volume_cents  BIGINT NOT NULL DEFAULT 0,
  seed_traders       INT NOT NULL DEFAULT 0,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (
  id         SERIAL PRIMARY KEY,
  user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  market_id  INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  side       TEXT NOT NULL CHECK (side IN ('yes','no')),
  shares     DOUBLE PRECISION NOT NULL DEFAULT 0,
  cost_cents BIGINT NOT NULL DEFAULT 0,
  UNIQUE (user_id, market_id, side)
);

CREATE TABLE IF NOT EXISTS trades (
  id           SERIAL PRIMARY KEY,
  market_id    INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  side         TEXT NOT NULL CHECK (side IN ('yes','no')),
  action       TEXT NOT NULL CHECK (action IN ('buy','sell')),
  shares       DOUBLE PRECISION NOT NULL,
  price_cents  INT NOT NULL,
  amount_cents BIGINT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS price_history (
  id          SERIAL PRIMARY KEY,
  market_id   INT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  price_cents INT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_history_market ON price_history (market_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades (market_id, created_at);
CREATE INDEX IF NOT EXISTS idx_positions_market ON positions (market_id);
`

function slugify(s) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
}

export function marketSlug(question) {
  const base = slugify(question) || 'market'
  const suffix = Math.random().toString(36).slice(2, 6)
  return `${base}-${suffix}`
}

/* ---------- demo activity seed ---------- */

const DEMO_TRADERS = [
  ['Maya Chen', 'maya.chen'],
  ['Dele Okafor', 'dele.okafor'],
  ['Priya Nair', 'priya.nair'],
  ['Tomás Rivera', 'tomas.rivera'],
  ['June Park', 'june.park'],
  ['Marcus Webb', 'marcus.webb'],
  ['Aisha Diallo', 'aisha.diallo'],
  ['Felix Grant', 'felix.grant'],
  ['Nadia Kovač', 'nadia.kovac'],
  ['Ellis Moore', 'ellis.moore'],
  ['Ruth Abrams', 'ruth.abrams'],
  ['Kenji Sato', 'kenji.sato'],
]

const EXTRA_MARKETS = [
  {
    slug: 'openai-gpt6-july-2027',
    ticker: 'OAI.GPT6',
    question: 'Will OpenAI ship a GPT-6 model before July 2027?',
    category: 'Tech',
    yes: 44,
    closes: '2027-06-30',
    by: 'Maya Chen',
    description:
      'Resolves YES if OpenAI publicly releases a model branded GPT-6 (or equivalent flagship successor) before July 1, 2027. Release cadence assumptions are the main swing factor — the crowd has bounced between 35¢ and 55¢ since opening.',
    resolution:
      'Resolves YES upon public availability of a GPT-6-branded model per OpenAI announcements.',
  },
  {
    slug: 'knicks-ecf-2027',
    ticker: 'NYK.ECF27',
    question: 'Will the Knicks reach the 2027 Eastern Conference Finals?',
    category: 'Sports',
    yes: 29,
    closes: '2027-06-15',
    by: 'Marcus Webb',
    description:
      'Resolves YES if the New York Knicks appear in the 2027 Eastern Conference Finals. Health-adjusted depth models put them firmly in the contender mix, but the East is brutal at the top.',
    resolution: 'Resolves YES if the Knicks play in the 2027 ECF, per the NBA.',
  },
]

async function seedDemoActivity() {
  const marker = await pool.query(
    `SELECT 1 FROM users WHERE email = 'maya.chen@demo.meridian'`
  )
  if (marker.rowCount) return

  const rand = mulberry32(0x5eedfeed)

  // demo traders: named accounts, unusable credentials, login blocked via is_house
  const users = {}
  for (const [name, slug] of DEMO_TRADERS) {
    const hash = `${crypto.randomBytes(16).toString('hex')}:${crypto.randomBytes(32).toString('hex')}`
    const { rows } = await pool.query(
      `INSERT INTO users (email, password_hash, display_name, is_house)
       VALUES ($1, $2, $3, true) RETURNING id`,
      [`${slug}@demo.meridian`, hash, name]
    )
    users[name] = rows[0].id
  }
  const balances = Object.fromEntries(
    Object.entries(users).map(([name, id]) => [id, 100_000])
  )

  // a couple of extra markets authored by named demo traders
  const createdSlugs = new Set()
  for (const x of EXTRA_MARKETS) {
    const { qYes, qNo } = openingQ(x.yes)
    await pool.query(
      `INSERT INTO markets
         (slug, ticker, question, category, description, resolution_rules,
          closes_at, creator_id, q_yes, q_no, created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now() - interval '9 days')
       ON CONFLICT (slug) DO NOTHING`,
      [x.slug, x.ticker, x.question, x.category, x.description, x.resolution,
       `${x.closes} 23:59:59Z`, users[x.by], qYes, qNo]
    )
    createdSlugs.add(x.slug)
    const { rows } = await pool.query(`SELECT id FROM markets WHERE slug = $1`, [x.slug])
    if (rows[0]) await insertHistory(rows[0].id, genHistory(x.slug, x.yes), 30)
  }

  // replay trades on every open market so feeds and holders have named activity;
  // final AMM quantities are written back so prices stay consistent
  const { rows: markets } = await pool.query(
    `SELECT id, slug, q_yes, q_no FROM markets WHERE status = 'open' ORDER BY id`
  )
  for (const m of markets) {
    let qYes = m.q_yes
    let qNo = m.q_no
    const holdings = new Map() // `${userId}:${side}` -> shares
    let drift = 0 // net YES-ward share flow; kept small so curated anchors hold
    const nTrades = 2 + Math.floor(rand() * 4)

    for (let i = 0; i < nTrades; i++) {
      const userId = Object.values(users)[Math.floor(rand() * DEMO_TRADERS.length)]
      const side =
        drift > 30 ? 'no' : drift < -30 ? 'yes' : rand() < 0.55 ? 'yes' : 'no'
      const hkey = `${userId}:${side}`
      const held = holdings.get(hkey) ?? 0
      const hoursAgo = (2 + rand() * 70).toFixed(2)

      if (held > 5 && rand() < 0.35) {
        // sell a slice of an earlier buy
        const shares = Number((held * (0.3 + rand() * 0.5)).toFixed(2))
        const proceeds = proceedsForShares(qYes, qNo, side, shares)
        const amountCents = Math.max(1, Math.round(proceeds * 100))
        qYes -= side === 'yes' ? shares : 0
        qNo -= side === 'no' ? shares : 0
        drift -= side === 'yes' ? shares : -shares
        balances[userId] += amountCents

        await pool.query(
          `INSERT INTO trades (market_id, user_id, side, action, shares, price_cents, amount_cents, created_at)
           VALUES ($1,$2,$3,'sell',$4,$5,$6, now() - ($7 || ' hours')::interval)`,
          [m.id, userId, side, shares, Math.round(amountCents / shares), amountCents, hoursAgo]
        )
        await pool.query(
          `UPDATE positions SET shares = GREATEST(positions.shares - $3, 0) WHERE user_id = $1 AND market_id = $2 AND side = $4`,
          [userId, m.id, shares, side]
        )
        holdings.set(hkey, held - shares)
      } else {
        // buy if the demo balance covers it — modest sizes, like retail orders
        const amountCents = Math.round(5 + rand() * 30) * 100
        if (balances[userId] < amountCents) continue
        const shares = sharesForDollars(qYes, qNo, side, amountCents / 100)
        if (shares < 1) continue
        qYes += side === 'yes' ? shares : 0
        qNo += side === 'no' ? shares : 0
        drift += side === 'yes' ? shares : -shares
        balances[userId] -= amountCents

        await pool.query(
          `INSERT INTO trades (market_id, user_id, side, action, shares, price_cents, amount_cents, created_at)
           VALUES ($1,$2,$3,'buy',$4,$5,$6, now() - ($7 || ' hours')::interval)`,
          [m.id, userId, side, shares, Math.round(amountCents / shares), amountCents, hoursAgo]
        )
        await pool.query(
          `INSERT INTO positions (user_id, market_id, side, shares, cost_cents)
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (user_id, market_id, side)
           DO UPDATE SET shares = positions.shares + $4, cost_cents = positions.cost_cents + $5`,
          [userId, m.id, side, shares, amountCents]
        )
        holdings.set(hkey, held + shares)
      }

      await pool.query(
        `INSERT INTO price_history (market_id, price_cents, created_at)
         VALUES ($1, $2, now() - ($3 || ' hours')::interval)`,
        [m.id, Math.round(priceYes(qYes, qNo) * 100), hoursAgo]
      )
    }

    await pool.query(`UPDATE markets SET q_yes = $2, q_no = $3 WHERE id = $1`, [
      m.id, qYes, qNo,
    ])
  }

  // keep demo balances in sync with the replay
  for (const [id, cents] of Object.entries(balances)) {
    await pool.query(`UPDATE users SET balance_cents = $2 WHERE id = $1`, [id, cents])
  }

  console.log(`Seeded ${DEMO_TRADERS.length} demo traders with market activity`)
}

function mulberry32(a) {
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* spread a generated walk across the last `daysSpan` days of history */
async function insertHistory(marketId, history, daysSpan) {
  const values = []
  const params = []
  history.forEach((p, i) => {
    const daysAgo = daysSpan - (daysSpan / (history.length - 1)) * i
    values.push(`($${params.length + 1}, $${params.length + 2}, now() - ($${params.length + 3} || ' days')::interval)`)
    params.push(marketId, p, daysAgo.toFixed(3))
  })
  await pool.query(
    `INSERT INTO price_history (market_id, price_cents, created_at) VALUES ${values.join(',')}`,
    params
  )
}

export async function initDb() {
  await pool.query(SCHEMA)

  const { rows } = await pool.query('SELECT COUNT(*)::int AS n FROM markets')
  if (rows[0].n === 0) await seedSampleMarkets()
  await seedDemoActivity()
}

async function seedSampleMarkets() {

  // house account authors the seeded sample markets
  const house = await pool.query(
    `INSERT INTO users (email, password_hash, display_name, is_house)
     VALUES ('house@meridian.demo', 'x', 'Meridian', true)
     ON CONFLICT (email) DO UPDATE SET display_name = 'Meridian'
     RETURNING id`
  )
  const houseId = house.rows[0].id

  for (const m of seedMarkets) {
    const { qYes, qNo } = openingQ(m.yes)
    const inserted = await pool.query(
      `INSERT INTO markets
         (slug, ticker, question, category, description, resolution_rules,
          closes_at, creator_id, q_yes, q_no, seed_volume_cents, seed_traders, created_at)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now() - interval '30 days')
       RETURNING id`,
      [
        m.id,
        m.ticker,
        m.question,
        m.category,
        m.description,
        m.resolution,
        `${m.closes} 23:59:59Z`,
        houseId,
        qYes,
        qNo,
        m.volume * 100,
        m.traders,
      ]
    )
    const marketId = inserted.rows[0].id

    // seed 30 days of price history ending at the opening price
    await insertHistory(marketId, genHistory(m.id, m.yes), 30)
  }
  console.log(`Seeded ${seedMarkets.length} sample markets`)
}
