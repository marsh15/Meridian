import express from 'express'
import crypto from 'node:crypto'
import { initDb, pool, marketSlug } from './db.js'
import {
  B,
  priceYes,
  openingQ,
  sharesForDollars,
  proceedsForShares,
} from './amm.js'

const PORT = process.env.PORT ?? 8393
const START_BALANCE_CENTS = 100_000
const COOKIE = 'meridian_session'
const CATEGORIES = [
  'Politics', 'Economics', 'Crypto', 'Tech', 'Science', 'Culture', 'Sports', 'Weather',
]

const app = express()
app.use(express.json())

/* ---------- tiny cookie parse ---------- */
function parseCookies(req) {
  const out = {}
  const raw = req.headers.cookie
  if (!raw) return out
  for (const part of raw.split(';')) {
    const i = part.indexOf('=')
    if (i > -1) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim())
  }
  return out
}

/* ---------- passwords: scrypt ---------- */
function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex')
  const hash = crypto.scryptSync(password, salt, 64).toString('hex')
  return `${salt}:${hash}`
}
function verifyPassword(password, stored) {
  const [salt, hash] = stored.split(':')
  const candidate = crypto.scryptSync(password, salt, 64)
  return crypto.timingSafeEqual(candidate, Buffer.from(hash, 'hex'))
}

/* ---------- session middleware ---------- */
app.use(async (req, _res, next) => {
  const token = parseCookies(req)[COOKIE]
  if (token) {
    const { rows } = await pool.query(
      `SELECT u.id, u.email, u.display_name, u.balance_cents
         FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = $1`,
      [token]
    )
    if (rows[0]) req.user = rows[0]
  }
  next()
})

function requireAuth(req, res, next) {
  if (!req.user) return res.status(401).json({ error: 'Sign in to do that.' })
  next()
}

async function setSession(res, userId) {
  const token = crypto.randomBytes(32).toString('hex')
  await pool.query('INSERT INTO sessions (token, user_id) VALUES ($1, $2)', [token, userId])
  res.setHeader(
    'Set-Cookie',
    `${COOKIE}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${60 * 60 * 24 * 30}`
  )
}

/* ---------- view shaping ---------- */
function marketView(m, extras = {}) {
  const price =
    m.status === 'resolved' ? (m.outcome === 'yes' ? 100 : 0) : Math.round(priceYes(m.q_yes, m.q_no) * 100)
  const change =
    m.price_24h_ago == null ? 0 : price - m.price_24h_ago
  return {
    id: m.slug,
    slug: m.slug,
    ticker: m.ticker,
    question: m.question,
    category: m.category,
    description: m.description,
    resolution: m.resolution_rules,
    closesAt: m.closes_at,
    createdAt: m.created_at,
    price,
    change24h: change,
    status: m.status,
    outcome: m.outcome,
    volumeCents:
      Number(m.seed_volume_cents) + Number(m.trade_volume_cents ?? 0),
    traders: m.seed_traders + Number(m.trade_traders ?? 0),
    creatorName: m.creator_name ?? null,
    ...extras,
  }
}

const MARKET_SELECT = `
  SELECT m.*,
    u.display_name AS creator_name,
    COALESCE((SELECT SUM(amount_cents) FROM trades t WHERE t.market_id = m.id), 0) AS trade_volume_cents,
    (SELECT COUNT(DISTINCT user_id) FROM trades t WHERE t.market_id = m.id) AS trade_traders,
    (SELECT price_cents FROM price_history h
       WHERE h.market_id = m.id AND h.created_at <= now() - interval '24 hours'
       ORDER BY h.created_at DESC, h.id DESC LIMIT 1) AS price_24h_ago
  FROM markets m
  LEFT JOIN users u ON u.id = m.creator_id
`

/* ================= AUTH ================= */

app.post('/api/auth/signup', async (req, res, next) => {
  try {
    const { email, password, displayName } = req.body ?? {}
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))
      return res.status(400).json({ error: 'A valid email is required.' })
    if (!password || password.length < 6)
      return res.status(400).json({ error: 'Password must be at least 6 characters.' })
    const name = (displayName ?? '').trim() || email.split('@')[0]
    if (name.length > 40)
      return res.status(400).json({ error: 'Display name too long (max 40).' })

    const exists = await pool.query('SELECT 1 FROM users WHERE email = $1', [email.toLowerCase()])
    if (exists.rowCount)
      return res.status(409).json({ error: 'That email is already registered.' })

    const { rows } = await pool.query(
      `INSERT INTO users (email, password_hash, display_name)
       VALUES ($1, $2, $3) RETURNING id, email, display_name, balance_cents`,
      [email.toLowerCase(), hashPassword(password), name]
    )
    await setSession(res, rows[0].id)
    res.json({
      user: {
        id: rows[0].id,
        email: rows[0].email,
        displayName: rows[0].display_name,
        balanceCents: Number(rows[0].balance_cents),
      },
    })
  } catch (err) { next(err) }
})

app.post('/api/auth/login', async (req, res, next) => {
  try {
    const { email, password } = req.body ?? {}
    const { rows } = await pool.query('SELECT * FROM users WHERE email = $1', [
      (email ?? '').toLowerCase(),
    ])
    const user = rows[0]
    if (!user || user.is_house || !verifyPassword(password ?? '', user.password_hash))
      return res.status(401).json({ error: 'Wrong email or password.' })
    await setSession(res, user.id)
    res.json({
      user: {
        id: user.id,
        email: user.email,
        displayName: user.display_name,
        balanceCents: Number(user.balance_cents),
      },
    })
  } catch (err) { next(err) }
})

app.post('/api/auth/logout', async (req, res) => {
  const token = parseCookies(req)[COOKIE]
  if (token) await pool.query('DELETE FROM sessions WHERE token = $1', [token])
  res.setHeader('Set-Cookie', `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`)
  res.json({ ok: true })
})

app.get('/api/auth/me', (req, res) => {
  res.json({
    user: req.user
      ? {
          id: req.user.id,
          email: req.user.email,
          displayName: req.user.display_name,
          balanceCents: Number(req.user.balance_cents),
        }
      : null,
  })
})

/* reset: back to $1,000 and no open positions */
app.post('/api/account/reset', requireAuth, async (req, res, next) => {
  try {
    await pool.query(
      `UPDATE users SET balance_cents = $2 WHERE id = $1`,
      [req.user.id, START_BALANCE_CENTS]
    )
    await pool.query(
      `UPDATE positions SET shares = 0, cost_cents = 0 WHERE user_id = $1`,
      [req.user.id]
    )
    const { rows } = await pool.query(
      'SELECT id, email, display_name, balance_cents FROM users WHERE id = $1',
      [req.user.id]
    )
    res.json({ user: { ...rows[0], balanceCents: Number(rows[0].balance_cents) } })
  } catch (err) { next(err) }
})

/* ================= MARKETS ================= */

app.get('/api/markets', async (req, res, next) => {
  try {
    const { rows } = await pool.query(`${MARKET_SELECT} ORDER BY m.created_at DESC`)
    const history = await pool.query(
      `SELECT market_id, price_cents FROM price_history ORDER BY market_id, created_at, id`
    )
    const byMarket = new Map()
    for (const h of history.rows) {
      if (!byMarket.has(h.market_id)) byMarket.set(h.market_id, [])
      byMarket.get(h.market_id).push(h.price_cents)
    }
    res.json({
      markets: rows.map((m) =>
        marketView(m, { history: byMarket.get(m.id) ?? [] })
      ),
    })
  } catch (err) { next(err) }
})

app.post('/api/markets', requireAuth, async (req, res, next) => {
  try {
    const { question, category, closesAt, description, resolution, initialYes } = req.body ?? {}
    const q = (question ?? '').trim()
    if (q.length < 10 || q.length > 240)
      return res.status(400).json({ error: 'Question must be 10–240 characters.' })
    const cat = (category ?? '').trim()
    if (!cat || cat.length > 40)
      return res.status(400).json({ error: 'Category is required.' })
    if (!/^\d{4}-\d{2}-\d{2}$/.test(closesAt ?? ''))
      return res.status(400).json({ error: 'A valid close date is required.' })
    const close = new Date(`${closesAt}T23:59:59Z`)
    if (Number.isNaN(close.getTime()) || close.getTime() < Date.now())
      return res.status(400).json({ error: 'Close date must be in the future.' })
    const p = Number(initialYes)
    if (!Number.isInteger(p) || p < 5 || p > 95)
      return res.status(400).json({ error: 'Opening YES price must be 5–95¢.' })

    const slug = marketSlug(q)
    const ticker =
      cat.slice(0, 4).toUpperCase().replace(/[^A-Z]/g, '') +
      '.' +
      slug.slice(-4).toUpperCase().replace(/[^A-Z0-9]/g, '') || 'MKT'
    const { qYes, qNo } = openingQ(p)

    const { rows } = await pool.query(
      `INSERT INTO markets
         (slug, ticker, question, category, description, resolution_rules,
          closes_at, creator_id, q_yes, q_no)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *`,
      [slug, ticker, q, cat, (description ?? '').trim(), (resolution ?? '').trim(),
       close.toISOString(), req.user.id, qYes, qNo]
    )
    const m = rows[0]
    await pool.query(
      'INSERT INTO price_history (market_id, price_cents) VALUES ($1, $2)',
      [m.id, p]
    )
    res.json({
      market: marketView({ ...m, creator_name: req.user.display_name, trade_volume_cents: 0, trade_traders: 0, price_24h_ago: null }),
    })
  } catch (err) { next(err) }
})

async function loadMarket(slug) {
  const { rows } = await pool.query(`${MARKET_SELECT} WHERE m.slug = $1`, [slug])
  return rows[0] ?? null
}

app.get('/api/markets/:slug', async (req, res, next) => {
  try {
    const m = await loadMarket(req.params.slug)
    if (!m) return res.status(404).json({ error: 'Market not found.' })

    const history = await pool.query(
      `SELECT price_cents, created_at FROM price_history
        WHERE market_id = $1 ORDER BY created_at, id`,
      [m.id]
    )
    const trades = await pool.query(
      `SELECT t.*, u.display_name FROM trades t
         JOIN users u ON u.id = t.user_id
        WHERE t.market_id = $1 ORDER BY t.created_at DESC, t.id DESC LIMIT 25`,
      [m.id]
    )
    const holders = await pool.query(
      `SELECT p.side, p.shares, u.display_name FROM positions p
         JOIN users u ON u.id = p.user_id
        WHERE p.market_id = $1 AND p.shares > 0.004
        ORDER BY p.shares DESC LIMIT 6`,
      [m.id]
    )

    let position = null
    if (req.user) {
      const pos = await pool.query(
        `SELECT side, shares, cost_cents FROM positions
          WHERE market_id = $1 AND user_id = $2`,
        [m.id, req.user.id]
      )
      position = {
        yes: { shares: 0, costCents: 0 },
        no: { shares: 0, costCents: 0 },
      }
      for (const r of pos.rows) {
        position[r.side] = { shares: r.shares, costCents: Number(r.cost_cents) }
      }
    }

    res.json({
      market: marketView(m, {
        history: history.rows.map((h) => ({ price: h.price_cents, at: h.created_at })),
        trades: trades.rows.map((t) => ({
          id: t.id,
          trader: t.display_name,
          side: t.side,
          action: t.action,
          shares: Number(t.shares.toFixed(2)),
          priceCents: t.price_cents,
          amountCents: Number(t.amount_cents),
          at: t.created_at,
        })),
        holders: holders.rows.map((h) => ({
          trader: h.display_name,
          side: h.side,
          shares: Number(h.shares.toFixed(1)),
        })),
        yourPosition: position,
        isCreator: req.user ? m.creator_id === req.user.id : false,
        q: { yes: m.q_yes, no: m.q_no },
        depth: B,
      }),
    })
  } catch (err) { next(err) }
})

/* ================= ORDERS (instant AMM fills) ================= */

app.post('/api/markets/:slug/orders', requireAuth, async (req, res, next) => {
  const client = await pool.connect()
  try {
    const { side, action, dollarsCents, shares } = req.body ?? {}
    if (!['yes', 'no'].includes(side))
      return res.status(400).json({ error: 'Side must be yes or no.' })

    await client.query('BEGIN')

    const m = (
      await client.query('SELECT * FROM markets WHERE slug = $1 FOR UPDATE', [req.params.slug])
    ).rows[0]
    if (!m) throw Object.assign(new Error('Market not found.'), { status: 404 })
    if (m.status !== 'open')
      return res.status(400).json({ error: `This market resolved ${m.outcome}. No more trading.` })
    if (new Date(m.closes_at).getTime() < Date.now())
      return res.status(400).json({ error: 'This market has closed. Awaiting resolution.' })

    const user = (
      await client.query('SELECT * FROM users WHERE id = $1 FOR UPDATE', [req.user.id])
    ).rows[0]
    const balance = Number(user.balance_cents)

    let amountCents, fillShares, fillPriceCents

    if (action === 'buy') {
      amountCents = Math.round(Number(dollarsCents))
      if (!Number.isFinite(amountCents) || amountCents < 100)
        return res.status(400).json({ error: 'Minimum order is $1.' })
      if (amountCents > balance)
        return res.status(400).json({ error: 'Insufficient balance.' })

      fillShares = sharesForDollars(m.q_yes, m.q_no, side, amountCents / 100)
      if (fillShares < 0.01)
        return res.status(400).json({ error: 'Order too small to fill at this price.' })
      fillPriceCents = Math.round(amountCents / fillShares)

      await client.query(
        'UPDATE users SET balance_cents = balance_cents - $2 WHERE id = $1',
        [user.id, amountCents]
      )
      await client.query(
        `INSERT INTO positions (user_id, market_id, side, shares, cost_cents)
         VALUES ($1,$2,$3,$4,$5)
         ON CONFLICT (user_id, market_id, side)
         DO UPDATE SET shares = positions.shares + $4, cost_cents = positions.cost_cents + $5`,
        [user.id, m.id, side, fillShares, amountCents]
      )
      await client.query(
        side === 'yes'
          ? 'UPDATE markets SET q_yes = q_yes + $2 WHERE id = $1'
          : 'UPDATE markets SET q_no = q_no + $2 WHERE id = $1',
        [m.id, fillShares]
      )
    } else if (action === 'sell') {
      const pos = (
        await client.query(
          `SELECT * FROM positions WHERE market_id = $1 AND user_id = $2 AND side = $3 FOR UPDATE`,
          [m.id, user.id, side]
        )
      ).rows[0]
      const sellShares = Number(shares)
      if (!pos || sellShares <= 0 || sellShares > pos.shares + 1e-9)
        return res.status(400).json({ error: 'You do not have that many shares.' })
      const clamped = Math.min(sellShares, pos.shares)

      const proceeds = proceedsForShares(m.q_yes, m.q_no, side, clamped)
      amountCents = Math.max(1, Math.round(proceeds * 100))
      fillShares = clamped
      fillPriceCents = Math.round(amountCents / clamped)

      const keptRatio = 1 - clamped / pos.shares
      await client.query(
        'UPDATE users SET balance_cents = balance_cents + $2 WHERE id = $1',
        [user.id, amountCents]
      )
      await client.query(
        `UPDATE positions SET shares = shares - $2,
            cost_cents = ROUND(cost_cents * $3::numeric)
          WHERE id = $1`,
        [pos.id, clamped, keptRatio]
      )
      await client.query(
        side === 'yes'
          ? 'UPDATE markets SET q_yes = q_yes - $2 WHERE id = $1'
          : 'UPDATE markets SET q_no = q_no - $2 WHERE id = $1',
        [m.id, clamped]
      )
    } else {
      return res.status(400).json({ error: 'Action must be buy or sell.' })
    }

    await client.query(
      `INSERT INTO trades (market_id, user_id, side, action, shares, price_cents, amount_cents)
       VALUES ($1,$2,$3,$4,$5,$6,$7)`,
      [m.id, user.id, side, action, fillShares, fillPriceCents, amountCents]
    )
    const after = (
      await client.query('SELECT q_yes, q_no FROM markets WHERE id = $1', [m.id])
    ).rows[0]
    await client.query(
      'INSERT INTO price_history (market_id, price_cents) VALUES ($1, $2)',
      [m.id, Math.round(priceYes(after.q_yes, after.q_no) * 100)]
    )

    await client.query('COMMIT')

    const fresh = await loadMarket(req.params.slug)
    const { rows: bal } = await pool.query(
      'SELECT balance_cents FROM users WHERE id = $1', [user.id]
    )
    const pos = await pool.query(
      `SELECT side, shares, cost_cents FROM positions WHERE market_id = $1 AND user_id = $2`,
      [m.id, user.id]
    )
    const position = { yes: { shares: 0, costCents: 0 }, no: { shares: 0, costCents: 0 } }
    for (const r of pos.rows)
      position[r.side] = { shares: r.shares, costCents: Number(r.cost_cents) }

    res.json({
      fill: {
        side, action,
        shares: Number(fillShares.toFixed(2)),
        priceCents: fillPriceCents,
        amountCents,
      },
      market: marketView(fresh),
      position,
      balanceCents: Number(bal[0].balance_cents),
    })
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {})
    next(err)
  } finally {
    client.release()
  }
})

/* ================= RESOLUTION ================= */

app.post('/api/markets/:slug/resolve', requireAuth, async (req, res, next) => {
  const client = await pool.connect()
  try {
    const { outcome } = req.body ?? {}
    if (!['yes', 'no'].includes(outcome))
      return res.status(400).json({ error: 'Outcome must be yes or no.' })

    await client.query('BEGIN')
    const m = (
      await client.query('SELECT * FROM markets WHERE slug = $1 FOR UPDATE', [req.params.slug])
    ).rows[0]
    if (!m) throw Object.assign(new Error('Market not found.'), { status: 404 })
    if (m.creator_id !== req.user.id)
      return res.status(403).json({ error: 'Only the market creator can resolve.' })
    if (m.status !== 'open')
      return res.status(400).json({ error: 'Market is already resolved.' })

    await client.query(
      `UPDATE markets SET status = 'resolved', outcome = $2 WHERE id = $1`,
      [m.id, outcome]
    )
    await client.query(
      'INSERT INTO price_history (market_id, price_cents) VALUES ($1, $2)',
      [m.id, outcome === 'yes' ? 100 : 0]
    )

    const winners = await client.query(
      `SELECT * FROM positions WHERE market_id = $1 AND side = $2 AND shares > 0`,
      [m.id, outcome]
    )
    for (const p of winners.rows) {
      const payout = Math.round(p.shares * 100)
      await client.query(
        'UPDATE users SET balance_cents = balance_cents + $2 WHERE id = $1',
        [p.user_id, payout]
      )
    }
    // winning shares became cash, losing shares expired — clear the book
    await client.query(
      `UPDATE positions SET shares = 0, cost_cents = 0 WHERE market_id = $1`, [m.id]
    )

    await client.query('COMMIT')

    const fresh = await loadMarket(req.params.slug)
    res.json({ market: marketView(fresh) })
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {})
    next(err)
  } finally {
    client.release()
  }
})

app.get('/api/categories', (_req, res) => res.json({ categories: CATEGORIES }))

app.get('/api/health', async (_req, res) => {
  try {
    await pool.query('SELECT 1')
    res.json({ ok: true })
  } catch {
    res.status(500).json({ ok: false })
  }
})

app.use((err, _req, res, _next) => {
  console.error(err)
  const status = err.status ?? 500
  res.status(status).json({ error: status === 500 ? 'Something went wrong.' : err.message })
})

initDb()
  .then(() => {
    app.listen(PORT, () => console.log(`Meridian API on http://localhost:${PORT}`))
  })
  .catch((err) => {
    console.error('Failed to init database:', err)
    process.exit(1)
  })
