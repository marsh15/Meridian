# ADR 0002: The market creator resolves their own market

## Status

Accepted (2026-09-30)

## Context

Every prediction market must eventually answer its own question. The
alternatives considered:

1. Creator resolution: whoever opened the market rules YES or NO.
2. Automated resolution: an oracle or UMA-style dispute process decides.
3. No resolution: markets trade forever.

Automated resolution against real-world sources is the hard 80% of a
production prediction market and cannot be meaningfully demoed locally.
No resolution leaves the product without its payoff moment.

## Decision

The creator of a market may resolve it YES or NO at any time while it is
open (trading also halts at the close date). On resolution, each winning
share pays $1 into its holder's balance, losing shares expire, and all
positions on the market are cleared. The resolution is attributed: the
detail page shows who created the market.

## Consequences

- Trivial to implement and to understand; gives the demo a complete
  create → trade → resolve → settle loop.
- Centralizes trust in one account per market. A malicious or careless
  creator can resolve against reality. Fine for play money; unacceptable
  for real stakes without a dispute window, an oracle, or stake
  slashing.
- Because trading halts at the close date but resolution is manual,
  markets can sit "closed, awaiting resolution", so the UI needs that
  state.
