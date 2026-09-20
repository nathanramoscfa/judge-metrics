// web/components/metric-stat.tsx
// The presentation-rule component: the only way an observation (a published
// number) is rendered anywhere in the web tier. It shows the label, the
// primary figure (a rate as a percentage, a median as days, a count as an
// integer), the numerator over the denominator, the eligible count when it
// differs from the denominator, the interval with its method, the period,
// the coverage (source, coverage window, whether the outcome is
// observable), the sample-size line, the methodology link anchored at the
// metric's slug, and the synthetic badge. A suppressed observation renders
// the suppression notice with the threshold in place of every figure —
// nothing numeric leaves the API for such a row, and nothing numeric is
// rendered here beyond the threshold itself, the period, and the coverage
// window. `MetricNotObservable` is the row for a metric the source cannot
// document at all.
import { BookOpen } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { SyntheticBadge } from "@/components/badges";
import type { Observation } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import {
  dimensionLabel,
  formatCount,
  formatCoverage,
  formatFraction,
  formatInterval,
  formatPeriod,
  isSuppressed,
  methodologyHref,
  primaryFigure,
  windowKey,
} from "@/lib/metrics";

const KIND_NOUN: Record<Observation["kind"], string> = {
  count: "count",
  share: "share",
  windowed_rate: "fixed-window rate",
  survival: "Kaplan–Meier cumulative incidence",
  distribution: "distribution",
  median: "median",
};

function figureUnit(observation: Observation): string {
  if (observation.kind === "median") return "median";
  if (observation.kind === "count") return "count";
  if (observation.kind === "distribution") return "share of disposed cases";
  return KIND_NOUN[observation.kind];
}

export function suppressionNotice(observation: Pick<Observation, "suppression_threshold">): string {
  return `Suppressed: fewer than ${observation.suppression_threshold} eligible members in the denominator; the number is withheld to protect a small cohort.`;
}

export function MetricStat({
  observation,
  label,
  variant = "default",
  comparison,
  className,
}: {
  observation: Observation;
  label: string;
  /** `compact` is the pooled court value beside a judge's stat: every field, smaller. */
  variant?: "default" | "compact";
  /** Rendered under the figures: the cohort position line. */
  comparison?: ReactNode;
  className?: string;
}) {
  const suppressed = isSuppressed(observation);
  const compact = variant === "compact";
  const dimension = dimensionLabel(observation.dimension_value);
  const href = observation.methodology_url || methodologyHref(observation.slug, observation.version);
  const showEligible =
    observation.denominator !== null && observation.eligible_count !== observation.denominator;

  return (
    <div
      data-testid="metric-stat"
      data-slug={observation.slug}
      data-window={windowKey(observation.window_days)}
      data-dimension={observation.dimension_value ?? undefined}
      data-suppressed={suppressed ? "true" : "false"}
      data-variant={variant}
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border p-3",
        compact ? "bg-muted/30 text-xs" : "text-sm",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("font-medium", compact ? "text-xs" : "text-sm")} data-testid="metric-label">
          {label}
          {dimension ? <span className="text-muted-foreground"> · {dimension}</span> : null}
        </span>
        {observation.synthetic ? <SyntheticBadge /> : null}
      </div>

      {suppressed ? (
        <p
          role="status"
          data-testid="suppression-notice"
          className={cn("rounded-md border border-dashed px-2 py-1.5 text-muted-foreground", compact ? "text-xs" : "text-sm")}
        >
          {suppressionNotice(observation)}
        </p>
      ) : (
        <div data-testid="metric-figures" className="flex flex-col gap-0.5">
          <p className={cn("font-semibold tabular-nums", compact ? "text-base" : "text-2xl")}>
            <span data-testid="metric-figure">{primaryFigure(observation)}</span>
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">{figureUnit(observation)}</span>
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {observation.kind !== "count" ? (
              <>
                <dt className="text-muted-foreground">Numerator / denominator</dt>
                <dd className="font-mono tabular-nums" data-testid="metric-fraction">
                  {formatFraction(observation.numerator, observation.denominator)}
                </dd>
              </>
            ) : null}
            {showEligible ? (
              <>
                <dt className="text-muted-foreground">Eligible</dt>
                <dd className="font-mono tabular-nums" data-testid="metric-eligible">
                  {formatCount(observation.eligible_count)}
                </dd>
              </>
            ) : null}
            {observation.interval_method ? (
              <>
                <dt className="text-muted-foreground">Interval</dt>
                <dd className="tabular-nums" data-testid="metric-interval">
                  {formatInterval(observation.lower, observation.upper, observation.interval_method)}
                </dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Sample size</dt>
            <dd className="tabular-nums" data-testid="metric-sample">
              {formatCount(observation.eligible_count)} eligible
              {observation.denominator !== null && observation.kind !== "count"
                ? `, ${formatCount(observation.denominator)} in the denominator`
                : ""}
            </dd>
          </dl>
        </div>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">Period</dt>
        <dd data-testid="metric-period" data-start={observation.period_start} data-end={observation.period_end}>
          {formatPeriod(observation.period_start, observation.period_end)}
        </dd>
        <dt className="text-muted-foreground">Coverage</dt>
        <dd data-testid="metric-coverage">{formatCoverage(observation.coverage, observation.source)}</dd>
      </dl>

      {comparison ? <div data-testid="metric-comparison">{comparison}</div> : null}

      <p className="text-xs">
        <Link
          href={href}
          className="inline-flex items-center gap-1 text-primary hover:underline"
          data-testid="methodology-link"
          title={`Methodology: ${observation.name} (definition version ${observation.version}, methodology ${observation.methodology_version})`}
        >
          <BookOpen aria-hidden="true" className="size-3" />
          Methodology
        </Link>
      </p>
    </div>
  );
}

/** The row for a metric whose outcome the source cannot document: no number, never a zero. */
export function MetricNotObservable({
  label,
  slug,
  source,
  methodologyUrl,
  version,
}: {
  label: string;
  slug: string;
  source: string;
  methodologyUrl?: string | null;
  version?: string;
}) {
  return (
    <div
      data-testid="metric-stat"
      data-slug={slug}
      data-window="none"
      data-suppressed="false"
      data-observable="false"
      className="flex flex-col gap-1.5 rounded-lg border border-dashed p-3 text-sm"
    >
      <span className="font-medium" data-testid="metric-label">
        {label}
      </span>
      <p role="status" data-testid="not-observable" className="text-xs text-muted-foreground">
        Not observable in this source: the {source} source does not document this outcome, so no
        number is published (never a zero).
      </p>
      <p className="text-xs">
        <Link
          href={methodologyUrl || methodologyHref(slug, version)}
          className="inline-flex items-center gap-1 text-primary hover:underline"
          data-testid="methodology-link"
        >
          <BookOpen aria-hidden="true" className="size-3" />
          Methodology
        </Link>
      </p>
    </div>
  );
}
