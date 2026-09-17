// web/tests/e2e/smoke.spec.ts
// The browser smoke test against a running web app and API holding the FJC
// fixture (tests/fixtures/fjc): home, search, judge, court, and the theme
// toggle. Sonia Sotomayor (FJC nid 1388091) is in the fixture and in the
// live export alike, so the same assertions hold on a developer's database.
import { expect, test, type Page } from "@playwright/test";

const FIXTURE_JUDGE = { surname: "Sotomayor", name: "Sonia Sotomayor" };

async function openFixtureJudge(page: Page): Promise<void> {
  await page.goto(`/search?q=${FIXTURE_JUDGE.surname}`);
  await page
    .getByTestId("search-result")
    .filter({ hasText: FIXTURE_JUDGE.name })
    .first()
    .getByRole("link", { name: FIXTURE_JUDGE.name })
    .click();
  await expect(page.getByTestId("judge-name")).toHaveText(FIXTURE_JUDGE.name);
}

test("home renders and `/` focuses the search box", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Judicial outcomes, measured from data",
  );
  await expect(page.getByTestId("tile-judges")).toContainText(/\d/);
  await expect(page.getByTestId("methodology-link")).toBeVisible();

  await page.locator("body").click();
  await page.keyboard.press("/");
  await expect(page.getByTestId("search-input")).toBeFocused();
});

test("searching a fixture judge's surname lists the judge", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("search-input").fill(FIXTURE_JUDGE.surname);
  await page.getByTestId("search-input").press("Enter");
  await expect(page).toHaveURL(/\/search\?q=Sotomayor/);
  const row = page.getByTestId("search-result").filter({ hasText: FIXTURE_JUDGE.name });
  await expect(row.first()).toBeVisible();
  await expect(row.first().getByTestId("entity-type")).toHaveText("Judge");
});

test("the judge page shows service rows and the source panel", async ({ page }) => {
  await openFixtureJudge(page);
  await expect(page.getByTestId("judge-status")).toBeVisible();
  const rows = page.getByTestId("service-row");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThanOrEqual(1);

  const panel = page.getByTestId("provenance-panel");
  await expect(panel.getByRole("heading", { name: "Source coverage" })).toBeVisible();
  const entries = panel.getByTestId("provenance-entry");
  expect(await entries.count()).toBeGreaterThanOrEqual(1);
  await expect(entries.first().getByTestId("hash-truncated")).toHaveText(/^[0-9a-f]{12}…$/);
  await expect(panel.getByTestId("report-data-issue")).toHaveAttribute(
    "href",
    /github\.com\/.*\/issues\/new\?template=data_source_issue\.md/,
  );
  await expect(
    panel.getByRole("link", { name: "Source export page" }).first(),
  ).toHaveAttribute("href", /fjc\.gov/);
});

test("the theme toggle switches data-theme", async ({ page }) => {
  await page.goto("/methodology");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", /^(light|dark)$/);
  const before = await html.getAttribute("data-theme");
  const toggle = page.getByTestId("theme-toggle");
  await toggle.click();
  await expect(html).toHaveAttribute("data-theme", before === "dark" ? "light" : "dark");
  await toggle.click();
  await expect(html).toHaveAttribute("data-theme", before ?? "light");
});

test("the court page lists judges serving on a date", async ({ page }) => {
  await openFixtureJudge(page);
  // Her last appointment: the Supreme Court, from 2009-08-06.
  const supremeCourt = page
    .getByTestId("service-row")
    .filter({ hasText: "Supreme Court of the United States" })
    .getByRole("link");
  await supremeCourt.click();
  await expect(page.getByTestId("court-name")).toHaveText("Supreme Court of the United States");

  await page.getByTestId("active-on").fill("2010-01-01");
  await page.getByRole("button", { name: "Show judges" }).click();
  await expect(page).toHaveURL(/active_on=2010-01-01/);
  await expect(page.getByTestId("judges-summary")).toContainText("Jan 1, 2010");
  const judges = page.getByTestId("court-judge-row");
  await expect(judges.filter({ hasText: FIXTURE_JUDGE.name })).toHaveCount(1);
});

test("an unknown judge id is a 404 and the methodology page carries the statement", async ({
  page,
}) => {
  const response = await page.goto("/judges/00000000-0000-4000-8000-000000000000");
  expect(response?.status()).toBe(404);
  await page.goto("/methodology");
  await expect(page.getByTestId("association-statement")).toHaveText(
    "These statistics describe associations in available records. They do not prove that a judicial decision caused a later event.",
  );
  await expect(page.getByTestId("principles").getByRole("listitem")).toHaveCount(10);
});
