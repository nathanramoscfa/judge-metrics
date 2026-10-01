// web/app/models/[modelId]/page.tsx
// The model card of an expected-outcome model, from GET /api/v1/models/{id}:
// what it predicts (target, window), its status, the synthetic badge, what it
// was fitted on (index events, outcome events, time range), the temporal
// validation summary with the ten calibration bins as a table, the
// coefficient table (estimate, bootstrap standard deviation, sign
// agreement), the versions and the content hash, and links to the
// methodology's adjusted statistics section and the model's section of the
// validation report. Every adjusted ratio links here (`ModelRef`). An
// unknown id (or a model of a snapshot no current figure cites) is a 404
// page; any other failure renders ErrorState. All text is React text nodes.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SyntheticBadge } from "@/components/badges";
import { ErrorState } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getModel, type ModelCard } from "@/lib/api/client";
import { formatDateTime, isUuid, titleCase, truncateHash } from "@/lib/format";
import { validationSectionUrl } from "@/lib/links";
import { formatCount, formatPeriod, formatRate, featureLabel } from "@/lib/metrics";

export const dynamic = "force-dynamic";

type Params = Promise<{ modelId: string }>;

const STATUS_TEXT: Record<ModelCard["status"], string> = {
  fitted: "Fitted: the published expected counts and ratios of this target and window come from this model.",
  insufficient_events:
    "Not fitted: too few outcome events per design column; no expected count is published from this model and every ratio citing it is withheld.",
  not_converged:
    "Not fitted: the solver did not converge; no expected count is published from this model and every ratio citing it is withheld.",
};

function targetLabel(model: Pick<ModelCard, "target" | "window_days">): string {
  const target = titleCase(model.target);
  return model.window_days === null ? target : `${target}, ${model.window_days} days`;
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { modelId } = await params;
  if (!isUuid(modelId)) return { title: "Model" };
  const result = await getModel(modelId);
  return { title: result.ok ? `Model: ${targetLabel(result.data)}` : "Model" };
}

/** A statistic to four decimals; a dash when undefined. */
function stat(value: number | null | undefined, digits = 4): string {
  return value === null || value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

/** A data level names the court or jurisdiction it stands for: link it. */
function LevelCell({ feature, level }: { feature: string | null; level: string | null }) {
  if (level === null) return <>—</>;
  if (isUuid(level) && (feature === "court" || feature === "jurisdiction")) {
    const href = feature === "court" ? `/courts/${level}` : `/jurisdictions/${level}`;
    return (
      <Link href={href} className="font-mono text-primary hover:underline">
        {truncateHash(level, 8)}
      </Link>
    );
  }
  return <>{featureLabel(level)}</>;
}

function ModelDetails({ model, methodologyUrl }: { model: ModelCard; methodologyUrl: string }) {
  const validation = model.validation;
  return (
    <>
      <section aria-labelledby="training-heading" className="grid gap-4 md:grid-cols-2">
        <Card size="sm" data-testid="model-training">
          <CardHeader>
            <CardTitle>
              <h2 id="training-heading">Training</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Source</dt>
              <dd>
                {model.source} {model.synthetic ? <SyntheticBadge className="ml-1" /> : null}
              </dd>
              <dt className="text-muted-foreground">Index events</dt>
              <dd className="tabular-nums" data-testid="model-index-events">
                {formatCount(model.training.index_events)}
              </dd>
              <dt className="text-muted-foreground">Outcome events</dt>
              <dd className="tabular-nums" data-testid="model-events">
                {formatCount(model.training.events)}
              </dd>
              <dt className="text-muted-foreground">Time range</dt>
              <dd data-testid="model-range">{formatPeriod(model.training.start, model.training.end)}</dd>
            </dl>
          </CardContent>
        </Card>
        <Card size="sm" data-testid="model-versions">
          <CardHeader>
            <CardTitle>
              <h2>Versions</h2>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Model</dt>
              <dd data-testid="model-version">{model.model_version}</dd>
              <dt className="text-muted-foreground">Specification</dt>
              <dd data-testid="model-spec-version">{model.spec_version}</dd>
              <dt className="text-muted-foreground">Code</dt>
              <dd className="font-mono text-xs">{model.code_version}</dd>
              <dt className="text-muted-foreground">Seed</dt>
              <dd className="font-mono text-xs">{model.seed}</dd>
              <dt className="text-muted-foreground">Fitted</dt>
              <dd>{formatDateTime(model.fitted_at)}</dd>
              <dt className="text-muted-foreground">Content hash</dt>
              <dd className="font-mono text-xs" title={model.content_hash} data-testid="model-hash">
                {truncateHash(model.content_hash)}
              </dd>
              <dt className="text-muted-foreground">Snapshot</dt>
              <dd className="font-mono text-xs" title={model.snapshot_hash}>
                {truncateHash(model.snapshot_hash)}
              </dd>
            </dl>
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="validation-heading" className="flex flex-col gap-3" data-testid="model-validation">
        <h2 id="validation-heading" className="text-lg font-semibold">
          Validation
        </h2>
        <p className="text-sm text-muted-foreground">
          A temporal split: fitted on the index events before{" "}
          {validation.split_cutoff ? formatDateTime(validation.split_cutoff) : "the cutoff"} (
          {formatCount(validation.train_index_events)} index events,{" "}
          {formatCount(validation.train_events)} outcomes) and scored on the{" "}
          {formatCount(validation.test_index_events)} after it ({formatCount(validation.test_events)}{" "}
          outcomes). The published model is refitted on both.
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="model-summary">
          <dt className="text-muted-foreground">Brier score</dt>
          <dd className="tabular-nums">{stat(validation.brier)}</dd>
          <dt className="text-muted-foreground">Brier skill</dt>
          <dd className="tabular-nums">{stat(validation.brier_skill)}</dd>
          <dt className="text-muted-foreground">AUC</dt>
          <dd className="tabular-nums">{stat(validation.auc)}</dd>
          <dt className="text-muted-foreground">Calibration in the large</dt>
          <dd className="tabular-nums">{stat(validation.calibration_in_the_large)}</dd>
          <dt className="text-muted-foreground">Calibration slope</dt>
          <dd className="tabular-nums">{stat(validation.calibration_slope)}</dd>
          <dt className="text-muted-foreground">Base rate (training)</dt>
          <dd className="tabular-nums">{formatRate(validation.base_rate_train)}</dd>
        </dl>
        {validation.bins.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="model-no-bins">
            No calibration bins: the model was not scored on a test set.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <Table data-testid="calibration-table">
              <caption className="sr-only">Calibration bins on the test set, by predicted probability.</caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Bin</TableHead>
                  <TableHead scope="col" className="text-right">
                    Index events
                  </TableHead>
                  <TableHead scope="col" className="text-right">
                    Mean predicted
                  </TableHead>
                  <TableHead scope="col" className="text-right">
                    Observed rate
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {validation.bins.map((bin) => (
                  <TableRow key={bin.bin} data-testid="calibration-bin">
                    <TableCell className="tabular-nums">{bin.bin}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatCount(bin.count)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatRate(bin.mean_predicted)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatRate(bin.observed_rate)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <section aria-labelledby="coefficients-heading" className="flex flex-col gap-3">
        <h2 id="coefficients-heading" className="text-lg font-semibold">
          Coefficients
        </h2>
        <p className="text-sm text-muted-foreground">
          Penalized log-odds per design column, with the standard deviation and the sign agreement
          over the bootstrap replicates. A coefficient describes the model&apos;s prediction, not an
          effect of the feature.
        </p>
        {model.coefficients.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="model-no-coefficients">
            No coefficients: the model was not fitted.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <Table data-testid="coefficient-table">
              <caption className="sr-only">The coefficients of the published fit, in design order.</caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Feature</TableHead>
                  <TableHead scope="col">Level</TableHead>
                  <TableHead scope="col">Reference</TableHead>
                  <TableHead scope="col" className="text-right">
                    Estimate
                  </TableHead>
                  <TableHead scope="col" className="text-right">
                    Bootstrap SD
                  </TableHead>
                  <TableHead scope="col" className="text-right">
                    Sign agreement
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {model.coefficients.map((row) => (
                  <TableRow key={row.column} data-testid="coefficient-row">
                    <TableCell>{row.feature === null ? "Intercept" : featureLabel(row.feature)}</TableCell>
                    <TableCell>
                      <LevelCell feature={row.feature} level={row.level} />
                    </TableCell>
                    <TableCell>
                      <LevelCell feature={row.feature} level={row.reference} />
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{stat(row.estimate, 3)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{stat(row.sd, 3)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatRate(row.sign_agreement, 0)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <section aria-labelledby="model-links-heading" className="flex flex-col gap-2 text-sm">
        <h2 id="model-links-heading" className="text-lg font-semibold">
          Methodology and validation
        </h2>
        <ul className="list-disc space-y-1 pl-6">
          <li>
            <Link href={methodologyUrl} className="text-primary hover:underline" data-testid="model-methodology-link">
              Adjusted statistics
            </Link>{" "}
            — the model, its features, the pooling, the interval, and the limitations of adjustment.
          </li>
          <li>
            <a
              href={validationSectionUrl(model.source, model.target, model.window_days)}
              className="text-primary hover:underline"
              data-testid="model-validation-link"
            >
              Validation report: {model.source}: {model.target}
              {model.window_days === null ? "" : `, ${model.window_days} days`}
            </a>{" "}
            — calibration, temporal transport, feature stability, and subgroup calibration.
          </li>
        </ul>
      </section>
    </>
  );
}

export default async function ModelPage({ params }: { params: Params }) {
  const { modelId } = await params;
  if (!isUuid(modelId)) notFound();
  const result = await getModel(modelId);
  if (!result.ok) {
    if (result.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Model</h1>
        <ErrorState what="this model" error={result.error} />
      </div>
    );
  }
  const model = result.data;
  // The API anchors its methodology link at the adjusted statistics section.
  const methodologyUrl = model.methodology_url || "/methodology#adjusted-statistics";
  return (
    <article className="flex flex-col gap-8" data-testid="model-card" data-status={model.status}>
      <header className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">Expected-outcome model</p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="model-target">
            {targetLabel(model)}
          </h1>
          {model.synthetic ? <SyntheticBadge /> : null}
        </div>
        <p className="text-sm" data-testid="model-status" data-status={model.status}>
          {STATUS_TEXT[model.status]}
        </p>
        <p className="max-w-3xl text-sm text-muted-foreground">
          The model predicts the probability of the target outcome for each index event from case
          and history features under the source&apos;s average practice; a judge&apos;s expected count
          is the sum of those probabilities over the judge&apos;s cohort. It describes associations in
          the records, not the effect of any decision.
        </p>
      </header>
      <ModelDetails model={model} methodologyUrl={methodologyUrl} />
    </article>
  );
}
