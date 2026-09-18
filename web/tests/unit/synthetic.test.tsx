// web/tests/unit/synthetic.test.tsx
// The demo-data surfaces: the banner renders only when /coverage reports a
// synthetic source (and never when the call fails), the synthetic badge,
// the actor badge for every actor type, and the timeline entry rendering
// (ordered list, <time> elements, actor and discretion badges, the source).
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ACTOR_LABELS, ActorBadge, DiscretionBadge, SyntheticBadge } from "@/components/badges";
import { CaseTimeline } from "@/components/case-timeline";
import {
  SYNTHETIC_BANNER_TEXT,
  SyntheticBanner,
  SyntheticBannerView,
} from "@/components/synthetic-banner";
import type { ActorType, Coverage, TimelineEntry } from "@/lib/api/client";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function coverage(syntheticPresent: boolean): Coverage {
  return {
    sources: [],
    synthetic_present: syntheticPresent,
    generated_at: "2026-09-18T12:00:00Z",
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SyntheticBanner", () => {
  it("renders the notice when a synthetic source is present", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(coverage(true)));
    render(await SyntheticBanner());
    const banner = screen.getByTestId("synthetic-banner");
    expect(banner).toHaveAttribute("role", "note");
    expect(banner).toHaveTextContent(SYNTHETIC_BANNER_TEXT);
    expect(within(banner).getByRole("link", { name: /coverage/ })).toHaveAttribute(
      "href",
      "/coverage",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when no synthetic source is present", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(coverage(false)));
    const { container } = render(await SyntheticBanner());
    expect(screen.queryByTestId("synthetic-banner")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the coverage call fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    render(await SyntheticBanner());
    expect(screen.queryByTestId("synthetic-banner")).toBeNull();

    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "database_unavailable", message: "database unavailable", request_id: "r" },
        { status: 503 },
      ),
    );
    render(await SyntheticBanner());
    expect(screen.queryByTestId("synthetic-banner")).toBeNull();
  });

  it("has no dismiss control", () => {
    render(<SyntheticBannerView present />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("badges", () => {
  it("labels a synthetic entity", () => {
    render(<SyntheticBadge />);
    const badge = screen.getByTestId("synthetic-badge");
    expect(badge).toHaveTextContent("Synthetic");
    expect(badge).toHaveAttribute("title", expect.stringMatching(/not a court record/));
  });

  it("renders an actor badge for every actor type", () => {
    const actors = Object.keys(ACTOR_LABELS) as ActorType[];
    expect(actors).toEqual([
      "judge",
      "prosecutor",
      "defense",
      "jury",
      "clerk",
      "law_enforcement",
      "legislature_or_mandatory_rule",
      "appellate_court",
      "unknown",
    ]);
    render(
      <>
        {actors.map((actor) => (
          <ActorBadge key={actor} actor={actor} />
        ))}
      </>,
    );
    const badges = screen.getAllByTestId("actor-badge");
    expect(badges).toHaveLength(actors.length);
    expect(badges.map((badge) => badge.getAttribute("data-actor"))).toEqual(actors);
    expect(badges[0]).toHaveTextContent("Judge");
    expect(badges[1]).toHaveTextContent("Prosecutor");
    expect(badges[6]).toHaveTextContent("Mandatory rule");
  });

  it("renders the discretion classification", () => {
    render(<DiscretionBadge classification="non_judicial" />);
    expect(screen.getByTestId("discretion-badge")).toHaveTextContent("Non-judicial");
    expect(screen.getByTestId("discretion-badge")).toHaveAttribute(
      "data-classification",
      "non_judicial",
    );
  });
});

const SOURCE = {
  source: "synthetic",
  external_record_id: "source/decisions.csv",
  retrieved_at: "2026-09-18T12:00:00Z",
  raw_sha256: "ffc63d463627d15343006d2e72e54751202d10fe1e702f837d6f3e885f865ac5", // pragma: allowlist secret
  parser_version: "1",
  ingest_run_id: "b7784a75-5690-42f1-a509-2e4cf88b9d75",
  synthetic: true,
};

const ENTRIES: TimelineEntry[] = [
  {
    at: "2020-06-20T00:00:00Z",
    kind: "filed",
    actor_type: null,
    judge: null,
    label: "Case SYN-2020-000005 filed",
    detail: { date: "2020-06-20", case_number: "SYN-2020-000005", case_type: "misdemeanor" },
    source: { ...SOURCE, external_record_id: "source/cases.csv" },
  },
  {
    at: "2020-09-25T15:54:00Z",
    kind: "decision",
    actor_type: "prosecutor",
    judge: null,
    label: "Decision: dismissal",
    detail: { decision_type: "dismissal", judicial_discretion_classification: "non_judicial" },
    source: SOURCE,
  },
  {
    at: "2020-09-25T15:54:00Z",
    kind: "decision",
    actor_type: "judge",
    judge: { id: "3a221440-e710-4f65-b5b9-215b52a17d08", canonical_name: "Puce Wingnut" },
    label: "Decision: disposition",
    detail: { decision_type: "disposition", judicial_discretion_classification: "discretionary" },
    source: SOURCE,
  },
];

describe("CaseTimeline", () => {
  it("renders an ordered list with a time element, badges, and the source per entry", () => {
    render(<CaseTimeline entries={ENTRIES} />);
    const list = screen.getByTestId("case-timeline");
    expect(list.tagName).toBe("OL");
    const items = within(list).getAllByTestId("timeline-entry");
    expect(items).toHaveLength(3);

    const filed = within(items[0]);
    expect(items[0]).toHaveAttribute("data-kind", "filed");
    const filedTime = filed.getByText("Jun 20, 2020");
    expect(filedTime.tagName).toBe("TIME");
    expect(filedTime).toHaveAttribute("dateTime", "2020-06-20");
    expect(filed.queryByTestId("actor-badge")).toBeNull();

    const dismissal = within(items[1]);
    expect(dismissal.getByText("Sep 25, 2020, 03:54 PM UTC")).toHaveAttribute(
      "dateTime",
      "2020-09-25T15:54:00Z",
    );
    expect(dismissal.getByTestId("actor-badge")).toHaveTextContent("Prosecutor");
    expect(dismissal.getByTestId("discretion-badge")).toHaveTextContent("Non-judicial");
    expect(dismissal.queryByRole("link")).toBeNull();
    expect(dismissal.getByTestId("timeline-source")).toHaveTextContent("source/decisions.csv");

    const disposition = within(items[2]);
    expect(disposition.getByTestId("actor-badge")).toHaveTextContent("Judge");
    expect(disposition.getByRole("link", { name: "Puce Wingnut" })).toHaveAttribute(
      "href",
      "/judges/3a221440-e710-4f65-b5b9-215b52a17d08",
    );
    expect(disposition.getByText("ffc63d463627…")).toHaveAccessibleName(
      `sha256 ${SOURCE.raw_sha256}`,
    );
  });
});
