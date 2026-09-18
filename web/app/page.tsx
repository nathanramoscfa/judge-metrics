// web/app/page.tsx
// Home: the headline, the global search box, coverage summary tiles from the
// jurisdiction and list totals and the per-source case counts of /coverage,
// and the prominent methodology link. Rendered on every request so the
// counts are live, never baked in at build time.
import { ArrowRight, BookOpenText } from "lucide-react";
import Link from "next/link";

import { SearchForm } from "@/components/search-form";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getCoverage, listCourts, listJudges, listJurisdictions } from "@/lib/api/client";
import { formatInteger } from "@/lib/format";

export const dynamic = "force-dynamic";

function Tile({
  label,
  value,
  detail,
  testId,
}: {
  label: string;
  value: string;
  detail?: string;
  testId: string;
}) {
  return (
    <Card size="sm" data-testid={testId}>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <p className="text-3xl font-semibold tabular-nums">{value}</p>
        {detail ? <p className="text-xs text-muted-foreground">{detail}</p> : null}
      </CardContent>
    </Card>
  );
}

export default async function HomePage() {
  const [jurisdictions, judges, courts, coverage] = await Promise.all([
    listJurisdictions({ limit: 100 }),
    listJudges({ limit: 1 }),
    listCourts({ limit: 1 }),
    getCoverage(),
  ]);

  const firstError = [jurisdictions, judges, courts, coverage].find((result) => !result.ok);
  const cases = coverage.ok ? coverage.data.sources.reduce((sum, s) => sum + s.cases, 0) : 0;
  const syntheticCases = coverage.ok
    ? coverage.data.sources.filter((s) => s.synthetic).reduce((sum, s) => sum + s.cases, 0)
    : 0;

  return (
    <div className="flex flex-col gap-10">
      <section aria-labelledby="headline" className="flex flex-col items-center gap-6 py-6 text-center">
        <h1 id="headline" className="font-heading text-4xl font-semibold tracking-tight md:text-5xl">
          Judicial outcomes, measured from data
        </h1>
        <p className="max-w-2xl text-balance text-muted-foreground">
          Public judicial records, connected and measured, with every number traceable
          to the source artifact it came from.
        </p>
        <SearchForm size="large" className="max-w-2xl" />
      </section>

      <section aria-labelledby="coverage-heading" className="flex flex-col gap-4">
        <div className="flex items-baseline justify-between">
          <h2 id="coverage-heading" className="text-lg font-semibold">
            Coverage
          </h2>
          <Link href="/coverage" className="text-sm text-primary hover:underline">
            Coverage detail
          </Link>
        </div>
        {firstError && !firstError.ok ? (
          <ErrorState what="the coverage summary" error={firstError.error} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              testId="tile-jurisdictions"
              label="Jurisdictions covered"
              value={jurisdictions.ok ? formatInteger(jurisdictions.data.total) : "—"}
              detail={
                jurisdictions.ok
                  ? jurisdictions.data.items.map((item) => item.name).join(", ") || "None yet"
                  : undefined
              }
            />
            <Tile
              testId="tile-judges"
              label="Judges indexed"
              value={judges.ok ? formatInteger(judges.data.total) : "—"}
              detail="Article III judges from the Federal Judicial Center, plus any synthetic demo judges"
            />
            <Tile
              testId="tile-courts"
              label="Courts indexed"
              value={courts.ok ? formatInteger(courts.data.total) : "—"}
              detail="Federal courts from the FJC service records, plus any synthetic demo courts"
            />
            <Tile
              testId="tile-cases"
              label="Cases indexed"
              value={coverage.ok ? formatInteger(cases) : "—"}
              detail={
                syntheticCases > 0
                  ? `${formatInteger(syntheticCases)} synthetic demo cases; real case data begins with the first state-court pipeline`
                  : "Real case data begins with the first state-court pipeline (Phase 5)"
              }
            />
          </div>
        )}
      </section>

      <section aria-labelledby="methodology-heading">
        <Card>
          <CardHeader>
            <CardTitle>
              <h2 id="methodology-heading" className="flex items-center gap-2">
                <BookOpenText aria-hidden="true" className="size-5" />
                How the numbers are made
              </h2>
            </CardTitle>
            <CardDescription>
              Every published statistic shows its numerator, denominator, date range,
              coverage, and sample size, and traces to the raw records behind it. These
              statistics describe associations in available records; they do not prove
              that a judicial decision caused a later event.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/methodology" data-testid="methodology-link">
                Read the methodology
                <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
