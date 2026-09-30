# Glossary — Meridian

The shared language of the prediction market. No implementation details.

- **Market** — A yes/no question about a future event that traders can trade shares in. Opens at a creator-chosen price and trades until resolved.
- **Trader** — A person with an Account who buys and sells Shares in Markets.
- **Account** — An email + password identity that holds a Balance and Positions.
- **Balance** — A trader's virtual dollars. Starts at $1,000. Buys debit it; sells and settlements credit it. Resettable.
- **Share** — A claim that pays $1 if its side of the Market wins. One side is YES, the other NO; a YES share and a NO share together are always worth exactly $1 at resolution.
- **Position** — A trader's holding of YES or NO Shares in a Market, tracked with average cost.
- **Market order** — An instruction to buy or sell Shares right now at the current market price. No resting orders.
- **Fill** — An executed market order: side (YES/NO), buy or sell, shares, price, dollar amount, trader, time.
- **Market price** — The current YES price in cents, always between 1¢ and 99¢. Moves with net buying and selling.
- **Creator** — The Trader who opened a Market; responsible for writing its resolution rules and issuing its Resolution.
- **Resolution** — The creator's final ruling that a Market ended YES or NO.
- **Settlement** — What happens at Resolution: each winning Share pays $1 to its holder; losing Shares expire worthless.
- **Demo trader** — A system-seeded Trader with a display name and holdings, but no usable credentials; exists so markets show activity. Always attributed by name, never as an anonymous collective.
