// web/tests/e2e/metrics.spec.ts
// The metric flow against a running web app and API over a synthetic
// dataset with computed metrics (the demo seed locally; CI switches its
// e2e job to the seed in Step 5): discover a synthetic judge with an
// unsuppressed pretrial release share through /metrics/compare sorted by
// denominator, open the judge page, check the statement precedes the
// panels and a MetricStat carries every presentation field, switch the
// window to 90 days, follow the compare link and find the judge's row with
// its sample size, then follow the methodology link to the anchored
// section with the formula. Also the compare page's validation and the
// coverage page's v1 fields.
import { expect, test, type APIRequestContext } from "@playwright/test";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

interface Scenario {
  judgeId: string;
  judgeName: string;
  courtId: string;
}

/** A synthetic court whose compare table for pretrial_release_share has an unsuppressed row. */
async function findScenario(request: APIRequestContext): Promise<Scenario> {
  const courts = await (await request.get(`${API_BASE_URL}/api/v1/courts?limit=100`)).json();
  const synthetic = courts.items.filter((court: { synthetic: boolean }) => court.synthetic);
  expect(synthetic.length, "no synthetic court is ingested").toBeGreaterThan(0);
  for (const court of synthetic) {
    const page = await (
      await request.get(
        `${API_BASE_URL}/api/v1/metrics/compare?metric=pretrial_release_share&court_id=${court.id}&sort=denominator&order=desc&limit=100`,
      )
    ).json();
    const row = page.items?.find((item: { suppressed: boolean }) => !item.suppressed);
    if (row) return { judgeId: row.subject_id, judgeName: row.name, courtId: court.id };
  }
  throw new Error("no synthetic judge with an unsuppressed pretrial_release_share");
}

test("judge panels → window switch → compare → methodology anchor", async ({ page, request }) => {
  const scenario = await findScenario(request);

  await page.goto(`/judges/${scenario.judgeId}`);
  await expect(page.getByTestId("judge-name")).toHaveText(scenario.judgeName);

  // The association statement precedes every panel in document order.
  const statement = page.getByTestId("association-statement");
  await expect(statement).toHaveText(
    "These statistics describe associations in available records. They do not prove that a judicial decision caused a later event.",
  );
  const precedes = await page.evaluate(() => {
    const statement = document.querySelector('[data-testid="association-statement"]');
    const panel = document.querySelector('[data-testid="metric-panel"]');
    if (!statement || !panel) return false;
    return Boolean(statement.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(precedes).toBe(true);
  for (const id of ["cases", "pretrial", "outcomes", "disposition", "sentencing"]) {
    await expect(page.locator(`#${id}[data-testid="metric-panel"]`)).toBeVisible();
  }

  // The pretrial release share stat carries every presentation field.
  const share = page
    .locator('[data-testid="metric-stat"][data-slug="pretrial_release_share"][data-variant="default"]')
    .first();
  await expect(share).toHaveAttribute("data-suppressed", "false");
  await expect(share.getByTestId("metric-figure")).toHaveText(/^\d+\.\d%$/);
  await expect(share.getByTestId("metric-fraction")).toHaveText(/^[\d,]+ \/ [\d,]+$/);
  await expect(share.getByTestId("metric-sample")).toContainText("eligible");
  await expect(share.getByTestId("metric-interval")).toContainText("95% Wilson interval");
  await expect(share.getByTestId("metric-period")).toContainText(/\d{4}/);
  await expect(share.getByTestId("metric-coverage")).toContainText("synthetic");
  await expect(share.getByTestId("methodology-link")).toHaveAttribute(
    "href",
    "/methodology#pretrial_release_share",
  );
  await expect(share.getByTestId("synthetic-badge")).toBeVisible();
  await expect(share.getByTestId("cohort-position")).toContainText("Same court, same period");
  await expect(page.locator("#pretrial").getByTestId("eligible-cases-link")).toHaveAttribute(
    "href",
    `/judges/${scenario.judgeId}/cases`,
  );

  // The outcomes panel follows the window selector.
  const outcomes = page.locator("#outcomes");
  await expect(outcomes.locator('[data-testid="metric-stat"][data-window="365"]').first()).toBeVisible();
  await outcomes.getByTestId("window-selector").locator("select").selectOption("90");
  await expect(page).toHaveURL(/window=90/);
  await expect(page.locator("#outcomes").locator('[data-testid="metric-stat"][data-window="90"]').first()).toBeVisible();
  expect(await page.locator("#outcomes").locator('[data-testid="metric-stat"][data-window="365"]').count()).toBe(0);
  await expect(page.locator("#outcomes").getByTestId("not-observable").first()).toContainText(
    "Not observable in this source",
  );

  // The compare link from the pretrial share leads to the judge's row with a sample-size cell.
  await page.locator('[data-testid="metric-stat"][data-slug="pretrial_release_share"]').first().getByTestId("compare-link").click();
  await expect(page).toHaveURL(/\/compare\?metric=pretrial_release_share/);
  expect(page.url()).toContain(`court_id=${scenario.courtId}`);
  const row = page.locator(`[data-testid="compare-row"][data-judge="${scenario.judgeId}"]`);
  await expect(row).toHaveCount(1);
  await expect(row.getByTestId("compare-sample")).toHaveText(/^[\d,]+$/);
  await expect(row.getByTestId("compare-figure")).toHaveText(/%$/);
  await expect(page.getByTestId("comparison-notes")).toContainText("associations");

  // The methodology link anchors at the metric's section, which shows the formula.
  await page.getByTestId("comparison-notes").getByTestId("methodology-link").click();
  await expect(page).toHaveURL(/\/methodology#pretrial_release_share$/);
  const section = page.locator("section#pretrial_release_share");
  await expect(section).toBeVisible();
  await expect(section.getByTestId("definition-formula")).toContainText("Numerator:");
  await expect(section.getByTestId("definition-formula")).toContainText("Denominator:");
  await expect(page.getByTestId("known-limitations").getByRole("listitem")).toHaveCount(8);
});

test("the compare page validates its query and marks suppressed rows", async ({ page, request }) => {
  const scenario = await findScenario(request);
  await page.goto(`/compare?metric=not_a_metric&court_id=${scenario.courtId}`);
  await expect(page.getByTestId("error-state")).toContainText("metric");
  await page.goto(`/compare?metric=new_case_rate&window=91&court_id=${scenario.courtId}`);
  await expect(page.getByTestId("error-state")).toContainText("window");
  await page.goto(`/compare?metric=new_case_rate&window=365&court_id=${scenario.courtId}&sort=rate&order=asc`);
  await expect(page.getByTestId("compare-table")).toBeVisible();
  await expect(page.getByTestId("sort-rate").locator("xpath=ancestor::th")).toHaveAttribute("aria-sort", "ascending");
  const rows = page.getByTestId("compare-row");
  expect(await rows.count()).toBeGreaterThanOrEqual(1);
  for (const row of await rows.all()) {
    const suppressed = (await row.getAttribute("data-suppressed")) === "true";
    if (suppressed) {
      await expect(row.getByTestId("compare-suppressed")).toContainText("Suppressed");
      expect(await row.getByTestId("compare-figure").count()).toBe(0);
    }
  }
  await page.goto("/compare");
  await expect(page.getByTestId("empty-state")).toContainText("Choose a court or a jurisdiction");
});

test("the coverage page states the window, the outcomes, and the snapshot per source", async ({ page }) => {
  await page.goto("/coverage");
  await expect(page.getByTestId("snapshot-card").getByTestId("registry-version")).toHaveText(/^\d+$/);
  await expect(page.getByTestId("snapshot-card").getByTestId("methodology-version")).toHaveText(/^\d+\.\d+$/);
  await expect(page.getByTestId("latest-snapshot").getByTestId("snapshot-hash")).toHaveText(/^[0-9a-f]{12}…$/);
  const synthetic = page.locator('[data-testid="coverage-source"][data-source="synthetic"]');
  await expect(synthetic.getByTestId("coverage-declared")).toContainText(/\d{4}/);
  await expect(synthetic.getByTestId("observable-outcomes")).toContainText("New Case");
  await expect(synthetic.getByTestId("not-observable-outcomes")).toContainText("Rearrest");
  await expect(synthetic.getByTestId("source-snapshot").getByTestId("snapshot-hash")).toHaveText(/^[0-9a-f]{12}…$/);
  await expect(synthetic.getByTestId("source-methodology")).toContainText("version");
});
