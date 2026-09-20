// web/tests/e2e/first-milestone.spec.ts
// The brief's first-milestone checklist, items 8–16, as one test each in
// order, against a running web app and API over the seeded demo dataset
// with computed metrics (`uv run poe bootstrap` locally; the CI `e2e` job
// seeds and computes the same). Items 1–7 (clone, setup, database,
// migrations, seed, API, web) are the commands the README maps them to and
// `scripts/verify_phase03.py --post` (Step 6) runs them; item 17 is `uv run
// poe check`. The suite shares one discovered judge: a synthetic circuit
// judge with an unsuppressed pretrial release share and an unsuppressed
// 365-day new-case rate, found through /metrics/compare and
// /judges/{id}/metrics, with at least one closed case. A final test
// submits the corrections form for that judge and asserts the received
// page shows the request id (and never the contact).
import { expect, request as playwrightRequest, test, type APIRequestContext } from "@playwright/test";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);
const METRIC = "pretrial_release_share";
const OUTCOME_METRIC = "new_case_rate";
const WINDOW = 365;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Scenario {
  judgeId: string;
  judgeName: string;
  surname: string;
  courtId: string;
  jurisdictionId: string;
}

async function json<T>(api: APIRequestContext, path: string): Promise<T> {
  const response = await api.get(`${API_BASE_URL}${path}`);
  expect(response.ok(), `${path} answered ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

/**
 * A synthetic circuit judge whose pretrial release share and 365-day
 * new-case rate are both published (unsuppressed), with a closed case.
 */
async function discover(api: APIRequestContext): Promise<Scenario> {
  const courts = await json<{ items: { id: string; synthetic: boolean; jurisdiction_id: string }[] }>(
    api,
    "/api/v1/courts?court_type=circuit&limit=100",
  );
  const synthetic = courts.items.filter((court) => court.synthetic);
  expect(synthetic.length, "no synthetic circuit court is ingested").toBeGreaterThan(0);
  for (const court of synthetic) {
    const page = await json<{ items: { subject_id: string; name: string; suppressed: boolean }[] }>(
      api,
      `/api/v1/metrics/compare?metric=${METRIC}&court_id=${court.id}&sort=denominator&order=desc&limit=100`,
    );
    for (const row of page.items.filter((item) => !item.suppressed)) {
      const metrics = await json<{ observations: Record<string, { window_days: number | null; suppressed: boolean }[]> }>(
        api,
        `/api/v1/judges/${row.subject_id}/metrics`,
      );
      const outcome = (metrics.observations[OUTCOME_METRIC] ?? []).find(
        (observation) => observation.window_days === WINDOW && !observation.suppressed,
      );
      if (!outcome) continue;
      const cases = await json<{ total: number }>(api, `/api/v1/judges/${row.subject_id}/cases?status=closed&limit=1`);
      if (cases.total === 0) continue;
      const words = row.name.trim().split(/\s+/);
      return {
        judgeId: row.subject_id,
        judgeName: row.name,
        surname: words[words.length - 1],
        courtId: court.id,
        jurisdictionId: court.jurisdiction_id,
      };
    }
  }
  throw new Error(`no synthetic circuit judge with an unsuppressed ${METRIC} and ${OUTCOME_METRIC} at ${WINDOW} days`);
}

test.describe.serial("the first milestone, items 8–16", () => {
  let scenario: Scenario;

  test.beforeAll(async () => {
    const api = await playwrightRequest.newContext();
    try {
      scenario = await discover(api);
    } finally {
      await api.dispose();
    }
  });

  test("8. open the website: the demo-data banner and the search box", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Judicial outcomes, measured from data");
    await expect(page.getByTestId("synthetic-banner")).toContainText("Demo data");
    await expect(page.getByTestId("search-input")).toBeVisible();
    await expect(page.getByTestId("tile-judges")).toContainText(/\d/);
  });

  test("9. search for a synthetic judge by surname", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("search-input").fill(scenario.surname);
    await page.getByTestId("search-input").press("Enter");
    await expect(page).toHaveURL((url) => url.pathname === "/search" && url.searchParams.get("q") === scenario.surname);
    const row = page.getByTestId("search-result").filter({ hasText: scenario.judgeName }).first();
    await expect(row).toBeVisible();
    await expect(row.getByTestId("entity-type")).toHaveText("Judge");
    await expect(row.getByTestId("synthetic-badge")).toBeVisible();
  });

  test("10. open the judge's profile: header and synthetic badge", async ({ page }) => {
    await page.goto(`/search?q=${encodeURIComponent(scenario.surname)}`);
    await page
      .getByTestId("search-result")
      .filter({ hasText: scenario.judgeName })
      .first()
      .getByRole("link", { name: scenario.judgeName })
      .click();
    await expect(page).toHaveURL((url) => url.pathname === `/judges/${scenario.judgeId}`);
    const header = page.locator("header").filter({ has: page.getByTestId("judge-name") });
    await expect(page.getByTestId("judge-name")).toHaveText(scenario.judgeName);
    await expect(header.getByTestId("synthetic-badge")).toBeVisible();
    await expect(header.getByTestId("report-data-error")).toHaveAttribute("data-target-type", "judge");
    await expect(page.getByTestId("association-statement")).toContainText("do not prove");
  });

  test("11. view case volume and objective outcome metrics", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    const cases = page.locator('#cases[data-testid="metric-panel"]');
    const eligible = cases.locator(`[data-testid="metric-stat"][data-slug="eligible_cases"]`).first();
    await expect(eligible).toHaveAttribute("data-suppressed", "false");
    await expect(eligible.getByTestId("metric-figure")).toHaveText(/^[\d,]+$/);
    await expect(eligible.getByTestId("metric-period")).toContainText(/\d{4}/);
    await expect(cases.getByTestId("report-data-error")).toHaveAttribute("data-target-type", "metric_observation");

    const outcomes = page.locator('#outcomes[data-testid="metric-panel"]');
    const rate = outcomes
      .locator(`[data-testid="metric-stat"][data-slug="${OUTCOME_METRIC}"][data-window="${WINDOW}"][data-variant="default"]`)
      .first();
    await expect(rate).toHaveAttribute("data-suppressed", "false");
    await expect(rate.getByTestId("metric-figure")).toHaveText(/^\d+\.\d%$/);
    await expect(rate.getByTestId("metric-fraction")).toHaveText(/^[\d,]+ \/ [\d,]+$/);
    await expect(rate.getByTestId("metric-interval")).toContainText("95% Wilson interval");
    await expect(rate.getByTestId("metric-sample")).toContainText("eligible");
    await expect(rate.getByTestId("metric-coverage")).toContainText("synthetic");
    await expect(rate.getByTestId("methodology-link")).toHaveAttribute("href", `/methodology#${OUTCOME_METRIC}`);
  });

  test("12. open an underlying synthetic case from the cases panel", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    const panel = page.getByTestId("cases-panel");
    await expect(panel.getByTestId("case-count")).toHaveText(/^[\d,]+$/);
    await panel.getByTestId("cases-link").click();
    await expect(page).toHaveURL((url) => url.pathname === `/judges/${scenario.judgeId}/cases`);
    const firstCase = page.getByTestId("case-row").first();
    await expect(firstCase).toBeVisible();
    await firstCase.getByRole("link").first().click();
    await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
    await expect(page.getByTestId("case-number")).toBeVisible();
    await expect(page.getByTestId("synthetic-badge").first()).toBeVisible();
  });

  test("13. view the case's event timeline and provenance with a sha256", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}/cases`);
    await page.getByTestId("case-row").first().getByRole("link").first().click();
    await expect(page).toHaveURL(/\/cases\//);
    const timeline = page.getByTestId("case-timeline");
    const entries = timeline.getByTestId("timeline-entry");
    expect(await entries.count()).toBeGreaterThanOrEqual(2);
    await expect(entries.first()).toHaveAttribute("data-kind", "filed");
    await expect(entries.first().locator("time").first()).toHaveAttribute("datetime", /\d{4}-\d{2}-\d{2}/);
    const sources = page.getByTestId("provenance-panel");
    await expect(sources.getByRole("heading", { name: "Sources" })).toBeVisible();
    const hash = sources.getByTestId("hash-truncated").first();
    await expect(hash).toHaveText(/^[0-9a-f]{12}…$/);
    await expect(hash).toHaveAttribute("aria-label", /^sha256 [0-9a-f]{64}$/);
    await expect(page.getByTestId("report-data-error").first()).toHaveAttribute("data-target-type", "case");
  });

  test("14. return to the judge page", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    await page.getByTestId("cases-panel").getByTestId("cases-link").click();
    await page.getByTestId("case-row").first().getByRole("link").first().click();
    await expect(page).toHaveURL(/\/cases\//);
    await page.goBack();
    await expect(page).toHaveURL((url) => url.pathname === `/judges/${scenario.judgeId}/cases`);
    await page.goBack();
    await expect(page).toHaveURL((url) => url.pathname === `/judges/${scenario.judgeId}`);
    await expect(page.getByTestId("judge-name")).toHaveText(scenario.judgeName);
  });

  test("15. compare the metric against the judge's comparison cohort", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    const row = page.locator(`[data-testid="metric-row"][data-slug="${METRIC}"]`).first();
    // The court's pooled value sits beside the judge's own, at the default cohort.
    await expect(row.locator('[data-testid="metric-stat"][data-variant="default"]')).toHaveAttribute("data-suppressed", "false");
    await expect(row.locator('[data-testid="metric-stat"][data-variant="compact"]').getByTestId("metric-label")).toContainText("court, pooled");
    await expect(row.getByTestId("cohort-position")).toContainText("Same court, same period");

    // Switch the cohort to the jurisdiction; the page state is the URL.
    await page.locator("#outcomes").getByTestId("cohort-selector").locator("select").selectOption("jurisdiction");
    await expect(page).toHaveURL(/cohort=jurisdiction/);
    const switched = page.locator(`[data-testid="metric-row"][data-slug="${METRIC}"]`).first();
    await expect(switched.getByTestId("cohort-position")).toContainText("Jurisdiction, same period");
    await expect(switched.locator('[data-testid="metric-stat"][data-variant="compact"]')).toBeVisible();

    // Follow the compare link: the judge's row with its sample-size cell.
    await switched.getByTestId("compare-link").click();
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/compare" &&
        url.searchParams.get("metric") === METRIC &&
        url.searchParams.get("jurisdiction_id") === scenario.jurisdictionId,
    );
    const judgeRow = page.locator(`[data-testid="compare-row"][data-judge="${scenario.judgeId}"]`);
    await expect(judgeRow).toHaveCount(1);
    await expect(judgeRow.getByTestId("compare-sample")).toHaveText(/^[\d,]+$/);
    await expect(judgeRow.getByTestId("compare-figure")).toHaveText(/%$/);
    await expect(judgeRow.getByTestId("compare-interval")).toContainText("95%");
  });

  test("16. open the methodology page at exactly that metric", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    await page
      .locator(`[data-testid="metric-stat"][data-slug="${METRIC}"][data-variant="default"]`)
      .first()
      .getByTestId("methodology-link")
      .click();
    await expect(page).toHaveURL((url) => url.pathname === "/methodology" && url.hash === `#${METRIC}`);
    const section = page.locator(`section#${METRIC}`);
    await expect(section).toBeVisible();
    await expect(section.getByTestId("definition-formula")).toContainText("Numerator:");
    await expect(section.getByTestId("definition-formula")).toContainText("Denominator:");
    await expect(page.getByTestId("known-limitations").getByRole("listitem")).toHaveCount(8);
    await expect(page.getByTestId("association-statement")).toContainText("do not prove");
  });

  test("a correction submitted through the form is received with an id", async ({ page }) => {
    await page.goto(`/judges/${scenario.judgeId}`);
    await page.locator('[data-testid="report-data-error"][data-target-type="judge"]').click();
    await expect(page).toHaveURL(/\/corrections\?target_type=judge/);
    expect(page.url()).toContain(`target_id=${scenario.judgeId}`);
    await expect(page.getByTestId("target-summary")).toContainText(scenario.judgeName);
    await expect(page.getByTestId("target-id")).toHaveValue(scenario.judgeId);
    await expect(page.getByTestId("consent")).toContainText("stored encrypted");
    await expect(page.getByTestId("submit-correction")).toBeDisabled();

    await page
      .getByTestId("reason")
      .fill("First-milestone walkthrough: the current appointment shown for this synthetic judge should be checked against the source record.");
    await page.getByTestId("contact").fill("requester@example.invalid");
    await expect(page.getByTestId("submit-correction")).toBeEnabled();
    await page.getByTestId("submit-correction").click();

    await expect(page).toHaveURL(/\/corrections\/received\?id=[0-9a-f-]{36}$/);
    const id = (await page.getByTestId("correction-id").textContent())?.trim() ?? "";
    expect(id).toMatch(UUID);
    await expect(page.getByTestId("correction-status")).toHaveText("received");
    await expect(page.locator("body")).not.toContainText("requester@example.invalid");
  });
});
