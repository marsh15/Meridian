# ADR 0005: Exact money: integer cents + NUMERIC shares

## Status

Accepted (2026-09-30)

## Context

Balances were already stored as BIGINT cents (correct). Shares,
positions, and LMSR quantities (q_yes, q_no) were `DOUBLE PRECISION`.
LMSR prices are irrational, so no representation is exact. But float
equality and accumulation errors in a system that debits money are the
kind of defect reviewers spot and the kind that compounds silently.

## Decision

- Balances, costs, amounts: BIGINT cents (unchanged).
- Shares, positions, q_yes/q_no, trades.shares: `NUMERIC(24,10)`,
  materialized as Python `Decimal`.
- The LMSR engine computes in floats internally (exp/log); the math is
  smooth and the errors are bounded, but every value crossing the DB
  boundary is quantized to 10 decimal places.
- One deliberate rounding point per fill: dollar amounts are rounded to
  whole cents at fill time; share quantities are truncated to 10 dp.

## Consequences

- Sells can compare share quantities exactly (the old `+1e-9` epsilon
  disappears).
- A future double-entry ledger can consume the same NUMERIC columns.
- Migration 0002 converts the existing volume in place (double →
  numeric casts losslessly at this precision).
