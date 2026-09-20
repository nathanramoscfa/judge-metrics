// web/components/metric-panel.tsx
// A titled, anchored card of MetricStats: the section heading, a
// description, an optional window selector (a GET form), the stats, and
// the "View eligible cases" link to the judge's case list with the panel's
// filter. `MetricRow` places a judge's stat beside the court's pooled stat
// and the cohort-position line from the compare rows; `CohortPositionLine`
// is the one derived figure on the page (a count of judges, the cohort's
// median, the judge's rank), and it names the rows it was derived from.
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { MetricStat } from "@/components/metric-stat";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Observation } from "@/lib/api/client";
import {
  COHORTS,
  type CohortKind,
  type CohortPosition,
  formatDays,
  formatRate,
} from "@/lib/metrics";

export function MetricPanel({
  id,
  title,
  description,
  controls,
  casesHref,
  casesLabel = "View eligible cases",
  children,
}: {
  /** The section anchor: `pretrial`, `outcomes`, `disposition`, `sentencing`, `cases`. */
  id: string;
  title: string;
  description?: ReactNode;
  /** The window or cohort selectors, rendered under the description. */
  controls?: ReactNode;
  /** The judge's case list, filtered where the cases route supports it. */
  casesHref?: string;
  casesLabel?: string;
  children: ReactNode;
}) {
  return (
    <Card id={id} size="sm" data-testid="metric-panel" data-panel={id} className="scroll-mt-20">
      <CardHeader>
        <CardTitle>
          <h2 id={`${id}-heading`}>{title}</h2>
        </CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
        {controls ? <div className="flex flex-wrap items-center gap-4 pt-1">{controls}</div> : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {children}
        {casesHref ? (
          <Button asChild variant="outline" size="sm" className="w-fit">
            <Link href={casesHref} data-testid="eligible-cases-link">
              {casesLabel}
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** The comparison line under a judge's stat: where the judge falls in the cohort. */
export function CohortPositionLine({
  position,
  cohort,
  kind,
  compareHref,
}: {
  position: CohortPosition;
  cohort: CohortKind;
  kind: Observation["kind"];
  compareHref: string;
}) {
  const figure = (value: number | null) => (kind === "median" ? formatDays(value) : formatRate(value));
  return (
    <dl
      className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 rounded-md bg-muted/40 px-2 py-1.5 text-xs"
      data-testid="cohort-position"
    >
      <dt className="text-muted-foreground">Cohort</dt>
      <dd>{COHORTS[cohort]}</dd>
      <dt className="text-muted-foreground">Judges</dt>
      <dd className="tabular-nums">
        {position.judges} in the cohort, {position.published} with a published figure
      </dd>
      <dt className="text-muted-foreground">Cohort median</dt>
      <dd className="tabular-nums" data-testid="cohort-median">
        {figure(position.median)}
      </dd>
      <dt className="text-muted-foreground">This judge</dt>
      <dd className="tabular-nums" data-testid="cohort-rank">
        {position.rank === null
          ? "not ranked (figure withheld or not yet computed)"
          : `${position.rank} of ${position.published}, highest first`}
        {" · "}
        <Link href={compareHref} className="text-primary hover:underline" data-testid="compare-link">
          Compare
        </Link>
      </dd>
    </dl>
  );
}

/** A judge's stat beside the court's pooled stat, with the cohort line under the judge's. */
export function MetricRow({
  label,
  judge,
  court,
  comparison,
}: {
  label: string;
  judge: Observation;
  court?: Observation | null;
  comparison?: ReactNode;
}) {
  return (
    <div className="grid gap-2 md:grid-cols-[3fr_2fr]" data-testid="metric-row" data-slug={judge.slug}>
      <MetricStat observation={judge} label={label} comparison={comparison} />
      {court ? (
        <MetricStat observation={court} label={`${label} — court, pooled`} variant="compact" />
      ) : (
        <div
          className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground"
          data-testid="pooled-missing"
        >
          No pooled court value for this metric and window.
        </div>
      )}
    </div>
  );
}
