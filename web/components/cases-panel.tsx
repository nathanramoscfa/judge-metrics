// web/components/cases-panel.tsx
// The judge page's "Cases" panel: how many cases carry an assignment to the
// judge, the span of their filing dates, and the link to the case list.
import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { JudgeDetail } from "@/lib/api/client";
import { formatDate, formatInteger } from "@/lib/format";

export function CasesPanel({ judge }: { judge: JudgeDetail }) {
  const window = judge.coverage;
  return (
    <Card size="sm" data-testid="cases-panel">
      <CardHeader>
        <CardTitle>
          <h2 id="cases-heading">Cases</h2>
        </CardTitle>
        <CardDescription>
          Cases with an assignment to this judge in the ingested sources, and the span of their
          filing dates.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Case count</dt>
          <dd className="font-semibold tabular-nums" data-testid="case-count">
            {formatInteger(judge.case_count)}
          </dd>
          <dt className="text-muted-foreground">Coverage</dt>
          <dd data-testid="case-coverage">
            {window ? (
              <>
                <time dateTime={window.earliest_filed ?? undefined}>{formatDate(window.earliest_filed)}</time>
                {" – "}
                <time dateTime={window.latest_filed ?? undefined}>{formatDate(window.latest_filed)}</time>
              </>
            ) : (
              "No case on file"
            )}
          </dd>
        </dl>
        {judge.case_count > 0 ? (
          <Button asChild variant="outline" size="sm" className="w-fit">
            <Link href={`/judges/${judge.id}/cases`} data-testid="cases-link">
              Browse cases
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">
            The Federal Judicial Center directory carries no case data; case-level sources arrive
            with the state-court pipelines.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
