/* The twelve sample markets, seeded into Postgres on first boot.
 * Seeded volume/trader numbers display alongside real activity. */

function hashSeed(str) {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
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

/* deterministic walk ending exactly at the opening price */
export function genHistory(id, current, n = 48) {
  const rand = mulberry32(hashSeed(id))
  let p = current + (rand() * 44 - 22)
  const pts = []
  for (let i = 0; i < n; i++) {
    p += (rand() - 0.5) * 7 + (current - p) * 0.07
    p = Math.min(97, Math.max(3, p))
    pts.push(p)
  }
  pts[n - 1] = current
  return pts.map((v) => Math.round(v))
}

export const seedMarkets = [
  {
    id: 'fed-cut-nov-2026',
    ticker: 'FED.CUT26',
    question: 'Will the Fed cut rates at the November 2026 meeting?',
    category: 'Economics',
    yes: 68,
    volume: 4820000,
    traders: 11400,
    closes: '2026-11-05',
    description:
      'This market resolves YES if the Federal Open Market Committee lowers the federal funds target rate at its November 2026 meeting. Futures pricing has swung between 55¢ and 75¢ over the past month as CPI prints and labor data alternately embolden and restrain the doves.',
    resolution:
      'Resolves YES if the FOMC statement released after the November 3–4, 2026 meeting announces a lower target range for the federal funds rate.',
  },
  {
    id: 'democrat-wins-2028',
    ticker: 'POTUS.28D',
    question: 'Will a Democrat win the 2028 US presidential election?',
    category: 'Politics',
    yes: 54,
    volume: 12750000,
    traders: 41200,
    closes: '2028-11-07',
    description:
      'Resolves YES if the Democratic nominee wins a majority of the electoral college in the 2028 US presidential election, as certified by Congress. Early trading typically tracks generic-ballot polling and incumbent-party fatigue measures.',
    resolution:
      'Resolves per the certification of the 2028 electoral college results by a joint session of Congress.',
  },
  {
    id: 'btc-150k-2026',
    ticker: 'BTC.150K',
    question: 'Will Bitcoin close above $150,000 on Dec 31, 2026?',
    category: 'Crypto',
    yes: 32,
    volume: 8930000,
    traders: 26800,
    closes: '2026-12-31',
    description:
      'Resolves YES if the BTC/USD price on Coinbase closes at or above $150,000 at 23:59:59 UTC on December 31, 2026. The market peaked at 71¢ after the spring halving rally before fading alongside risk-off macro sentiment.',
    resolution:
      'Resolves using the 1-day candle close on Coinbase for December 31, 2026, in UTC.',
  },
  {
    id: 'spx-7500-2026',
    ticker: 'SPX.7500',
    question: 'Will the S&P 500 finish 2026 above 7,500?',
    category: 'Economics',
    yes: 46,
    volume: 5640000,
    traders: 18700,
    closes: '2026-12-31',
    description:
      'Resolves YES if the S&P 500 index closes above 7,500 on the final trading day of 2026. Earnings breadth has been strong, but multiple expansion is stretched by historical standards — traders are split almost down the middle.',
    resolution:
      'Resolves to the official closing print of the S&P 500 on the last NYSE trading day of 2026.',
  },
  {
    id: 'apple-ar-headset',
    ticker: 'AAPL.AR',
    question: 'Will Apple announce a new AR headset in 2026?',
    category: 'Tech',
    yes: 41,
    volume: 2210000,
    traders: 9400,
    closes: '2026-12-31',
    description:
      'Resolves YES if Apple formally announces a new augmented-reality headset (or major successor to Vision Pro) at any point during calendar year 2026. Leaked CAD drawings and display orders have kept this market lively despite no official word.',
    resolution:
      'Resolves YES upon an Apple press release or keynote announcement of a new AR headset product.',
  },
  {
    id: 'starship-mars-2026',
    ticker: 'STSHIP.MRS',
    question: 'Will SpaceX Starship depart for Mars in 2026?',
    category: 'Science',
    yes: 12,
    volume: 1310000,
    traders: 7100,
    closes: '2026-12-31',
    description:
      'Resolves YES if a Starship vehicle departs Earth orbit on a Mars transfer trajectory before the end of 2026. The Hohmann transfer window opens in October, but unfueled-dep skepticism keeps this market cheap.',
    resolution:
      'Resolves YES if SpaceX confirms a trans-Mars injection burn of a Starship vehicle in 2026.',
  },
  {
    id: 'ai-film-oscar-2030',
    ticker: 'AI.OSCAR30',
    question: 'Will an AI-generated film win an Oscar by 2030?',
    category: 'Culture',
    yes: 24,
    volume: 980000,
    traders: 5900,
    closes: '2030-03-31',
    description:
      'Resolves YES if a film that uses AI-generated video for a majority of its runtime wins any Academy Award in a competitive category before the March 2030 ceremony. Current Academy rules require disclosed human authorship for eligibility in some categories.',
    resolution:
      'Resolves YES per the Academy of Motion Picture Arts and Sciences official winners list.',
  },
  {
    id: 'swift-tour-2027',
    ticker: 'TSWIFT.27',
    question: 'Will Taylor Swift announce a 2027 world tour?',
    category: 'Culture',
    yes: 58,
    volume: 1740000,
    traders: 9900,
    closes: '2027-06-30',
    description:
      'Resolves YES if Taylor Swift or her label officially announces a concert tour with dates in 2027. Historically, tour announcements follow roughly 4–8 months after a major album release cycle.',
    resolution:
      'Resolves YES on an official artist or label announcement of a tour including 2027 dates.',
  },
  {
    id: 'nyc-90-christmas',
    ticker: 'NYC.XMAS90',
    question: 'Will NYC hit 90°F on Christmas Day 2026?',
    category: 'Weather',
    yes: 4,
    volume: 340000,
    traders: 3300,
    closes: '2026-12-25',
    description:
      'Resolves YES if the National Weather Service records a temperature of 90°F or higher in Central Park on December 25, 2026. The all-time record for that date is 64°F, set in 1964 — hence the deep longshot pricing.',
    resolution:
      'Resolves to the NWS Central Park daily high for December 25, 2026.',
  },
  {
    id: 'eth-flips-btc',
    ticker: 'ETH.FLIP',
    question: 'Will Ethereum flip Bitcoin market cap by 2028?',
    category: 'Crypto',
    yes: 8,
    volume: 1120000,
    traders: 6100,
    closes: '2028-12-31',
    description:
      'Resolves YES if Ethereum market capitalization exceeds Bitcoin market capitalization on any day before January 1, 2029, per CoinGecko aggregated data. ETH last closed the gap to under 40% of BTC cap in 2021.',
    resolution:
      'Resolves YES if ETH market cap exceeds BTC market cap at any daily close before 2029.',
  },
  {
    id: 'artemis-moon-2027',
    ticker: 'ARTEMIS.MN',
    question: 'Will astronauts land on the Moon before 2028?',
    category: 'Science',
    yes: 61,
    volume: 2010000,
    traders: 8800,
    closes: '2027-12-31',
    description:
      'Resolves YES if a crewed spacecraft touches down on the lunar surface with living astronauts aboard before January 1, 2028. No human has walked on the Moon since Apollo 17 in December 1972.',
    resolution:
      'Resolves YES upon confirmed crewed lunar surface landing per NASA or the operating agency.',
  },
  {
    id: 'chiefs-sb-lxi',
    ticker: 'KC.SB61',
    question: 'Will the Chiefs reach Super Bowl LXI?',
    category: 'Sports',
    yes: 37,
    volume: 3320000,
    traders: 22400,
    closes: '2027-02-14',
    description:
      'Resolves YES if the Kansas City Chiefs play in Super Bowl LXI in February 2027. Dynasty pricing is getting expensive against a deeper field of AFC contenders than at any point in the Mahomes era.',
    resolution: 'Resolves YES if the Chiefs appear in Super Bowl LXI, per the NFL.',
  },
]
