// web/tests/e2e/smoke.spec.ts
// The browser smoke test against a running web app and API holding the FJC
// fixture (tests/fixtures/fjc) and a synthetic dataset (the golden fixture
// in CI, the demo seed on a developer's machine): home, search, judge,
// court, the theme toggle, and the case flow. Sonia Sotomayor (FJC nid
// 1388091) is in the fixture and in the live export alike, so the same
// assertions hold on a developer's database; the synthetic judge and case
// are discovered through the API, since the golden and demo datasets name
// different judges.
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FIXTURE_JUDGE = { surname: "Sotomayor", name: "Sonia Sotomayor" };
const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

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

// --- the case flow (Phase 2 Step 4) -------------------------------------------------

type SyntheticScenario = {
  judgeName: string;
  caseNumber: string;
  filedDate: string;
  personKey: string;
};

/**
 * A synthetic judge and one of their cases that carries a prosecutor's
 * dismissal, a judicial decision, and a sentence: found through the API so
 * the scenario holds on the golden fixture and the demo seed alike.
 */
async function findSyntheticScenario(request: APIRequestContext): Promise<SyntheticScenario> {
  const courts = await (await request.get(`${API_BASE_URL}/api/v1/courts?court_type=circuit&limit=100`)).json();
  const synthetic = courts.items.filter((court: { synthetic: boolean }) => court.synthetic);
  expect(synthetic.length, "no synthetic court is ingested").toBeGreaterThan(0);
  for (const court of synthetic) {
    const judges = await (
      await request.get(`${API_BASE_URL}/api/v1/judges?court_id=${court.id}&limit=100`)
    ).json();
    for (const judge of judges.items) {
      const cases = await (
        await request.get(`${API_BASE_URL}/api/v1/judges/${judge.id}/cases?status=closed&limit=100`)
      ).json();
      for (const item of cases.items) {
        const detail = await (await request.get(`${API_BASE_URL}/api/v1/cases/${item.id}`)).json();
        const actors = new Set(detail.decisions.map((d: { actor_type: string }) => d.actor_type));
        if (actors.has("prosecutor") && actors.has("judge") && detail.sentences.length > 0) {
          return {
            judgeName: judge.canonical_name,
            caseNumber: detail.case_number,
            filedDate: detail.filed_date,
            personKey: detail.parties[0].public_person_key,
          };
        }
      }
    }
  }
  throw new Error("no synthetic case with a prosecutor dismissal, a judicial decision, and a sentence");
}

test("a synthetic judge leads to a case page with attributed decisions and sources", async ({
  page,
  request,
}) => {
  const scenario = await findSyntheticScenario(request);

  // Search the judge: the result row carries the synthetic badge.
  await page.goto(`/search?q=${encodeURIComponent(scenario.judgeName)}`);
  const row = page.getByTestId("search-result").filter({ hasText: scenario.judgeName }).first();
  await expect(row.getByTestId("synthetic-badge")).toBeVisible();
  await row.getByRole("link", { name: scenario.judgeName }).click();

  // The judge page: banner, badge, and the cases panel.
  await expect(page.getByTestId("judge-name")).toHaveText(scenario.judgeName);
  await expect(page.getByTestId("synthetic-banner")).toContainText("Demo data");
  await expect(page.getByTestId("synthetic-badge").first()).toBeVisible();
  const panel = page.getByTestId("cases-panel");
  await expect(panel.getByTestId("case-count")).toHaveText(/^[\d,]+$/);
  await expect(panel.getByTestId("case-coverage")).toContainText(/\d{4}/);
  await panel.getByTestId("cases-link").click();

  // The cases list, filtered to the case's filing date, links to the case page.
  await expect(page).toHaveURL(/\/judges\/[0-9a-f-]+\/cases$/);
  await page.locator("#filed_from").fill(scenario.filedDate);
  await page.locator("#filed_to").fill(scenario.filedDate);
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/filed_from=\d{4}-\d{2}-\d{2}/);
  expect(page.url()).toContain(`filed_from=${scenario.filedDate}`);
  const caseRow = page.getByTestId("case-row").filter({ hasText: scenario.caseNumber });
  await expect(caseRow).toHaveCount(1);
  await caseRow.getByRole("link", { name: scenario.caseNumber }).click();

  // The case page: timeline, charges, actor badges, the sentence, the sources panel.
  await expect(page.getByTestId("case-number")).toHaveText(scenario.caseNumber);
  await expect(page.getByTestId("synthetic-banner")).toBeVisible();
  const timeline = page.getByTestId("case-timeline");
  expect(await timeline.getByTestId("timeline-entry").count()).toBeGreaterThanOrEqual(3);
  await expect(timeline.getByTestId("timeline-entry").first()).toHaveAttribute("data-kind", "filed");
  expect(await page.getByTestId("charge-row").count()).toBeGreaterThanOrEqual(1);
  const decisions = page.getByTestId("decisions");
  await expect(decisions.locator("[data-actor='prosecutor']").first()).toHaveText("Prosecutor");
  await expect(decisions.locator("[data-actor='judge']").first()).toHaveText("Judge");
  await expect(page.getByTestId("sentence").first()).toBeVisible();
  const sources = page.getByTestId("provenance-panel");
  await expect(sources.getByRole("heading", { name: "Sources" })).toBeVisible();
  expect(await sources.getByTestId("provenance-entry").count()).toBeGreaterThanOrEqual(3);
  // The party is the pseudonymous key the API returned; no name exists to render.
  await expect(page.getByTestId("case-parties")).toHaveText(`Defendant ${scenario.personKey}`);
});

test("the coverage page lists the synthetic source and the home tile counts cases", async ({
  page,
}) => {
  await page.goto("/coverage");
  const synthetic = page.getByTestId("coverage-source").filter({ has: page.getByTestId("synthetic-badge") });
  await expect(synthetic.first()).toBeVisible();
  await expect(synthetic.first().getByTestId("coverage-window")).toContainText(/\d{4}/);
  await expect(synthetic.first().getByTestId("coverage-last-run")).toContainText("succeeded");
  await expect(page.getByTestId("coverage-note")).toContainText("Phase 5");

  await page.goto("/");
  await expect(page.getByTestId("tile-cases")).toContainText(/[1-9]\d*/);
  await expect(page.getByTestId("synthetic-banner")).toBeVisible();
});
