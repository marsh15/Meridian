import { expect, test } from "@playwright/test";

/**
 * Full happy path through the real UI, one serial flow:
 * signup → create market → buy YES → resolve YES (as creator).
 * Runs against the live stack booted by the Playwright webServer
 * (repo-root `make dev`: Postgres + migrations + seed + API + web).
 */

test.describe.configure({ mode: "serial" });

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("signup, create a market, buy YES, and resolve it as the creator", async ({
  page,
}) => {
  const stamp = Date.now();
  const email = `e2e-${stamp}@example.com`;
  const password = "meridian-e2e"; // >= 6 chars
  const displayName = "E2e Runner";
  const question = `Will the Meridian e2e run from ${stamp} finish green?`;
  // the create form takes YYYY-MM-DD and requires a date after today
  const closesAt = new Date(Date.now() + 90 * 86_400_000)
    .toISOString()
    .slice(0, 10);

  await test.step("sign up with a unique email via the auth modal", async () => {
    await page.goto("/");

    await page
      .getByRole("banner")
      .getByRole("button", { name: "Sign in" })
      .click();

    const authTabs = page.getByRole("group", { name: "Authentication mode" });
    await authTabs.getByRole("button", { name: "Create account" }).click();

    await page.getByLabel("Display name").fill(displayName);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    // the tab button is also named "Create account" — scope to the form
    await page
      .locator("form")
      .getByRole("button", { name: "Create account" })
      .click();

    await expect(
      page.getByRole("banner").getByRole("button", { name: "Sign out" }),
    ).toBeVisible();
    await expect(page.getByTitle("Virtual balance")).toContainText("$1,000.00");
  });

  await test.step("create a market via the create-market modal", async () => {
    await page.getByRole("button", { name: "+ New market" }).click();
    await expect(
      page.getByRole("dialog", { name: "Create a market" }),
    ).toBeVisible();

    await page.getByLabel("Question").fill(question);
    await page.getByLabel("Category").selectOption({ label: "Science" });
    await page.getByLabel("Close date").fill(closesAt);
    await page
      .getByLabel("Description")
      .fill("Created by the Playwright happy-path spec.");
    await page
      .getByLabel("Resolution rules")
      .fill("Resolves YES once this spec passes end to end.");
    await page.getByLabel("Opening YES price").fill("60");

    await page.getByRole("button", { name: "Open this market" }).click();

    // creating routes straight to the market page
    await expect(
      page.getByRole("heading", { level: 1, name: question }),
    ).toBeVisible();
  });

  await test.step("reopen the market from the home grid via its card link", async () => {
    await page.getByRole("link", { name: "All markets" }).click();

    const card = page.getByRole("link", {
      name: new RegExp(escapeRegExp(question)),
    });
    await expect(card).toBeVisible();
    await card.click();

    await expect(
      page.getByRole("heading", { level: 1, name: question }),
    ).toBeVisible();
  });

  await test.step("buy $10 of YES on the market page", async () => {
    await page.getByRole("button", { name: /^Yes \d+¢$/ }).click();
    await page.getByLabel("Trade amount in dollars").fill("10");
    await page
      .getByRole("button", { name: "Buy Yes", exact: true })
      .click();

    // success toast: "Bought <shares> YES @ <price>¢"
    await expect(page.getByRole("status")).toContainText(
      /Bought [\d.]+ YES @ \d+¢/,
    );
    // $1,000 starting balance minus the $10 order
    await expect(page.getByTitle("Virtual balance")).toContainText("$990.00");
    // position card now shows the YES row
    await expect(page.getByText("Your position")).toBeVisible();
    await expect(page.getByText(/^YES$/)).toBeVisible();
  });

  await test.step("resolve the market YES via the creator-tools card", async () => {
    await expect(page.getByText("Creator tools")).toBeVisible();

    await page
      .getByRole("button", { name: "Resolve YES", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Confirm YES", exact: true })
      .click();

    await expect(page.getByRole("status")).toContainText(
      "Market resolved YES",
    );
    await expect(page.getByText("Resolved YES.")).toBeVisible();
    // trading is over: the trade panel swaps its submit for a dead button
    await expect(
      page.getByRole("button", { name: "Market resolved" }),
    ).toBeDisabled();
  });
});
