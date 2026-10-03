# Meridian glossary

The shared language of the prediction market. No implementation details.

- **Market**: a yes/no question about a future event that traders can trade shares in. Opens at a creator-chosen price and trades until it is resolved.
- **Trader**: a person with an account who buys and sells shares in markets.
- **Account**: an email + password identity that holds a balance and positions.
- **Balance**: a trader's virtual dollars. Starts at $1,000. Buys debit it; sells and settlements credit it. Resettable.
- **Share**: a claim that pays $1 if its side of the market wins. One side is YES, the other NO; a YES share and a NO share together are always worth exactly $1 at resolution.
- **Position**: a trader's holding of YES or NO shares in a market, tracked with average cost.
- **Market order**: an instruction to buy or sell shares right now at the current market price. No resting orders.
- **Fill**: an executed market order: side (YES/NO), buy or sell, shares, price, dollar amount, trader, time.
- **Market price**: the current YES price in cents, always between 1¢ and 99¢. Moves with net buying and selling.
- **Creator**: the trader who opened a market. Writes its resolution rules and issues its resolution.
- **Resolution**: the creator's final ruling that a market ended YES or NO.
- **Settlement**: what happens at resolution. Each winning share pays $1 to its holder; losing shares expire worthless.
- **Demo trader**: a system-seeded trader with a display name and holdings, but no usable credentials; exists so markets show activity. Always attributed by name, never as an anonymous collective.
