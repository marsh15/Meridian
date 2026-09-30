# ADR 0001: Instant AMM fills over a limit order book

## Status

Accepted (2026-09-30)

## Context

Meridian needs a mechanism for turning trader intent into fills. The two
reference products differ: Kalshi matches resting limit orders on a book;
Polymarket historically used an automated market maker for liquidity. We are
building a demo exchange with virtual money, a small team, and a want for
every click to produce immediate, visible feedback — price movement, fills,
positions.

A limit order book requires: resting order storage, a matching engine, partial
fills, best-bid/best-ask maintenance, and UI for choosing prices. That is the
majority of the complexity of a real exchange, and most of it is invisible
until two traders happen to cross.

## Decision

Every market order fills instantly against an LMSR (logarithmic market scoring
rule) automated market maker with liquidity parameter B = 250. Each market row
stores net outstanding quantities (q_yes, q_no); price is derived
(sigmoid of the difference), so no price column can drift out of sync. Buys
solve for shares at exact dollar cost; sells redeem shares for the marginal
value. The market maker is the counterparty to everyone, subsidized by the
house — acceptable because all money is virtual.

## Consequences

- Any single visitor gets a complete trading experience with no counterparties.
- Price impact is smooth, monotonic, and bounded away from 0¢/100¢ by
  construction — no circuit breakers needed.
- No resting orders, no book UI; the detail page shows recent trades and top
  holders instead of an order book.
- LMSR subsidization means the house can show a "loss" on net flows; this is
  meaningless in play money but would need redesign for real stakes.
- If we later need true Kalshi-style limit orders, the positions and trades
  tables carry over unchanged; only execution logic and q columns are AMM-
  specific.
