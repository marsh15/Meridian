/* parity with the python engine (services/api/app/amm.py) via generated
   fixtures — python quantizes shares/proceeds to 10dp, hence the tolerances;
   the invariants below are pure client-side sanity, no server input */

import { describe, expect, it } from "vitest";
import fixtures from "./amm.fixtures.json";
import { priceYes, proceedsForShares, sharesForDollars } from "@/lib/amm";

type Side = "yes" | "no";

const priceCases = fixtures.priceYes as { qYes: number; qNo: number; price: number }[];
const buyCases = fixtures.sharesForDollars as {
  qYes: number; qNo: number; side: Side; dollars: number; shares: number;
}[];
const sellCases = fixtures.proceedsForShares as {
  qYes: number; qNo: number; side: Side; shares: number; proceeds: number;
}[];

/* carry the full case into the failure message, not just the delta */
function near(actual: number, expected: number, tol: number, label: string) {
  expect(
    Math.abs(actual - expected),
    `${label}: got ${actual}, want ${expected}, |diff| > ${tol}`,
  ).toBeLessThanOrEqual(tol);
}

describe("fixture parity with the python engine (B=250)", () => {
  for (const c of priceCases) {
    it(`priceYes(${c.qYes}, ${c.qNo})`, () => {
      near(
        priceYes(c.qYes, c.qNo),
        c.price,
        1e-9,
        `priceYes(qYes=${c.qYes}, qNo=${c.qNo}, input price=${c.price})`,
      );
    });
  }

  for (const c of buyCases) {
    it(`sharesForDollars(${c.qYes}, ${c.qNo}, ${c.side}, $${c.dollars})`, () => {
      near(
        sharesForDollars(c.qYes, c.qNo, c.side, c.dollars),
        c.shares,
        1e-6,
        `sharesForDollars(qYes=${c.qYes}, qNo=${c.qNo}, side=${c.side}, dollars=${c.dollars})`,
      );
    });
  }

  for (const c of sellCases) {
    it(`proceedsForShares(${c.qYes}, ${c.qNo}, ${c.side}, ${c.shares})`, () => {
      near(
        proceedsForShares(c.qYes, c.qNo, c.side, c.shares),
        c.proceeds,
        1e-6,
        `proceedsForShares(qYes=${c.qYes}, qNo=${c.qNo}, side=${c.side}, shares=${c.shares})`,
      );
    });
  }
});

describe("invariants (client-side only)", () => {
  /* keep spreads float64-reachable: |qNo - qYes|/B above ~37 saturates
     priceYes to exactly 0/1 and underflows small proceeds */
  const states: Array<[number, number]> = [
    [0, 0], [100, -50], [-100, 42.7], [500, 500], [800, 0],
  ];
  const sides: Side[] = ["yes", "no"];

  it("priceYes stays strictly inside (0, 1)", () => {
    const qs = [-1200, -250, -100, 0, 1.5, 42.7, 100, 250, 1200];
    for (const qYes of qs) {
      for (const qNo of qs) {
        const p = priceYes(qYes, qNo);
        expect(p, `priceYes(${qYes}, ${qNo}) = ${p}`).toBeGreaterThan(0);
        expect(p, `priceYes(${qYes}, ${qNo}) = ${p}`).toBeLessThan(1);
      }
    }
  });

  it("more dollars buy strictly more shares", () => {
    const dollarSteps = [1, 2, 5, 10, 25, 50, 100, 250, 500];
    for (const [qYes, qNo] of states) {
      for (const side of sides) {
        let prev = 0;
        for (const dollars of dollarSteps) {
          const shares = sharesForDollars(qYes, qNo, side, dollars);
          expect(
            shares,
            `sharesForDollars(qYes=${qYes}, qNo=${qNo}, side=${side}, dollars=${dollars}) = ${shares}, prev = ${prev}`,
          ).toBeGreaterThan(prev);
          prev = shares;
        }
      }
    }
  });

  it("more shares sold return strictly more proceeds", () => {
    const shareSteps = [0.1, 0.5, 1, 5, 10, 50, 100];
    for (const [qYes, qNo] of states) {
      for (const side of sides) {
        let prev = 0;
        for (const shares of shareSteps) {
          const proceeds = proceedsForShares(qYes, qNo, side, shares);
          expect(
            proceeds,
            `proceedsForShares(qYes=${qYes}, qNo=${qNo}, side=${side}, shares=${shares}) = ${proceeds}, prev = ${prev}`,
          ).toBeGreaterThan(prev);
          prev = proceeds;
        }
      }
    }
  });

  it("buying moves the price toward the bought side", () => {
    for (const [qYes, qNo] of states) {
      const p0 = priceYes(qYes, qNo);

      const yesShares = sharesForDollars(qYes, qNo, "yes", 25);
      const pAfterYes = priceYes(qYes + yesShares, qNo);
      expect(
        pAfterYes,
        `after buying $25 of YES (qYes=${qYes}, qNo=${qNo}, shares=${yesShares}): ${p0} -> ${pAfterYes}`,
      ).toBeGreaterThan(p0);

      const noShares = sharesForDollars(qYes, qNo, "no", 25);
      const pAfterNo = priceYes(qYes, qNo + noShares);
      expect(
        pAfterNo,
        `after buying $25 of NO (qYes=${qYes}, qNo=${qNo}, shares=${noShares}): ${p0} -> ${pAfterNo}`,
      ).toBeLessThan(p0);
    }
  });
});
