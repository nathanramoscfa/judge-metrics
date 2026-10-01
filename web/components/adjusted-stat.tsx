// web/components/adjusted-stat.tsx
// The presentation-rule component of an adjusted statistic: the only way an
// observed-to-expected ratio (`kind: observed_expected`) is rendered as a
// stat anywhere in the web tier. It shows the label and the synthetic badge;
// for a published ratio, the observed and model-expected events, the pooled
// ratio with its 95% bootstrap interval, the pooling weight as a sentence,
// the sample size (eligible members and the members in the ratio), and the
// brief's interpretation of an O/E ratio beside the figures; for a
// suppressed one, the reason in words and no figure region at all. Always:
// the period, the coverage, the cohort definition when the page passes one,
// the model link (`/models/<id>`), and the methodology version as visible
// text linking to the metric's section. Nothing here claims a cause: the
// interpretation is the brief's own sentence, passed from the registry.
import { BookOpen, Boxes } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { SyntheticBadge } from "@/components/badges";
import type { Observation } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import {
  adjustedSuppressionText,
  formatCount,
  formatCoverage,
  formatExpected,
  formatPeriod,
  formatRatio,
  formatRatioInterval,
  isSuppressed,
  methodologyHref,
  modelHref,
  poolingSentence,
  windowKey,
} from "@/lib/metrics";

/** The suppression notice of an adjusted row (the stat and the compare table share it). */
export function adjustedSuppressionNotice(
  observation: Pick<Observation, "suppression_reason" | "suppression_threshold">,
  minimumExpected: number | null | undefined,
): string {
  return adjustedSuppressionText(
    observation.suppression_reason,
    observation.suppression_threshold,
    minimumExpected,
  );
}

export function AdjustedStat({
  observation,
  label,
  interpretation,
  minimumExpected,
  cohortDefinition,
  comparison,
  className,
}: {
  observation: Observation;
  label: string;
  /** The brief's reading of an O/E ratio (`Registry.adjustment.interpretation`). */
  interpretation: string;
  /** The registry's minimum expected count, for the suppression reason. */
  minimumExpected?: number | null;
  /** "Expected counts from model …; compared within …" (`adjustedCohortDefinition`). */
  cohortDefinition?: string | null;
  /** Rendered under the figures: the cohort position line. */
  comparison?: ReactNode;
  className?: string;
}) {
  const suppressed = isSuppressed(observation);
  const href = observation.methodology_url || methodologyHref(observation.slug, observation.version);
  const model = observation.model;

  return (
    <div
      data-testid="adjusted-stat"
      data-slug={observation.slug}
      data-window={windowKey(observation.window_days)}
      data-suppressed={suppressed ? "true" : "false"}
      data-reason={observation.suppression_reason ?? undefined}
      className={cn("flex flex-col gap-1.5 rounded-lg border p-3 text-sm", className)}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium" data-testid="adjusted-label">
          {label}
        </span>
        {observation.synthetic ? <SyntheticBadge /> : null}
      </div>

      {suppressed ? (
        <p
          role="status"
          data-testid="adjusted-suppression"
          className="rounded-md border border-dashed px-2 py-1.5 text-sm text-muted-foreground"
        >
          {adjustedSuppressionNotice(observation, minimumExpected)}
        </p>
      ) : (
        <div data-testid="adjusted-figures" className="flex flex-col gap-0.5">
          <p className="text-2xl font-semibold tabular-nums">
            <span data-testid="adjusted-ratio">{formatRatio(observation.ratio)}</span>
            <span className="ml-1.5 text-xs font-normal text-muted-foreground">
              observed / expected, pooled
            </span>
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            <dt className="text-muted-foreground">Observed events</dt>
            <dd className="font-mono tabular-nums" data-testid="adjusted-observed">
              {formatCount(observation.numerator)}
            </dd>
            <dt className="text-muted-foreground">Expected events</dt>
            <dd className="font-mono tabular-nums" data-testid="adjusted-expected">
              {formatExpected(observation.expected)}
            </dd>
            <dt className="text-muted-foreground">Interval</dt>
            <dd className="tabular-nums" data-testid="adjusted-interval">
              {formatRatioInterval(observation.ratio_lower, observation.ratio_upper)}
            </dd>
            <dt className="text-muted-foreground">Pooling</dt>
            <dd data-testid="adjusted-pooling">{poolingSentence(observation.pooling_weight)}</dd>
            <dt className="text-muted-foreground">Sample size</dt>
            <dd className="tabular-nums" data-testid="adjusted-sample">
              {formatCount(observation.eligible_count)} eligible,{" "}
              {formatCount(observation.denominator)} in the ratio
            </dd>
          </dl>
          <p className="pt-1 text-xs text-muted-foreground" data-testid="adjusted-interpretation">
            {interpretation}
          </p>
        </div>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">Period</dt>
        <dd data-testid="adjusted-period" data-start={observation.period_start} data-end={observation.period_end}>
          {formatPeriod(observation.period_start, observation.period_end)}
        </dd>
        <dt className="text-muted-foreground">Coverage</dt>
        <dd data-testid="adjusted-coverage">{formatCoverage(observation.coverage, observation.source)}</dd>
        {cohortDefinition ? (
          <>
            <dt className="text-muted-foreground">Cohort</dt>
            <dd data-testid="adjusted-cohort">{cohortDefinition}</dd>
          </>
        ) : null}
      </dl>

      {comparison ? <div data-testid="adjusted-comparison">{comparison}</div> : null}

      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {model ? (
          <Link
            href={modelHref(model.id)}
            className="inline-flex items-center gap-1 text-primary hover:underline"
            data-testid="adjusted-model"
          >
            <Boxes aria-hidden="true" className="size-3" />
            Model {model.model_version} (specification {model.spec_version})
          </Link>
        ) : null}
        <Link
          href={href}
          className="inline-flex items-center gap-1 text-primary hover:underline"
          data-testid="methodology-link"
          title={`Methodology: ${observation.name} (definition version ${observation.version})`}
        >
          <BookOpen aria-hidden="true" className="size-3" />
          <span data-testid="methodology-version">Methodology {observation.methodology_version}</span>
        </Link>
      </p>
    </div>
  );
}
