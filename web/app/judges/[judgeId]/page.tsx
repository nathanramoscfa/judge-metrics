// web/app/judges/[judgeId]/page.tsx
// A judge: identity and status, the service timeline as a sortable table,
// the cases panel (count, coverage window, link to the case list), and the
// source coverage panel. Metrics and cohorts arrive in Phase 3; the page
// says so rather than showing empty charts.
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { StatusBadge, SyntheticBadge } from "@/components/badges";
import { CasesPanel } from "@/components/cases-panel";
import { ProvenancePanel } from "@/components/provenance-panel";
import { ServiceTable } from "@/components/service-table";
import { ErrorState } from "@/components/states";
import { getJudge, type JudgeDetail } from "@/lib/api/client";
import { isUuid } from "@/lib/format";
import { sourceLinks } from "@/lib/links";

export const dynamic = "force-dynamic";

type Params = Promise<{ judgeId: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) return { title: "Judge" };
  const result = await getJudge(judgeId);
  return { title: result.ok ? result.data.canonical_name : "Judge" };
}

function fjcNid(judge: JudgeDetail): string | null {
  const nid = judge.external_ids.fjc_nid;
  return typeof nid === "string" && /^\d+$/.test(nid) ? nid : null;
}

function birthYear(judge: JudgeDetail): string | null {
  const year = judge.metadata.birth_year;
  return typeof year === "number" ? String(year) : null;
}

export default async function JudgePage({ params }: { params: Params }) {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) notFound();

  const result = await getJudge(judgeId);
  if (!result.ok) {
    if (result.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Judge</h1>
        <ErrorState what="this judge" error={result.error} />
      </div>
    );
  }

  const judge = result.data;
  const nid = fjcNid(judge);
  const born = birthYear(judge);
  const fjc = sourceLinks("fjc");
  const current = judge.service.filter((record) => record.end_date === null);

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="judge-name">
            {judge.canonical_name}
          </h1>
          <StatusBadge status={judge.status} />
          {judge.synthetic ? <SyntheticBadge /> : null}
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          {current.length > 0 ? (
            <div className="flex gap-1.5">
              <dt>Current:</dt>
              <dd className="text-foreground">
                {current.map((record) => `${record.position_type}, ${record.court.canonical_name}`).join("; ")}
              </dd>
            </div>
          ) : null}
          {born ? (
            <div className="flex gap-1.5">
              <dt>Born:</dt>
              <dd className="text-foreground">{born}</dd>
            </div>
          ) : null}
          {nid && fjc.recordUrl ? (
            <div className="flex gap-1.5">
              <dt>FJC biography:</dt>
              <dd>
                <a href={fjc.recordUrl(nid)} className="font-mono text-primary hover:underline">
                  nid {nid}
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
      </header>

      <section aria-labelledby="service-heading" className="flex flex-col gap-3">
        <h2 id="service-heading" className="text-lg font-semibold">
          Service
        </h2>
        <p className="text-sm text-muted-foreground">
          Every appointment on file, oldest first. Senior status does not end an
          appointment; a judge on senior status is still serving.
        </p>
        <ServiceTable records={judge.service} />
      </section>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <section aria-labelledby="metrics-heading" className="flex flex-col gap-3">
          <h2 id="metrics-heading" className="text-lg font-semibold">
            Outcome metrics
          </h2>
          <div className="rounded-xl border border-dashed px-6 py-8 text-sm text-muted-foreground">
            Pretrial, disposition, sentencing, and subsequent-event metrics arrive in
            Phase 3 with the metrics engine. Every number will show its numerator,
            denominator, date range, coverage, sample size, and methodology version.
          </div>
        </section>
        <div className="flex flex-col gap-6">
          <section aria-labelledby="cases-heading">
            <CasesPanel judge={judge} />
          </section>
          <ProvenancePanel
            entries={judge.provenance}
            issueTitle={`${judge.canonical_name} (judge ${judge.id})`}
          />
        </div>
      </div>
    </article>
  );
}
