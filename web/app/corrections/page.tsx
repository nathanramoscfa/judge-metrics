// web/app/corrections/page.tsx
// /corrections: submit a data-correction request. A server page that reads
// `target_type`, `target_id`, and `label` from the query (the "Report a data
// error" links prefill them), looks the target up when the type and id are
// valid so the summary shows what the request is about, explains the
// correction process, and hosts the client form (components/correction-form.tsx).
// The form posts to the route handler at /api/corrections; this page never
// calls the API's write path itself.
import type { Metadata } from "next";
import Link from "next/link";

import { SyntheticBadge } from "@/components/badges";
import { CorrectionForm, type CorrectionTarget } from "@/components/correction-form";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getCase,
  getCourt,
  getJudge,
  getObservationProvenance,
} from "@/lib/api/client";
import { type CorrectionTargetType, TARGET_TYPE_LABELS, isCorrectionTargetType } from "@/lib/corrections";
import { isUuid, titleCase } from "@/lib/format";
import { formatPeriod } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Report a data error" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

interface TargetSummary {
  title: string;
  detail: string;
  href: string | null;
  synthetic: boolean;
}

/** What the API knows about the target, or null when it does not (the form still submits). */
async function summarize(type: CorrectionTargetType, id: string): Promise<TargetSummary | null> {
  switch (type) {
    case "judge": {
      const judge = await getJudge(id);
      if (!judge.ok) return null;
      const current = judge.data.service.find((record) => record.end_date === null);
      return {
        title: judge.data.canonical_name,
        detail: current ? `${titleCase(current.position_type)}, ${current.court.canonical_name}` : `Status: ${titleCase(judge.data.status)}`,
        href: `/judges/${id}`,
        synthetic: judge.data.synthetic,
      };
    }
    case "court": {
      const court = await getCourt(id);
      if (!court.ok) return null;
      return {
        title: court.data.canonical_name,
        detail: `${titleCase(court.data.court_type)} court${court.data.state_code ? `, ${court.data.state_code}` : ""}`,
        href: `/courts/${id}`,
        synthetic: court.data.synthetic,
      };
    }
    case "case": {
      const c = await getCase(id);
      if (!c.ok) return null;
      return {
        title: `Case ${c.data.case_number}`,
        detail: `${c.data.court.canonical_name}; ${titleCase(c.data.case_type)}, ${titleCase(c.data.status)}`,
        href: `/cases/${id}`,
        synthetic: c.data.synthetic,
      };
    }
    case "metric_observation": {
      const trace = await getObservationProvenance(id);
      if (!trace.ok) return null;
      const o = trace.data.observation;
      return {
        title: o.name,
        detail: `${o.subject_type === "judge" ? "Judge" : "Court"} ${o.subject_id}; ${formatPeriod(o.period_start, o.period_end)}; definition version ${o.version}, methodology ${o.methodology_version}`,
        href: `/${o.subject_type === "judge" ? "judges" : "courts"}/${o.subject_id}`,
        synthetic: o.synthetic,
      };
    }
  }
}

export default async function CorrectionsPage({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const rawType = firstValue(query.target_type);
  const rawId = firstValue(query.target_id);
  const label = firstValue(query.label).slice(0, 200) || null;
  const valid = isCorrectionTargetType(rawType) && isUuid(rawId);
  const target: CorrectionTarget | null = valid ? { type: rawType, id: rawId } : null;
  const summary = valid ? await summarize(rawType, rawId) : null;

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Report a data error</h1>
        <p className="max-w-3xl text-muted-foreground">
          Tell us what is wrong with a judge, court, case, or published number and how to reach
          you. Every request is logged for review against the source records; demonstrably
          incorrect, sealed, expunged, misidentified, or legally restricted information is
          corrected or suppressed with an internal audit trail.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <section aria-labelledby="form-heading" className="flex flex-col gap-4">
          <h2 id="form-heading" className="text-lg font-semibold">
            The request
          </h2>
          {target ? (
            <div
              className="flex flex-col gap-1 rounded-xl border bg-muted/30 p-4 text-sm"
              data-testid="target-summary"
            >
              <p className="text-xs text-muted-foreground">
                {TARGET_TYPE_LABELS[target.type as CorrectionTargetType]}
              </p>
              {summary ? (
                <>
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {summary.href ? (
                      <Link href={summary.href} className="text-primary hover:underline">
                        {summary.title}
                      </Link>
                    ) : (
                      summary.title
                    )}
                    {summary.synthetic ? <SyntheticBadge /> : null}
                  </p>
                  <p className="text-xs text-muted-foreground">{summary.detail}</p>
                </>
              ) : (
                <p className="text-xs text-muted-foreground" data-testid="target-unknown">
                  {label ? `${label} — ` : ""}the API does not currently return this record; you can
                  still send the request and it will be checked against the id.
                </p>
              )}
            </div>
          ) : rawType || rawId ? (
            <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground" data-testid="target-invalid">
              The link that brought you here named no valid record; choose the record type and
              paste the id from the page address below.
            </p>
          ) : null}
          <CorrectionForm target={target} label={summary?.title ?? label} />
        </section>

        <Card size="sm" data-testid="correction-process">
          <CardHeader>
            <CardTitle>
              <h2>How corrections are handled</h2>
            </CardTitle>
            <CardDescription>The process the methodology commits to.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-2 pl-5 text-sm">
              <li>
                <span className="font-medium">Received.</span> Your request is stored with a
                request id; the page you land on shows it and nothing you typed. Keep the id to
                ask about the request.
              </li>
              <li>
                <span className="font-medium">Reviewed against the source.</span> A reviewer
                compares the record with the raw artifact it was derived from (every row cites
                one, with its sha256) and with the material you linked.
              </li>
              <li>
                <span className="font-medium">Corrected or suppressed.</span> A demonstrably
                wrong, sealed, expunged, misidentified, or legally restricted record is corrected
                or withheld from every public surface, and every published number it entered is
                recomputed from a new snapshot. An arrest, a charge, a conviction, and a
                dismissal are separate facts; a correction changes only the one that is wrong.
              </li>
              <li>
                <span className="font-medium">Audited.</span> Every change is recorded in an
                append-only audit log; the raw source artifact is never altered.
              </li>
              <li>
                <span className="font-medium">Answered.</span> You are contacted only about this
                request, at the contact you gave, which is stored encrypted and readable only by
                the reviewers.
              </li>
            </ol>
            <p className="mt-3 text-xs text-muted-foreground">
              A wrong or changed data source (rather than one record) can also be reported on
              the{" "}
              <Link href="/coverage" className="text-primary hover:underline">
                coverage page
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    </article>
  );
}
