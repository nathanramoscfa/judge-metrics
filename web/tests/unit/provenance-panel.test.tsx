// web/tests/unit/provenance-panel.test.tsx
// The source coverage panel: one entry per artifact, the sha256 truncated
// to twelve characters with the full digest in the accessible name, the
// copy button writing the full digest to the clipboard, and the links.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ProvenancePanel } from "@/components/provenance-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Provenance } from "@/lib/api/client";

const SHA = "b6a69ef26d40636f158f7c725d018f3e7ecd553938df0c4d982bd5584870b475"; // pragma: allowlist secret

const ENTRIES: Provenance[] = [
  {
    source: "fjc",
    external_record_id: "federal-judicial-service.csv",
    retrieved_at: "2026-09-16T23:46:51.974414Z",
    raw_sha256: SHA,
    parser_version: "2026.09.1",
    ingest_run_id: "b7784a75-5690-42f1-a509-2e4cf88b9d75",
    synthetic: false,
  },
  {
    source: "fjc",
    external_record_id: "judges.csv",
    retrieved_at: "2026-09-16T23:46:50.406253Z",
    raw_sha256: "ffc63d463627d15343006d2e72e54751202d10fe1e702f837d6f3e885f865ac5", // pragma: allowlist secret
    parser_version: "2026.09.1",
    ingest_run_id: "b7784a75-5690-42f1-a509-2e4cf88b9d75",
    synthetic: false,
  },
];

function renderPanel(entries: Provenance[] = ENTRIES) {
  return render(
    <TooltipProvider>
      <ProvenancePanel entries={entries} issueTitle="Sonia Sotomayor (judge 3a22)" />
    </TooltipProvider>,
  );
}

describe("ProvenancePanel", () => {
  it("lists every artifact with its source, retrieval time, and truncated sha256", () => {
    renderPanel();

    const entries = screen.getAllByTestId("provenance-entry");
    expect(entries).toHaveLength(2);

    const first = within(entries[0]);
    expect(first.getByText(/Federal Judicial Center/)).toBeInTheDocument();
    expect(first.getByText("federal-judicial-service.csv")).toBeInTheDocument();
    expect(first.getByText("Sep 16, 2026, 11:46 PM UTC")).toBeInTheDocument();

    const truncated = first.getByTestId("hash-truncated");
    expect(truncated).toHaveTextContent("b6a69ef26d40…");
    expect(truncated).toHaveAccessibleName(`sha256 ${SHA}`);
  });

  it("copies the full sha256 to the clipboard", async () => {
    // user-event installs a clipboard stub on navigator for the test.
    const user = userEvent.setup();
    renderPanel();

    const button = screen.getAllByTestId("copy-hash")[0];
    expect(button).toHaveAccessibleName("Copy the full sha256");
    await user.click(button);

    expect(await navigator.clipboard.readText()).toBe(SHA);
    expect(button).toHaveAccessibleName("Copied the full sha256");
  });

  it("links the source export page and the data-issue template", () => {
    renderPanel();

    const exportLinks = screen.getAllByRole("link", { name: /Source export page/ });
    expect(exportLinks[0]).toHaveAttribute(
      "href",
      "https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export",
    );

    const issue = screen.getByTestId("report-data-issue");
    const href = new URL(issue.getAttribute("href") ?? "");
    expect(href.pathname).toBe("/nathanramoscfa/judge-metrics/issues/new");
    expect(href.searchParams.get("template")).toBe("data_source_issue.md");
    expect(href.searchParams.get("title")).toBe("data: Sonia Sotomayor (judge 3a22)");
  });

  it("renders an empty state without entries", () => {
    renderPanel([]);
    expect(screen.getByTestId("empty-state")).toHaveTextContent("No source record");
  });

  it("labels a synthetic artifact and takes a custom title", () => {
    render(
      <TooltipProvider>
        <ProvenancePanel
          title="Sources"
          entries={[{ ...ENTRIES[0], source: "synthetic", synthetic: true }]}
          issueTitle="Case SYN-2020-000005"
        />
      </TooltipProvider>,
    );
    expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByTestId("synthetic-badge")).toHaveTextContent("Synthetic");
    expect(screen.getByText(/Synthetic dataset/)).toBeInTheDocument();
  });
});
