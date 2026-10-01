// web/tests/e2e/adjusted.spec.ts
// The risk-adjusted flow against a running web app and API over the demo
// seed (its thirteen models are fitted; the golden fixture's are not, so a
// shown ratio needs the seed): discover through the API a synthetic judge
// with a published 365-day new-case ratio, open the judge page, check the
// "Risk-adjusted comparison" panel shows the ratio, its bootstrap interval,
// the methodology version, the raw rate it adjusts, the cohort definition,
// and a model link; switch `?window=` and see the panel's windows change;
// follow the model link to the card's coefficient table; open /compare for
// the adjusted metric and check it sorts by ratio; resolve the methodology
// anchor `#adjusted-statistics`; and open a judge whose adjusted row is
// suppressed to see the reason in words.
import { expect, test, type APIRequestContext } from "@playwright/test";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);
const METRIC = "new_case_observed_expected";
const ADJUSTED_SLUGS = [
  "pretrial_release_observed_expected",
  "new_case_observed_expected",
  "failure_to_appear_observed_expected",
];
const WINDOWS = [30, 90, 180, 365, 730, 1095];

interface CompareItem {
  subject_id: string;
  name: string;
  suppressed: boolean;
  suppression_reason: string | null;
  ratio: number | null;
}

async function syntheticCourts(request: APIRequestContext): Promise<string[]> {
  const courts = await (await request.get(`${API_BASE_URL}/api/v1/courts?limit=100`)).json();
  const ids = courts.items
    .filter((court: { synthetic: boolean }) => court.synthetic)
    .map((court: { id: string }) => court.id);
  expect(ids.length, "no synthetic court is ingested").toBeGreaterThan(0);
  return ids;
}

async function compareItems(
  request: APIRequestContext,
  courtId: string,
  metric: string,
  window: number | null,
): Promise<CompareItem[]> {
  const query = `metric=${metric}&court_id=${courtId}${window === null ? "" : `&window=${window}`}&limit=100`;
  const response = await request.get(`${API_BASE_URL}/api/v1/metrics/compare?${query}`);
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()).items as CompareItem[];
}

/** A synthetic court whose 365-day new-case ratio has a published row, and that row's judge. */
async function findPublished(request: APIRequestContext): Promise<{ judgeId: string; judgeName: string; courtId: string }> {
  for (const courtId of await syntheticCourts(request)) {
    const row = (await compareItems(request, courtId, METRIC, 365)).find((item) => !item.suppressed);
    if (row) return { judgeId: row.subject_id, judgeName: row.name, courtId };
  }
  throw new Error("no synthetic judge with a published 365-day new-case ratio (run `uv run poe bootstrap`)");
}

/** A judge with a suppressed adjusted row, the slug, the window, and the reason. */
async function findSuppressed(
  request: APIRequestContext,
): Promise<{ judgeId: string; slug: string; window: number | null; reason: string }> {
  for (const courtId of await syntheticCourts(request)) {
    for (const slug of ADJUSTED_SLUGS) {
      for (const window of slug === "pretrial_release_observed_expected" ? [null] : WINDOWS) {
        const row = (await compareItems(request, courtId, slug, window)).find((item) => item.suppressed);
        if (row?.suppression_reason) {
          return { judgeId: row.subject_id, slug, window, reason: row.suppression_reason };
        }
      }
    }
  }
  throw new Error("no synthetic judge with a suppressed adjusted observation");
}

test("the judge's risk-adjusted panel shows a ratio, its interval, the methodology version, and a model link", async ({
  page,
  request,
}) => {
  const scenario = await findPublished(request);

  await page.goto(`/judges/${scenario.judgeId}`);
  await expect(page.getByTestId("judge-name")).toHaveText(scenario.judgeName);
  const panel = page.locator('#adjusted[data-testid="metric-panel"]');
  await expect(panel.getByRole("heading", { name: "Risk-adjusted comparison" })).toBeVisible();
  // The association statement still renders once per page.
  await expect(page.getByTestId("association-statement")).toHaveCount(1);

  const stat = panel.locator(`[data-testid="adjusted-stat"][data-slug="${METRIC}"]`);
  await expect(stat).toHaveAttribute("data-window", "365");
  await expect(stat).toHaveAttribute("data-suppressed", "false");
  await expect(stat.getByTestId("adjusted-ratio")).toHaveText(/^\d+\.\d\d$/);
  await expect(stat.getByTestId("adjusted-interval")).toHaveText(/^\d+\.\d\d–\d+\.\d\d \(95% bootstrap interval\)$/);
  await expect(stat.getByTestId("adjusted-observed")).toHaveText(/^[\d,]+$/);
  await expect(stat.getByTestId("adjusted-expected")).toHaveText(/^[\d,]+\.\d$/);
  await expect(stat.getByTestId("adjusted-pooling")).toContainText("estimate pooled toward 1.0");
  await expect(stat.getByTestId("adjusted-sample")).toContainText("in the ratio");
  await expect(stat.getByTestId("methodology-version")).toHaveText("Methodology 1.0");
  await expect(stat.getByTestId("methodology-link")).toHaveAttribute("href", `/methodology#${METRIC}`);
  await expect(stat.getByTestId("adjusted-cohort")).toContainText("Expected counts from model expected-logit-v1");
  await expect(stat.getByTestId("adjusted-interpretation")).toContainText("An O/E ratio above 1 means");
  await expect(stat.getByTestId("cohort-position")).toContainText("Same court, same period");
  await expect(stat.getByTestId("synthetic-badge")).toBeVisible();
  // The raw rate it adjusts sits beside it.
  const row = panel.locator(`[data-testid="adjusted-row"][data-slug="${METRIC}"]`);
  await expect(row.locator('[data-testid="metric-stat"][data-slug="new_case_rate"][data-window="365"]')).toBeVisible();
  await expect(panel.getByTestId("report-data-error")).toBeVisible();
  await expect(stat.getByTestId("adjusted-model")).toHaveAttribute("href", /^\/models\/[0-9a-f-]{36}$/);
});

test("switching ?window= changes the adjusted panel's windows", async ({ page, request }) => {
  const scenario = await findPublished(request);
  await page.goto(`/judges/${scenario.judgeId}`);
  const panel = page.locator('#adjusted[data-testid="metric-panel"]');
  await expect(panel.locator(`[data-testid="adjusted-stat"][data-slug="${METRIC}"]`)).toHaveAttribute("data-window", "365");
  await panel.getByTestId("window-selector").locator("select").selectOption("90");
  await expect(page).toHaveURL(/window=90/);
  const after = page.locator("#adjusted");
  await expect(after.locator(`[data-testid="adjusted-stat"][data-slug="${METRIC}"]`)).toHaveAttribute("data-window", "90");
  expect(await after.locator('[data-testid="adjusted-stat"][data-window="365"]').count()).toBe(0);
  await expect(
    after.locator('[data-testid="adjusted-stat"][data-slug="pretrial_release_observed_expected"]'),
  ).toHaveAttribute("data-window", "all");
});

test("the model link opens the model card with its coefficient table", async ({ page, request }) => {
  const scenario = await findPublished(request);
  await page.goto(`/judges/${scenario.judgeId}?window=90`);
  const stat = page.locator(`#adjusted [data-testid="adjusted-stat"][data-slug="${METRIC}"]`);
  await expect(stat).toHaveAttribute("data-window", "90");
  await stat.getByTestId("adjusted-model").click();
  await expect(page).toHaveURL(/\/models\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("model-target")).toHaveText("New Case, 90 days");
  await expect(page.getByTestId("model-status")).toHaveAttribute("data-status", "fitted");
  await expect(page.getByTestId("coefficient-table")).toBeVisible();
  expect(await page.getByTestId("coefficient-row").count()).toBeGreaterThan(1);
  await expect(page.getByTestId("calibration-table").getByTestId("calibration-bin")).toHaveCount(10);
  await expect(page.getByTestId("model-methodology-link")).toHaveAttribute("href", "/methodology#adjusted-statistics");
});

test("compare sorts an adjusted metric by its pooled ratio", async ({ page, request }) => {
  const scenario = await findPublished(request);
  await page.goto(`/compare?metric=${METRIC}&window=365&court_id=${scenario.courtId}`);
  const table = page.getByTestId("compare-table");
  await expect(table).toHaveAttribute("data-kind", "observed_expected");
  await expect(page.getByTestId("sort-ratio").locator("xpath=ancestor::th")).toHaveAttribute("aria-sort", "descending");
  const figures = await table.getByTestId("compare-figure").allTextContents();
  expect(figures.length).toBeGreaterThan(0);
  const ratios = figures.map((text) => Number.parseFloat(text));
  expect(ratios).toEqual([...ratios].sort((a, b) => b - a));
  // Suppressed rows come after every published ratio and show their reason.
  const states = await table.getByTestId("compare-row").evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-suppressed")),
  );
  const firstSuppressed = states.indexOf("true");
  if (firstSuppressed !== -1) expect(states.slice(firstSuppressed)).not.toContain("false");
  await expect(page.getByTestId("adjusted-formula")).toContainText("(α + O) / (α + E)");
  await expect(page.getByTestId("model-link")).toHaveAttribute("href", /\/models\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("adjusted-interpretation")).toContainText("An O/E ratio above 1 means");
});

test("the methodology anchor #adjusted-statistics resolves", async ({ page }) => {
  await page.goto("/methodology#adjusted-statistics");
  const section = page.locator("section#adjusted-statistics");
  await expect(section).toBeVisible();
  await expect(section.getByRole("heading", { name: "Adjusted statistics" })).toBeVisible();
  await expect(section.getByTestId("adjustment-interpretation")).toContainText("An O/E ratio above 1 means");
  await expect(page.locator(`section#${METRIC}`)).toContainText("observed-to-expected ratio");
});

test("a judge whose adjusted row is suppressed shows the reason", async ({ page, request }) => {
  const scenario = await findSuppressed(request);
  await page.goto(`/judges/${scenario.judgeId}${scenario.window === null ? "" : `?window=${scenario.window}`}`);
  const stat = page.locator(`#adjusted [data-testid="adjusted-stat"][data-slug="${scenario.slug}"]`);
  await expect(stat).toHaveAttribute("data-suppressed", "true");
  await expect(stat).toHaveAttribute("data-reason", scenario.reason);
  await expect(stat.getByTestId("adjusted-suppression")).toContainText("Suppressed:");
  expect(await stat.getByTestId("adjusted-figures").count()).toBe(0);
  await expect(stat.getByTestId("methodology-version")).toHaveText("Methodology 1.0");
});
